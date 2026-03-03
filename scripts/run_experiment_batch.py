#!/usr/bin/env python3
"""Batch runner for ROS-MCP experiments with rosbag + Gemini telemetry."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_run_artifacts import validate_attempt_dir


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(data, ensure_ascii=True) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def stop_process_group(proc: subprocess.Popen, *, timeout_sec: float) -> int:
    if proc.poll() is not None:
        return int(proc.returncode or 0)

    try:
        os.killpg(proc.pid, signal.SIGINT)
    except ProcessLookupError:
        return int(proc.poll() or 0)

    try:
        return int(proc.wait(timeout=timeout_sec))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return int(proc.poll() or 0)
        try:
            return int(proc.wait(timeout=10))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            return int(proc.wait())


def find_next_attempt(run_dir: Path) -> int:
    attempts_dir = run_dir / "attempts"
    if not attempts_dir.exists():
        return 1
    max_idx = 0
    for child in attempts_dir.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith("attempt_"):
            continue
        suffix = child.name.split("_", 1)[-1]
        if suffix.isdigit():
            max_idx = max(max_idx, int(suffix))
    return max_idx + 1


def make_run_id(task: str, condition: str, env: str, idx: int) -> str:
    return f"{task}_{condition}_{env.upper()}_{idx:03d}"


def ensure_command_exists(command: str) -> None:
    if shutil.which(command):
        return
    raise RuntimeError(f"Required command not found: {command}")


def load_profiles(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(f"Profile file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid profile JSON: {path} ({exc})") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Profile root must be a JSON object")
    return data


def resolve_task_config(
    profiles: dict[str, Any],
    *,
    task: str,
    condition: str,
    env: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = profiles.get("tasks", {})
    if task not in tasks:
        raise RuntimeError(f"Unknown task: {task}")
    task_cfg = tasks[task]
    conditions = task_cfg.get("conditions", {})
    if condition not in conditions:
        raise RuntimeError(f"Unknown condition '{condition}' for task '{task}'")
    condition_cfg = conditions[condition]
    envs = condition_cfg.get("environments", [])
    if env not in envs:
        raise RuntimeError(
            f"Environment '{env}' is not allowed for {task}/{condition}. Allowed: {envs}"
        )
    topics = task_cfg.get("topics", [])
    if not isinstance(topics, list) or not topics:
        raise RuntimeError(f"No topics configured for task {task}")
    return task_cfg, condition_cfg


def status_is_completed_and_valid(run_dir: Path) -> bool:
    status = read_json(run_dir / "status.json")
    if status.get("status") != "completed":
        return False
    raw_attempt_dir = status.get("attempt_dir")
    if not isinstance(raw_attempt_dir, str) or not raw_attempt_dir:
        return False
    attempt_dir = Path(raw_attempt_dir)
    if not attempt_dir.is_absolute():
        attempt_dir = (run_dir / attempt_dir).resolve()
    ok, _ = validate_attempt_dir(attempt_dir)
    return ok


@dataclass
class RunnerConfig:
    workspace_root: Path
    output_root: Path
    profiles_path: Path
    task: str
    condition: str
    env: str
    repeats: int
    start_run: int
    resume: bool
    rosbag_warmup_sec: float
    rosbag_shutdown_sec: float
    continue_on_failure: bool
    gemini_args: list[str]


def run_one(
    cfg: RunnerConfig,
    *,
    run_index: int,
    task_cfg: dict[str, Any],
    condition_cfg: dict[str, Any],
    manifest_path: Path,
) -> tuple[bool, str]:
    task = cfg.task
    condition = cfg.condition
    env = cfg.env
    run_id = make_run_id(task, condition, env, run_index)

    run_dir = cfg.output_root / task / condition / env / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    attempt_index = find_next_attempt(run_dir)
    attempt_dir = run_dir / "attempts" / f"attempt_{attempt_index:03d}"
    rosbag_dir = attempt_dir / "rosbag"
    gemini_dir = attempt_dir / "gemini"
    gemini_raw_root = attempt_dir / "gemini_raw"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    gemini_dir.mkdir(parents=True, exist_ok=True)
    gemini_raw_root.mkdir(parents=True, exist_ok=True)

    status_path = run_dir / "status.json"
    run_meta_path = run_dir / "run_meta.json"
    attempt_meta_path = attempt_dir / "run_meta.json"
    rosbag_log_path = attempt_dir / "rosbag_record.log"
    wrapper_script = cfg.workspace_root / "scripts" / "run_gemini_with_timing.sh"

    prompt = str(task_cfg.get("prompt", "")).strip()
    topics = [str(t) for t in task_cfg.get("topics", [])]
    timeout_sec = float(task_cfg.get("timeout_sec", 0.0))
    condition_desc = str(condition_cfg.get("description", "")).strip()

    session_id = f"{run_id}_A{attempt_index:03d}"
    started_at = now_utc()

    running_status = {
        "run_id": run_id,
        "task": task,
        "condition": condition,
        "environment": env,
        "run_index": run_index,
        "attempt_index": attempt_index,
        "attempt_dir": str(attempt_dir),
        "status": "running",
        "started_at": started_at,
        "updated_at": started_at,
    }
    write_json_atomic(status_path, running_status)
    append_jsonl(
        manifest_path,
        {
            "event": "run_started",
            "timestamp": started_at,
            "run_id": run_id,
            "run_index": run_index,
            "attempt_index": attempt_index,
            "status": "running",
            "attempt_dir": str(attempt_dir),
        },
    )

    rosbag_cmd = ["ros2", "bag", "record", "-o", str(rosbag_dir), *topics]
    rosbag_proc: subprocess.Popen | None = None
    gemini_exit_code: int | None = None
    rosbag_exit_code: int | None = None
    failure_reason = ""

    try:
        with rosbag_log_path.open("w", encoding="utf-8") as bag_log:
            rosbag_proc = subprocess.Popen(
                rosbag_cmd,
                cwd=str(cfg.workspace_root),
                stdout=bag_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            time.sleep(max(0.0, cfg.rosbag_warmup_sec))
            if rosbag_proc.poll() is not None:
                raise RuntimeError("ros2 bag record terminated immediately; check rosbag_record.log")

            print("")
            print(f"[run] {run_id} (attempt {attempt_index})")
            print(f"[run] task={task} condition={condition} env={env}")
            if condition_desc:
                print(f"[run] condition_desc={condition_desc}")
            if timeout_sec > 0.0:
                print(f"[run] suggested_timeout_sec={timeout_sec:.1f}")
            print(f"[run] prompt: {prompt}")
            print("[run] Gemini CLI will start now. Complete the interaction and then exit Gemini.")
            print("")

            gemini_env = os.environ.copy()
            gemini_env["GEMINI_TIMING_LOG_DIR"] = str(gemini_raw_root)
            gemini_env["GEMINI_TIMING_SESSION_ID"] = session_id
            wrapper_cmd = [str(wrapper_script), *cfg.gemini_args]
            # Keep stdin/stdout/stderr inherited from the current terminal for full interactivity.
            gemini_exit_code = subprocess.call(wrapper_cmd, cwd=str(cfg.workspace_root), env=gemini_env)

            rosbag_exit_code = stop_process_group(rosbag_proc, timeout_sec=cfg.rosbag_shutdown_sec)

        raw_session_dir = gemini_raw_root / session_id
        for name in ("session_report.json", "session_report.txt", "telemetry_raw.jsonl"):
            src = raw_session_dir / name
            if src.exists():
                shutil.copy2(src, gemini_dir / name)

        ok_artifacts, artifact_errors = validate_attempt_dir(attempt_dir)

        if gemini_exit_code != 0:
            failure_reason = f"gemini_exit_code={gemini_exit_code}"
        elif not ok_artifacts:
            failure_reason = "; ".join(artifact_errors)

        finished_at = now_utc()
        final_status = "completed" if not failure_reason else "failed"

        run_meta = {
            "run_id": run_id,
            "task": task,
            "condition": condition,
            "environment": env,
            "run_index": run_index,
            "attempt_index": attempt_index,
            "attempt_dir": str(attempt_dir),
            "prompt": prompt,
            "topics": topics,
            "timeout_sec": timeout_sec,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": final_status,
            "gemini_exit_code": gemini_exit_code,
            "rosbag_exit_code": rosbag_exit_code,
            "artifact_errors": artifact_errors if not ok_artifacts else [],
            "failure_reason": failure_reason,
            "rosbag_log": str(rosbag_log_path),
        }
        write_json_atomic(attempt_meta_path, run_meta)
        write_json_atomic(run_meta_path, run_meta)

        write_json_atomic(
            status_path,
            {
                **running_status,
                "status": final_status,
                "finished_at": finished_at,
                "updated_at": finished_at,
                "failure_reason": failure_reason,
            },
        )
        append_jsonl(
            manifest_path,
            {
                "event": "run_finished",
                "timestamp": finished_at,
                "run_id": run_id,
                "run_index": run_index,
                "attempt_index": attempt_index,
                "status": final_status,
                "attempt_dir": str(attempt_dir),
                "gemini_exit_code": gemini_exit_code,
                "rosbag_exit_code": rosbag_exit_code,
                "failure_reason": failure_reason,
            },
        )

        return final_status == "completed", failure_reason
    except KeyboardInterrupt:
        failure_reason = "interrupted_by_user"
        if rosbag_proc is not None:
            rosbag_exit_code = stop_process_group(rosbag_proc, timeout_sec=cfg.rosbag_shutdown_sec)
        finished_at = now_utc()
        write_json_atomic(
            status_path,
            {
                **running_status,
                "status": "failed",
                "finished_at": finished_at,
                "updated_at": finished_at,
                "failure_reason": failure_reason,
                "rosbag_exit_code": rosbag_exit_code,
            },
        )
        append_jsonl(
            manifest_path,
            {
                "event": "run_finished",
                "timestamp": finished_at,
                "run_id": run_id,
                "run_index": run_index,
                "attempt_index": attempt_index,
                "status": "failed",
                "attempt_dir": str(attempt_dir),
                "failure_reason": failure_reason,
                "rosbag_exit_code": rosbag_exit_code,
            },
        )
        return False, failure_reason
    except Exception as exc:
        failure_reason = str(exc)
        if rosbag_proc is not None:
            rosbag_exit_code = stop_process_group(rosbag_proc, timeout_sec=cfg.rosbag_shutdown_sec)
        finished_at = now_utc()
        write_json_atomic(
            status_path,
            {
                **running_status,
                "status": "failed",
                "finished_at": finished_at,
                "updated_at": finished_at,
                "failure_reason": failure_reason,
                "rosbag_exit_code": rosbag_exit_code,
            },
        )
        append_jsonl(
            manifest_path,
            {
                "event": "run_finished",
                "timestamp": finished_at,
                "run_id": run_id,
                "run_index": run_index,
                "attempt_index": attempt_index,
                "status": "failed",
                "attempt_dir": str(attempt_dir),
                "failure_reason": failure_reason,
                "rosbag_exit_code": rosbag_exit_code,
            },
        )
        return False, failure_reason


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    workspace_root = script_dir.parent

    parser = argparse.ArgumentParser(description="Batch experiment runner with rosbag + Gemini telemetry")
    parser.add_argument("--task", required=True, help="Task id (e.g., T1-1, T1-2, T2, T3-1, T3-2)")
    parser.add_argument("--condition", required=True, help="Condition id (e.g., C2, P2, S1)")
    parser.add_argument("--env", required=True, choices=("sim", "real"), help="Execution environment")
    parser.add_argument("--repeats", required=True, type=int, help="Total run count")
    parser.add_argument("--resume", action="store_true", help="Skip completed runs and continue")
    parser.add_argument("--from-run", type=int, default=1, help="Start index (1-based)")
    parser.add_argument(
        "--profiles",
        default=str(script_dir / "experiment_profiles.json"),
        help="Path to experiment profile JSON",
    )
    parser.add_argument(
        "--output-root",
        default=str(workspace_root / "experiments"),
        help="Root directory for experiment artifacts",
    )
    parser.add_argument("--rosbag-warmup-sec", type=float, default=2.0, help="rosbag startup wait time")
    parser.add_argument(
        "--rosbag-shutdown-sec",
        type=float,
        default=20.0,
        help="Grace period for rosbag shutdown",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Continue remaining runs even if one run fails",
    )
    parser.add_argument(
        "--gemini-args",
        default="--yolo",
        help=(
            "Extra args forwarded to run_gemini_with_timing.sh (default: '--yolo'). "
            "Example: \"--yolo --model gemini-2.5-pro\""
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats <= 0:
        raise RuntimeError("--repeats must be > 0")
    if args.from_run < 1:
        raise RuntimeError("--from-run must be >= 1")
    if args.from_run > args.repeats:
        raise RuntimeError("--from-run cannot exceed --repeats")

    script_dir = Path(__file__).resolve().parent
    workspace_root = script_dir.parent
    output_root = Path(args.output_root).resolve()
    profiles_path = Path(args.profiles).resolve()

    ensure_command_exists("ros2")
    ensure_command_exists("python3")
    gemini_bin = os.environ.get("GEMINI_BIN", "gemini")
    ensure_command_exists(gemini_bin)

    wrapper_script = workspace_root / "scripts" / "run_gemini_with_timing.sh"
    if not wrapper_script.exists():
        raise RuntimeError(f"Gemini wrapper script not found: {wrapper_script}")

    profiles = load_profiles(profiles_path)
    task_cfg, condition_cfg = resolve_task_config(
        profiles,
        task=args.task,
        condition=args.condition,
        env=args.env,
    )

    cfg = RunnerConfig(
        workspace_root=workspace_root,
        output_root=output_root,
        profiles_path=profiles_path,
        task=args.task,
        condition=args.condition,
        env=args.env,
        repeats=args.repeats,
        start_run=args.from_run,
        resume=bool(args.resume),
        rosbag_warmup_sec=float(args.rosbag_warmup_sec),
        rosbag_shutdown_sec=float(args.rosbag_shutdown_sec),
        continue_on_failure=bool(args.continue_on_failure),
        gemini_args=shlex.split(str(args.gemini_args)),
    )

    manifest_path = output_root / args.task / args.condition / args.env / "manifest.jsonl"
    print(f"[batch] task={args.task} condition={args.condition} env={args.env} repeats={args.repeats}")
    print(f"[batch] output_root={output_root}")
    print(f"[batch] profile={profiles_path}")
    print(f"[batch] gemini_args={cfg.gemini_args}")

    completed = 0
    failed = 0

    for run_index in range(cfg.start_run, cfg.repeats + 1):
        run_id = make_run_id(cfg.task, cfg.condition, cfg.env, run_index)
        run_dir = cfg.output_root / cfg.task / cfg.condition / cfg.env / run_id

        if cfg.resume and status_is_completed_and_valid(run_dir):
            print(f"[batch] skip completed run: {run_id}")
            completed += 1
            continue

        if (not cfg.resume) and status_is_completed_and_valid(run_dir):
            raise RuntimeError(
                f"Run already completed: {run_id}. Use --resume or increase --from-run to avoid overwrite."
            )

        ok, reason = run_one(
            cfg,
            run_index=run_index,
            task_cfg=task_cfg,
            condition_cfg=condition_cfg,
            manifest_path=manifest_path,
        )
        if ok:
            completed += 1
            print(f"[batch] completed: {run_id}")
            continue

        failed += 1
        print(f"[batch] failed: {run_id} ({reason})")
        if not cfg.continue_on_failure:
            print("[batch] stop on failure. Re-run with --resume to continue from failed run.")
            break

    print(f"[batch] done: completed={completed}, failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[batch] interrupted by user")
        raise SystemExit(130)
    except Exception as exc:
        print(f"[batch] error: {exc}", file=sys.stderr)
        raise SystemExit(1)
