"""IMECE batch and episode runner."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .analysis import analyze_batch, audit_batch, classify_episode_report
from .config import (
    EDUCATIONAL_PROMPT_TASKS,
    PROMPT_LEVELS,
    PROMPT_VARIANTS,
    build_episode_prompt,
    load_c2_freeze,
    resolve_prompt_profile,
    resolve_t4_interrupt,
    resolve_task_spec,
)
from .constants import (
    ARMING_SERVICE,
    ARMING_SERVICE_TYPE,
    DEFAULT_C2_FREEZE_PATH,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_POLICY_PATH,
    LAND_MODE,
    OFFBOARD_MODE,
    REPO_ROOT,
    ROSBAG_TOPICS,
    ROSBRIDGE_DEFAULT_IP,
    ROSBRIDGE_DEFAULT_PORT,
    SET_MODE_SERVICE,
    SET_MODE_SERVICE_TYPE,
)
from .gemini import GeminiRunner
from .monitor import FlightMonitor
from .rosbridge import RosbridgeRequester, RosbridgeSubscriber
from .scoring import task_success

INFRA_RESULT_STATUSES = {"process_error", "no_output"}
QUOTA_ERROR_SNIPPETS = (
    "exhausted your capacity",
    "quota",
    "rate limit",
    "resource exhausted",
    "too many requests",
    "429",
)


@dataclass(frozen=True)
class EpisodeMatrixEntry:
    condition: str
    task_id: str
    episode_index: int
    prompt_level: str | None = None
    prompt_variant: str | None = None

    @property
    def key(self) -> str:
        if self.prompt_level and self.prompt_variant:
            return (
                f"{self.condition}:{self.task_id}:{self.prompt_level}:"
                f"{self.prompt_variant}:{self.episode_index:02d}"
            )
        return f"{self.condition}:{self.task_id}:{self.episode_index:02d}"


@dataclass(frozen=True)
class StudyPhaseSpec:
    name: str
    conditions: tuple[str, ...]
    tasks: tuple[str, ...]
    repetitions: int
    automated: bool
    note: str


STUDY_PHASES = {
    "discovery": StudyPhaseSpec(
        name="discovery",
        conditions=("C0", "C1"),
        tasks=("T1", "T2", "T3", "T4"),
        repetitions=5,
        automated=True,
        note="Prompt-only discovery pilot used to justify whether C2 is necessary.",
    ),
    "c2_freeze": StudyPhaseSpec(
        name="c2_freeze",
        conditions=("C2",),
        tasks=("T1", "T2", "T3", "T4"),
        repetitions=5,
        automated=True,
        note="One complete pilot batch after helper changes; add 20 episodes for each extra freeze-validation batch.",
    ),
    "official_sim": StudyPhaseSpec(
        name="official_sim",
        conditions=("C0", "C1", "C2"),
        tasks=("T1", "T2", "T3", "T4"),
        repetitions=10,
        automated=True,
        note="Official simulation evaluation with fresh Gemini sessions per episode.",
    ),
    "official_real": StudyPhaseSpec(
        name="official_real",
        conditions=("C2",),
        tasks=("T1", "T2", "T3", "T4"),
        repetitions=5,
        automated=False,
        note="Manual real-flight evaluation count. The current plan carries forward C2 only across T1-T4.",
    ),
}


def _now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _merge_env_file(env: dict[str, str], env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return env
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in env:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    return env


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _capture_command(args: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output or None


def _git_commit(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    output = _capture_command(["git", "-C", str(path), "rev-parse", "HEAD"])
    if not output:
        return None
    return output.splitlines()[0].strip()


def _gemini_version(binary: str) -> str | None:
    output = _capture_command([binary, "--version"])
    if not output:
        return None
    return output.splitlines()[0].strip()


def _gazebo_version() -> str | None:
    output = _capture_command(["gz", "sim", "--versions"])
    if output:
        return output.splitlines()[0].strip()
    output = _capture_command(["gz", "--versions"])
    if output:
        return output.splitlines()[0].strip()
    return None


def _mavros_version() -> str | None:
    shell_command = "source /opt/ros/jazzy/setup.bash && ros2 pkg xml mavros"
    try:
        result = subprocess.run(
            ["bash", "-lc", shell_command],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    output = (result.stdout or "").strip()
    if not output:
        return None
    try:
        root = ET.fromstring(output)
    except ET.ParseError:
        return None
    version = root.findtext("version")
    return version.strip() if version else None


def _extract_routed_model(turns: list[dict[str, Any]]) -> str | None:
    for turn in turns:
        for event in turn.get("events", []):
            if event.get("type") == "init":
                model = event.get("model")
                if isinstance(model, str) and model:
                    return model
    return None


def _collect_runtime_metadata(
    *,
    cwd: Path,
    gemini_binary: str,
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    px4_dir = Path(os.environ.get("PX4_AUTOPILOT_DIR", "/home/husl-ai/workspace/PX4-Autopilot"))
    return {
        "repo_commit_sha": _git_commit(cwd),
        "ros_mcp_repo_commit_sha": _git_commit(cwd),
        "px4_commit_sha": _git_commit(px4_dir),
        "gemini_cli_version": _gemini_version(gemini_binary),
        "actual_routed_model": _extract_routed_model(turns),
        "mavros_version": _mavros_version(),
        "gazebo_version": _gazebo_version(),
        "ros_distro": "jazzy",
    }


def _prompt_profile_pairs(
    prompt_levels: list[str] | tuple[str, ...] | None,
    prompt_variants: list[str] | tuple[str, ...] | None,
) -> list[tuple[str | None, str | None]]:
    if not prompt_levels and not prompt_variants:
        return [(None, None)]
    if not prompt_levels or not prompt_variants:
        raise ValueError("prompt levels and prompt variants must be provided together")
    pairs: list[tuple[str | None, str | None]] = []
    for level in prompt_levels:
        for variant in prompt_variants:
            pairs.append(resolve_prompt_profile(level, variant))
    return pairs


def build_episode_matrix(
    conditions: list[str] | tuple[str, ...],
    tasks: list[str] | tuple[str, ...],
    repetitions: int,
    *,
    prompt_levels: list[str] | tuple[str, ...] | None = None,
    prompt_variants: list[str] | tuple[str, ...] | None = None,
) -> list[EpisodeMatrixEntry]:
    matrix: list[EpisodeMatrixEntry] = []
    prompt_profiles = _prompt_profile_pairs(prompt_levels, prompt_variants)
    if prompt_profiles != [(None, None)]:
        unsupported = [
            resolve_task_spec(task_id).task_id
            for task_id in tasks
            if resolve_task_spec(task_id).task_id not in EDUCATIONAL_PROMPT_TASKS
        ]
        if unsupported:
            supported = ", ".join(EDUCATIONAL_PROMPT_TASKS)
            raise ValueError(
                f"Educational prompt profiles are defined only for {supported}; got {', '.join(sorted(set(unsupported)))}"
            )
    for condition in conditions:
        for task_id in tasks:
            for prompt_level, prompt_variant in prompt_profiles:
                for episode_index in range(1, repetitions + 1):
                    matrix.append(
                        EpisodeMatrixEntry(
                            condition=condition,
                            task_id=task_id,
                            episode_index=episode_index,
                            prompt_level=prompt_level,
                            prompt_variant=prompt_variant,
                        )
                    )
    return matrix


def study_plan_summary() -> dict[str, Any]:
    phases: dict[str, Any] = {}
    for name, spec in STUDY_PHASES.items():
        count = len(spec.conditions) * len(spec.tasks) * spec.repetitions
        phases[name] = {
            "conditions": list(spec.conditions),
            "tasks": list(spec.tasks),
            "repetitions": spec.repetitions,
            "episode_count": count,
            "automated": spec.automated,
            "note": spec.note,
        }
    simulation_total_before_real = (
        phases["discovery"]["episode_count"]
        + phases["c2_freeze"]["episode_count"]
        + phases["official_sim"]["episode_count"]
    )
    return {
        "phases": phases,
        "simulation_total_before_real": simulation_total_before_real,
        "fixed_total_with_one_c2_freeze_batch": simulation_total_before_real
        + phases["official_real"]["episode_count"],
        "extra_c2_freeze_batch_cost": phases["c2_freeze"]["episode_count"],
        "notes": [
            "Discovery is 2 conditions x 4 tasks x 5 reps = 40 episodes.",
            "One C2 freeze-validation batch is 1 condition x 4 tasks x 5 reps = 20 episodes.",
            "Official simulation is 3 conditions x 4 tasks x 10 reps = 120 episodes.",
            "Official real-flight is 1 C2 condition x 4 tasks x 5 reps = 20 episodes.",
        ],
    }


def _batch_state_path(batch_root: Path) -> Path:
    return batch_root / "batch_state.json"


def _episode_dir_for(batch_root: Path, spec: EpisodeMatrixEntry) -> Path:
    base_dir = batch_root / spec.condition / spec.task_id
    if spec.prompt_level and spec.prompt_variant:
        base_dir = base_dir / spec.prompt_level / spec.prompt_variant
    return base_dir / f"episode-{spec.episode_index:02d}"


def _episode_record(spec: EpisodeMatrixEntry) -> dict[str, Any]:
    return {
        "condition": spec.condition,
        "task_id": spec.task_id,
        "episode_index": spec.episode_index,
        "prompt_level": spec.prompt_level,
        "prompt_variant": spec.prompt_variant,
        "attempts": 0,
        "status": "pending",
        "last_error": None,
        "last_episode_dir": None,
        "infra_error": False,
        "task_success": None,
        "failure_codes": [],
    }


def _stderr_quota_warning(episode_dir: Path) -> str | None:
    stderr_path = episode_dir / "gemini.stderr.log"
    if not stderr_path.exists():
        return None
    for line in stderr_path.read_text(encoding="utf-8", errors="replace").splitlines():
        lowered = line.lower()
        if any(snippet in lowered for snippet in QUOTA_ERROR_SNIPPETS):
            return line.strip()
    return None


def _new_batch_state(
    *,
    batch_id: str,
    phase: str | None,
    matrix: list[EpisodeMatrixEntry],
    max_attempts: int,
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "phase": phase,
        "max_attempts": max_attempts,
        "created_at": _now_stamp(),
        "updated_at": _now_stamp(),
        "planned_episode_keys": [spec.key for spec in matrix],
        "episodes": {spec.key: _episode_record(spec) for spec in matrix},
        "summary": {},
    }


def _refresh_batch_summary(state: dict[str, Any]) -> None:
    counts = {"pending": 0, "running": 0, "completed": 0, "infra_error": 0, "exhausted": 0}
    for record in state["episodes"].values():
        status = record["status"]
        counts[status] = counts.get(status, 0) + 1
    state["summary"] = counts
    state["updated_at"] = _now_stamp()


def _load_or_init_batch_state(
    *,
    batch_root: Path,
    batch_id: str,
    phase: str | None,
    matrix: list[EpisodeMatrixEntry],
    max_attempts: int,
    resume: bool,
) -> dict[str, Any]:
    state_path = _batch_state_path(batch_root)
    planned_keys = [spec.key for spec in matrix]
    if state_path.exists():
        if not resume:
            raise ValueError(
                f"Batch root {batch_root} already exists. Re-run with --resume or choose a new --batch-id."
            )
        state = _read_json(state_path)
        if state.get("planned_episode_keys") != planned_keys:
            raise ValueError("Existing batch state does not match the requested episode matrix")
        state["max_attempts"] = max_attempts
        _refresh_batch_summary(state)
        return state
    state = _new_batch_state(batch_id=batch_id, phase=phase, matrix=matrix, max_attempts=max_attempts)
    _refresh_batch_summary(state)
    return state


def _save_batch_state(batch_root: Path, state: dict[str, Any]) -> None:
    _refresh_batch_summary(state)
    _write_json(_batch_state_path(batch_root), state)


def _retryable_specs(
    state: dict[str, Any],
    matrix: list[EpisodeMatrixEntry],
    max_attempts: int,
) -> list[EpisodeMatrixEntry]:
    retryable: list[EpisodeMatrixEntry] = []
    for spec in matrix:
        record = state["episodes"][spec.key]
        if record["status"] == "completed":
            continue
        if int(record["attempts"]) >= max_attempts:
            continue
        retryable.append(spec)
    return retryable


def _start_rosbag(output_dir: Path) -> subprocess.Popen[str] | None:
    if shutil.which("ros2") is None:
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        ["ros2", "bag", "record", "-o", str(output_dir / "bag"), *ROSBAG_TOPICS],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _touch_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("alive", encoding="utf-8")


def _mark_abort(path: Path) -> None:
    path.write_text("abort", encoding="utf-8")


def _cleanup_episode_artifacts(episode_dir: Path) -> None:
    transient_paths = (
        episode_dir / "watchdog.heartbeat",
        episode_dir / "rosbag" / "rosbag.stdout.log",
        episode_dir / "rosbag" / "rosbag.stderr.log",
    )
    for path in transient_paths:
        path.unlink(missing_ok=True)


def _estimate_offboard_rejections(
    events: list[dict[str, Any]],
    latest_mode: str | None,
) -> int:
    requested = 0
    for event in events:
        if event.get("type") != "tool_use":
            continue
        parameters = event.get("parameters", {})
        if not isinstance(parameters, dict):
            continue
        if parameters.get("service_name") != SET_MODE_SERVICE:
            continue
        request = parameters.get("request", {})
        if isinstance(request, dict) and request.get("custom_mode") == OFFBOARD_MODE:
            requested += 1
    if requested == 0:
        return 0
    if latest_mode == OFFBOARD_MODE:
        return max(0, requested - 1)
    return requested


def _scripts_dir() -> Path:
    return REPO_ROOT / "scripts" / "imece"


def _runtime_dir() -> Path:
    return DEFAULT_OUTPUT_ROOT / "runtime"


def _run_script(script_name: str, *, cwd: Path) -> None:
    subprocess.run(["bash", str(_scripts_dir() / script_name)], cwd=str(cwd), check=True)


def _sample_vehicle_state(
    *,
    host: str,
    port: int,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "connected": None,
        "armed": None,
        "mode": None,
        "system_status": None,
        "z": None,
        "orientation_x": None,
        "orientation_y": None,
    }
    last_snapshot = dict(state)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        subscriber = None
        try:
            subscriber = RosbridgeSubscriber(host, port, timeout=1.0)

            def on_state(message: dict[str, Any]) -> None:
                state["connected"] = message.get("connected")
                state["armed"] = message.get("armed")
                state["mode"] = message.get("mode")
                state["system_status"] = message.get("system_status")

            def on_pose(message: dict[str, Any]) -> None:
                pose = message.get("pose", {})
                position = pose.get("position", {}) if isinstance(pose, dict) else {}
                orientation = pose.get("orientation", {}) if isinstance(pose, dict) else {}
                try:
                    state["z"] = float(position.get("z"))
                except (TypeError, ValueError):
                    pass
                try:
                    state["orientation_x"] = float(orientation.get("x"))
                    state["orientation_y"] = float(orientation.get("y"))
                except (TypeError, ValueError):
                    pass

            subscriber.subscribe("/mavros/state", "mavros_msgs/msg/State", on_state)
            subscriber.subscribe("/mavros/local_position/pose", "geometry_msgs/msg/PoseStamped", on_pose)
            inner_deadline = min(deadline, time.monotonic() + 2.0)
            while time.monotonic() < inner_deadline:
                last_snapshot = dict(state)
                if _vehicle_ready(state):
                    return dict(state)
                time.sleep(0.1)
        except Exception:
            time.sleep(1.0)
        finally:
            if subscriber is not None:
                subscriber.stop()
    return last_snapshot


def _vehicle_upright(snapshot: dict[str, Any]) -> bool:
    try:
        orientation_x = float(snapshot.get("orientation_x"))
        orientation_y = float(snapshot.get("orientation_y"))
    except (TypeError, ValueError):
        return False
    return abs(orientation_x) <= 0.2 and abs(orientation_y) <= 0.2


def _vehicle_ready(snapshot: dict[str, Any]) -> bool:
    try:
        system_status = int(snapshot.get("system_status"))
    except (TypeError, ValueError):
        system_status = 0
    try:
        z = float(snapshot.get("z"))
    except (TypeError, ValueError):
        return False
    return (
        bool(snapshot.get("connected"))
        and snapshot.get("armed") is False
        and snapshot.get("mode") != OFFBOARD_MODE
        and z <= 0.2
        and system_status >= 3
        and _vehicle_upright(snapshot)
    )


def _restart_sim_stack(*, cwd: Path, progress_enabled: bool) -> None:
    _log(progress_enabled, "[episode] restart sim stack")
    stop_script = _scripts_dir() / "stop_sim_stack.sh"
    if stop_script.exists():
        subprocess.run(["bash", str(stop_script)], cwd=str(cwd), check=False)
    time.sleep(2.0)
    _runtime_dir().mkdir(parents=True, exist_ok=True)
    _run_script("start_sim_stack.sh", cwd=cwd)


def _ensure_episode_stack_ready(
    *,
    cwd: Path,
    host: str,
    port: int,
    progress_enabled: bool,
) -> None:
    snapshot = _sample_vehicle_state(host=host, port=port, timeout_s=15.0)
    if _vehicle_ready(snapshot):
        return
    _log(progress_enabled, f"[episode] unhealthy baseline detected state={snapshot}")
    requester = RosbridgeRequester(host, port, timeout=5.0)
    try:
        _normalize_episode_start_state(requester, host=host, port=port, timeout_s=8.0)
    except Exception:
        pass
    finally:
        requester.close()
    recovered_snapshot = _sample_vehicle_state(host=host, port=port, timeout_s=10.0)
    if _vehicle_ready(recovered_snapshot):
        _log(progress_enabled, f"[episode] recovered baseline locally state={recovered_snapshot}")
        return
    _restart_sim_stack(cwd=cwd, progress_enabled=progress_enabled)
    ready_snapshot = _sample_vehicle_state(host=host, port=port, timeout_s=90.0)
    if not _vehicle_ready(ready_snapshot):
        raise RuntimeError(f"sim stack did not reach a ready state: {ready_snapshot}")


def _ensure_real_episode_ready(
    *,
    host: str,
    port: int,
    progress_enabled: bool,
) -> None:
    snapshot = _sample_vehicle_state(host=host, port=port, timeout_s=15.0)
    if not _vehicle_ready(snapshot):
        raise RuntimeError(
            "real-flight preflight check failed; expected connected, landed, disarmed, "
            f"upright baseline but saw {snapshot}"
        )
    _log(progress_enabled, f"[episode] real preflight ready state={snapshot}")


def _normalize_episode_start_state(
    requester: RosbridgeRequester,
    *,
    host: str,
    port: int,
    timeout_s: float = 8.0,
) -> None:
    try:
        requester.call_service(
            SET_MODE_SERVICE,
            SET_MODE_SERVICE_TYPE,
            {"base_mode": 0, "custom_mode": LAND_MODE},
            timeout=5.0,
        )
    except Exception:
        pass

    try:
        requester.call_service(ARMING_SERVICE, ARMING_SERVICE_TYPE, {"value": False}, timeout=5.0)
    except Exception:
        pass

    try:
        requester.call_service(
            SET_MODE_SERVICE,
            SET_MODE_SERVICE_TYPE,
            {"base_mode": 0, "custom_mode": "AUTO.LOITER"},
            timeout=5.0,
        )
    except Exception:
        pass

    state: dict[str, Any] = {
        "armed": None,
        "z": None,
        "mode": None,
        "system_status": None,
        "orientation_x": None,
        "orientation_y": None,
    }
    subscriber = RosbridgeSubscriber(host, port, timeout=1.0)

    def on_state(message: dict[str, Any]) -> None:
        state["armed"] = message.get("armed")
        state["mode"] = message.get("mode")
        state["system_status"] = message.get("system_status")

    def on_pose(message: dict[str, Any]) -> None:
        pose = message.get("pose", {})
        position = pose.get("position", {}) if isinstance(pose, dict) else {}
        orientation = pose.get("orientation", {}) if isinstance(pose, dict) else {}
        try:
            state["z"] = float(position.get("z"))
        except (TypeError, ValueError):
            pass
        try:
            state["orientation_x"] = float(orientation.get("x"))
            state["orientation_y"] = float(orientation.get("y"))
        except (TypeError, ValueError):
            pass

    try:
        subscriber.subscribe("/mavros/state", "mavros_msgs/msg/State", on_state)
        subscriber.subscribe("/mavros/local_position/pose", "geometry_msgs/msg/PoseStamped", on_pose)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                system_status = int(state.get("system_status"))
            except (TypeError, ValueError):
                system_status = 0
            if (
                state.get("armed") is False
                and state.get("z") is not None
                and float(state["z"]) <= 0.2
                and state.get("mode") != OFFBOARD_MODE
                and system_status >= 3
                and _vehicle_upright(state)
            ):
                return
            time.sleep(0.1)
    finally:
        subscriber.stop()


def _load_pose_samples(log_path: Path) -> list[dict[str, float]]:
    samples: list[dict[str, float]] = []
    if not log_path.exists():
        return samples
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("kind") != "pose":
                continue
            payload = record.get("payload") or {}
            pose = payload.get("pose") if isinstance(payload, dict) else None
            position = pose.get("position") if isinstance(pose, dict) else None
            if not isinstance(position, dict):
                continue
            try:
                samples.append(
                    {
                        "x": float(position["x"]),
                        "y": float(position["y"]),
                        "z": float(position["z"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
    return samples


def _square_pattern_metrics(log_path: Path) -> dict[str, Any]:
    samples = _load_pose_samples(log_path)
    if not samples:
        return {"square_waypoints_reached": 0, "square_pattern_complete": False}

    start = samples[0]
    targets = (
        {"x": start["x"], "y": start["y"], "z": 1.0},
        {"x": start["x"] + 1.0, "y": start["y"], "z": 1.0},
        {"x": start["x"] + 1.0, "y": start["y"] + 1.0, "z": 1.0},
        {"x": start["x"], "y": start["y"] + 1.0, "z": 1.0},
        {"x": start["x"], "y": start["y"], "z": 1.0},
    )

    reached = 0
    for sample in samples:
        target = targets[reached]
        if (
            abs(sample["x"] - target["x"]) <= 0.25
            and abs(sample["y"] - target["y"]) <= 0.25
            and abs(sample["z"] - target["z"]) <= 0.25
        ):
            reached += 1
            if reached == len(targets):
                break

    return {
        "square_waypoints_reached": reached,
        "square_pattern_complete": reached == len(targets),
    }


def _task_success(task_id: str, report: dict[str, Any]) -> bool:
    return task_success(task_id, report)


def _run_configured_episode(args: argparse.Namespace, *, execution_mode: str) -> Path:
    task_spec = resolve_task_spec(args.task)
    output_root = Path(args.output_root)
    batch_id = args.batch_id or _now_stamp()
    condition_label = args.condition.upper()
    prompt_level, prompt_variant = resolve_prompt_profile(
        getattr(args, "prompt_level", None),
        getattr(args, "prompt_variant", None),
    )
    episode_spec = EpisodeMatrixEntry(
        condition=condition_label,
        task_id=task_spec.task_id,
        episode_index=args.episode_index,
        prompt_level=prompt_level,
        prompt_variant=prompt_variant,
    )
    batch_root = output_root / batch_id
    episode_dir = _episode_dir_for(batch_root, episode_spec)
    if getattr(args, "clean_existing", False) and episode_dir.exists():
        shutil.rmtree(episode_dir)
    episode_dir.mkdir(parents=True, exist_ok=True)
    progress_enabled = bool(getattr(args, "progress", True))
    from_batch = bool(getattr(args, "_from_batch", False))
    if progress_enabled and not from_batch:
        _log(
            True,
            f"[episode] start {condition_label}:{task_spec.task_id}:{args.episode_index:02d} batch_id={batch_id}",
        )

    rosbridge_ip = args.rosbridge_ip
    rosbridge_port = args.rosbridge_port
    freeze = load_c2_freeze(Path(args.freeze_path))
    selected_helpers = freeze.get("selected_helpers", []) if condition_label == "C2" else []
    helper_env_value = ",".join(selected_helpers)

    heartbeat_path = episode_dir / "watchdog.heartbeat"
    _touch_heartbeat(heartbeat_path)

    env = _merge_env_file(dict(os.environ), Path(args.cwd) / ".env")
    env["ROSBRIDGE_IP"] = rosbridge_ip
    env["ROSBRIDGE_PORT"] = str(rosbridge_port)
    env["IMECE_SELECTED_HELPERS"] = helper_env_value
    env["IMECE_WATCHDOG_HEARTBEAT_FILE"] = str(heartbeat_path)
    env["IMECE_WATCHDOG_TIMEOUT_S"] = str(args.watchdog_timeout)

    policy_path = Path(args.policy_path)
    prompt = build_episode_prompt(
        condition_label,
        task_spec.task_id,
        args.episode_index,
        rosbridge_ip,
        rosbridge_port,
        selected_helpers=selected_helpers,
        prompt_level=prompt_level,
        prompt_variant=prompt_variant,
    )
    (episode_dir / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    ros_requester = RosbridgeRequester(rosbridge_ip, rosbridge_port, timeout=5.0)
    if execution_mode == "sim":
        _ensure_episode_stack_ready(
            cwd=Path(args.cwd),
            host=rosbridge_ip,
            port=rosbridge_port,
            progress_enabled=progress_enabled,
        )
        _normalize_episode_start_state(ros_requester, host=rosbridge_ip, port=rosbridge_port)
    elif execution_mode == "real":
        _ensure_real_episode_ready(
            host=rosbridge_ip,
            port=rosbridge_port,
            progress_enabled=progress_enabled,
        )
    else:
        raise ValueError(f"Unsupported execution mode: {execution_mode}")
    monitor = FlightMonitor(rosbridge_ip, rosbridge_port, episode_dir / "monitor.jsonl")
    monitor.start()
    rosbag_process = _start_rosbag(episode_dir / "rosbag")
    gemini = GeminiRunner(binary=args.gemini_binary, cwd=Path(args.cwd), base_env=env)
    deadline_monotonic = time.monotonic() + args.timeout
    current_prompt = prompt
    resume_session_id = None
    turns: list[dict[str, Any]] = []
    interrupt_prompt = resolve_t4_interrupt(args.episode_index) if task_spec.task_id == "T4" else None
    interrupt_sent = False
    timed_out = False
    terminal_label = None
    terminal_payload = None

    def tick(_: float) -> None:
        _touch_heartbeat(heartbeat_path)

    try:
        while time.monotonic() < deadline_monotonic:
            turn_index = len(turns) + 1
            result = gemini.run_turn(
                prompt=current_prompt,
                trace_path=episode_dir / "gemini.jsonl",
                stderr_path=episode_dir / "gemini.stderr.log",
                policy_path=policy_path,
                turn_index=turn_index,
                timeout_s=max(5.0, deadline_monotonic - time.monotonic()),
                resume_session_id=resume_session_id,
                tick=tick,
            )
            resume_session_id = result.session_id or resume_session_id
            turns.append(
                {
                    "turn_index": turn_index,
                    "prompt": current_prompt,
                    "session_id": result.session_id,
                    "assistant_text": result.assistant_text,
                    "terminal_label": result.terminal_label,
                    "terminal_payload": result.terminal_payload,
                    "result_status": result.result_status,
                    "return_code": result.return_code,
                    "tool_call_count": result.tool_call_count,
                    "invalid_tool_call_count": result.invalid_tool_call_count,
                    "tool_error_messages": result.tool_error_messages,
                    "events": result.events,
                }
            )
            terminal_label = result.terminal_label
            terminal_payload = result.terminal_payload

            if task_spec.task_id == "T4" and interrupt_prompt and not interrupt_sent and terminal_label == "CLARIFY":
                _normalize_episode_start_state(
                    ros_requester,
                    host=rosbridge_ip,
                    port=rosbridge_port,
                    timeout_s=20.0,
                )
                current_prompt = interrupt_prompt
                interrupt_sent = True
                continue

            if terminal_label == "CLARIFY" and task_spec.clarification_reply:
                current_prompt = task_spec.clarification_reply
                continue

            if terminal_label in {"DONE", "REFUSE"}:
                break

            if result.result_status == "timeout":
                timed_out = True
                break

            break

        if time.monotonic() >= deadline_monotonic:
            timed_out = True

        if timed_out:
            _mark_abort(heartbeat_path)
            try:
                ros_requester.call_service(
                    SET_MODE_SERVICE,
                    SET_MODE_SERVICE_TYPE,
                    {"base_mode": 0, "custom_mode": LAND_MODE},
                    timeout=5.0,
                )
            except Exception:
                pass

        time.sleep(1.0)
        snapshot = monitor.snapshot()
        square_metrics = (
            _square_pattern_metrics(episode_dir / "monitor.jsonl")
            if task_spec.task_id == "T3"
            else {}
        )
        all_events = [event for turn in turns for event in turn["events"]]
        infra_error_reasons: list[str] = []
        for turn in turns:
            if turn["result_status"] in INFRA_RESULT_STATUSES:
                infra_error_reasons.append(
                    f"turn {turn['turn_index']} returned {turn['result_status']}"
                )
            elif turn["return_code"] != 0 and turn["result_status"] != "timeout":
                infra_error_reasons.append(
                    f"turn {turn['turn_index']} exited with return code {turn['return_code']}"
                )
        metrics = {
            "batch_id": batch_id,
            "condition": condition_label,
            "task_id": task_spec.task_id,
            "task_name": task_spec.title,
            "execution_mode": execution_mode,
            "episode_index": args.episode_index,
            "prompt_level": prompt_level,
            "prompt_variant": prompt_variant,
            "session_id": resume_session_id,
            "terminal_label": terminal_label,
            "terminal_payload": terminal_payload,
            "interrupt_prompt": interrupt_prompt,
            "interrupt_sent": interrupt_sent,
            "timed_out": timed_out,
            "tool_call_count": sum(turn["tool_call_count"] for turn in turns),
            "invalid_tool_call_count": sum(turn["invalid_tool_call_count"] for turn in turns),
            "tool_error_messages": [msg for turn in turns for msg in turn["tool_error_messages"]],
            "turn_result_statuses": [turn["result_status"] for turn in turns],
            "turn_return_codes": [turn["return_code"] for turn in turns],
            "first_setpoint_latency_s": snapshot.first_setpoint_latency_s,
            "max_setpoint_gap_s": snapshot.max_setpoint_gap_s,
            "setpoint_count": snapshot.setpoint_count,
            "max_altitude_m": snapshot.max_altitude_m,
            "final_position": snapshot.final_position,
            "horizontal_displacement_m": snapshot.horizontal_displacement_m,
            "x_span_m": snapshot.x_span_m,
            "y_span_m": snapshot.y_span_m,
            "offboard_drop_count": snapshot.offboard_drop_count,
            "offboard_rejection_count": _estimate_offboard_rejections(all_events, snapshot.latest_mode),
            "latest_mode": snapshot.latest_mode,
            "latest_armed": snapshot.latest_armed,
            "actuation_seen": snapshot.actuation_seen,
            "watchdog_triggered": Path(heartbeat_path).read_text(encoding="utf-8").strip() == "abort",
            "state_errors": snapshot.state_errors,
            "infra_error": bool(infra_error_reasons),
            "infra_error_reasons": infra_error_reasons,
            "task_success": False,
        }
        metrics.update(square_metrics)
        metrics["task_success"] = _task_success(task_spec.task_id, metrics)
        metrics["failure_codes"] = classify_episode_report(metrics)
        runtime_metadata = _collect_runtime_metadata(
            cwd=Path(args.cwd),
            gemini_binary=args.gemini_binary,
            turns=turns,
        )

        _write_json(
            episode_dir / "metadata.json",
            {
                "condition": condition_label,
                "task_id": task_spec.task_id,
                "task_name": task_spec.title,
                "execution_mode": execution_mode,
                "prompt_level": prompt_level,
                "prompt_variant": prompt_variant,
                "selected_helpers": selected_helpers,
                "runtime_metadata": runtime_metadata,
                "turns": turns,
            },
        )
        _write_json(episode_dir / "metrics.json", metrics)
        if progress_enabled and not from_batch:
            failure_codes = ",".join(metrics["failure_codes"]) if metrics["failure_codes"] else "-"
            _log(
                True,
                (
                    f"[episode] end {condition_label}:{task_spec.task_id}:{args.episode_index:02d} "
                    f"task_success={metrics['task_success']} infra_error={metrics['infra_error']} "
                    f"failures={failure_codes}"
                ),
            )
    finally:
        if execution_mode == "sim":
            try:
                _normalize_episode_start_state(
                    ros_requester,
                    host=rosbridge_ip,
                    port=rosbridge_port,
                    timeout_s=6.0,
                )
            except Exception:
                pass
        _stop_process(rosbag_process)
        monitor.stop()
        ros_requester.close()
        _cleanup_episode_artifacts(episode_dir)
    return episode_dir


def run_episode(args: argparse.Namespace) -> Path:
    return _run_configured_episode(args, execution_mode="sim")


def run_real_episode(args: argparse.Namespace) -> Path:
    return _run_configured_episode(args, execution_mode="real")


def _execute_batch_specs(
    *,
    args: argparse.Namespace,
    batch_root: Path,
    batch_id: str,
    state: dict[str, Any],
    specs: list[EpisodeMatrixEntry],
) -> None:
    total_planned = len(state["planned_episode_keys"])
    for spec in specs:
        record = state["episodes"][spec.key]
        attempt_index = int(record["attempts"]) + 1
        planned_index = state["planned_episode_keys"].index(spec.key) + 1
        record["attempts"] = attempt_index
        record["status"] = "running"
        record["last_error"] = None
        _save_batch_state(batch_root, state)
        _log(
            args.progress,
            f"[batch] start {planned_index}/{total_planned} {spec.key} attempt={attempt_index}",
        )

        episode_args = argparse.Namespace(**vars(args))
        episode_args.batch_id = batch_id
        episode_args.condition = spec.condition
        episode_args.task = spec.task_id
        episode_args.episode_index = spec.episode_index
        episode_args.clean_existing = True
        episode_args._from_batch = True
        episode_args.prompt_level = spec.prompt_level
        episode_args.prompt_variant = spec.prompt_variant

        episode_dir = _episode_dir_for(batch_root, spec)
        quota_warning = None
        try:
            run_episode(episode_args)
            metrics = _read_json(episode_dir / "metrics.json")
            quota_warning = _stderr_quota_warning(episode_dir)
            record["last_episode_dir"] = str(episode_dir)
            record["infra_error"] = bool(metrics.get("infra_error"))
            record["task_success"] = metrics.get("task_success")
            record["failure_codes"] = metrics.get("failure_codes", [])
            if metrics.get("infra_error"):
                record["status"] = (
                    "infra_error" if attempt_index < int(state["max_attempts"]) else "exhausted"
                )
                reasons = metrics.get("infra_error_reasons") or ["episode marked infra_error"]
                record["last_error"] = "; ".join(str(reason) for reason in reasons)
            else:
                record["status"] = "completed"
        except Exception as exc:
            record["last_episode_dir"] = str(episode_dir)
            record["infra_error"] = True
            record["task_success"] = None
            record["failure_codes"] = []
            record["last_error"] = str(exc)
            record["status"] = (
                "infra_error" if attempt_index < int(state["max_attempts"]) else "exhausted"
            )
        finally:
            _save_batch_state(batch_root, state)
        summary = state["summary"]
        failure_codes = ",".join(record["failure_codes"]) if record["failure_codes"] else "-"
        _log(
            args.progress,
            (
                f"[batch] end {planned_index}/{total_planned} {spec.key} "
                f"status={record['status']} task_success={record['task_success']} "
                f"infra_error={record['infra_error']} failures={failure_codes} "
                f"completed={summary.get('completed', 0)} "
                f"remaining={summary.get('pending', 0) + summary.get('running', 0) + summary.get('infra_error', 0)}"
            ),
        )
        if record["last_error"]:
            _log(args.progress, f"[batch] detail {spec.key} error={record['last_error']}")
        if quota_warning:
            _log(args.progress, f"[batch] quota-warning {spec.key} {quota_warning}")


def run_batch(args: argparse.Namespace) -> Path:
    batch_id = args.batch_id or _now_stamp()
    batch_root = Path(args.output_root) / batch_id
    matrix = build_episode_matrix(
        args.conditions,
        args.tasks,
        args.repetitions,
        prompt_levels=getattr(args, "prompt_levels", None),
        prompt_variants=getattr(args, "prompt_variants", None),
    )
    state = _load_or_init_batch_state(
        batch_root=batch_root,
        batch_id=batch_id,
        phase=getattr(args, "phase", None),
        matrix=matrix,
        max_attempts=args.max_attempts,
        resume=args.resume,
    )
    _log(
        args.progress,
        (
            f"[batch] ready batch_id={batch_id} phase={getattr(args, 'phase', None) or 'custom'} "
            f"total={len(matrix)} completed={state['summary'].get('completed', 0)} "
            f"pending={state['summary'].get('pending', 0)}"
        ),
    )

    initial_specs = _retryable_specs(state, matrix, args.max_attempts)
    _execute_batch_specs(args=args, batch_root=batch_root, batch_id=batch_id, state=state, specs=initial_specs)

    if args.retry_at_end:
        while True:
            retry_specs = _retryable_specs(state, matrix, args.max_attempts)
            if not retry_specs:
                break
            _log(
                args.progress,
                f"[batch] retry-pass count={len(retry_specs)} max_attempts={args.max_attempts}",
            )
            _execute_batch_specs(
                args=args,
                batch_root=batch_root,
                batch_id=batch_id,
                state=state,
                specs=retry_specs,
            )

    analysis = analyze_batch(batch_root)
    _write_json(batch_root / "analysis.json", analysis)
    if "audit" in analysis:
        _write_json(batch_root / "audit.json", analysis["audit"])
    _save_batch_state(batch_root, state)
    _log(
        args.progress,
        (
            f"[batch] analyzed batch_id={batch_id} completed={state['summary'].get('completed', 0)} "
            f"infra_error={state['summary'].get('infra_error', 0)} exhausted={state['summary'].get('exhausted', 0)}"
        ),
    )
    if args.freeze_c2 and all(
        record["status"] == "completed" for record in state["episodes"].values()
    ):
        _write_json(Path(args.freeze_path), analysis["selection"])
        _log(args.progress, f"[batch] wrote-freeze {args.freeze_path}")
    return batch_root


def run_phase(args: argparse.Namespace) -> Path:
    phase = STUDY_PHASES[args.phase]
    if not phase.automated:
        raise ValueError(f"Phase {args.phase} is plan-only and is not automated by the sim runner")
    batch_args = argparse.Namespace(**vars(args))
    batch_args.conditions = list(phase.conditions)
    batch_args.tasks = list(phase.tasks)
    batch_args.repetitions = phase.repetitions
    batch_args.phase = phase.name
    batch_args.prompt_levels = None
    batch_args.prompt_variants = None
    if args.phase == "discovery" and not args.freeze_c2:
        batch_args.freeze_c2 = True
    return run_batch(batch_args)


def run_educational_batch(args: argparse.Namespace) -> Path:
    batch_args = argparse.Namespace(**vars(args))
    batch_args.conditions = ["C2"]
    batch_args.tasks = list(args.tasks)
    batch_args.repetitions = 1
    batch_args.phase = "educational_sim"
    batch_args.freeze_c2 = False
    return run_batch(batch_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="IMECE experiment runner")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--cwd", default=str(Path(__file__).resolve().parents[2]))
        subparser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
        subparser.add_argument("--policy-path", default=str(DEFAULT_POLICY_PATH))
        subparser.add_argument("--freeze-path", default=str(DEFAULT_C2_FREEZE_PATH))
        subparser.add_argument("--gemini-binary", default="gemini")
        subparser.add_argument("--rosbridge-ip", default=ROSBRIDGE_DEFAULT_IP)
        subparser.add_argument("--rosbridge-port", type=int, default=ROSBRIDGE_DEFAULT_PORT)
        subparser.add_argument("--timeout", type=float, default=120.0)
        subparser.add_argument("--watchdog-timeout", type=float, default=5.0)
        subparser.add_argument("--batch-id")
        subparser.add_argument("--clean-existing", action="store_true")
        subparser.add_argument(
            "--progress",
            action=argparse.BooleanOptionalAction,
            default=True,
        )

    def add_prompt_profile(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--prompt-level", choices=list(PROMPT_LEVELS))
        subparser.add_argument("--prompt-variant", choices=list(PROMPT_VARIANTS))

    episode = subparsers.add_parser("run-episode")
    add_shared(episode)
    add_prompt_profile(episode)
    episode.add_argument("--condition", choices=["C0", "C1", "C2"], required=True)
    episode.add_argument("--task", choices=["T1", "T2", "T3", "T4"], required=True)
    episode.add_argument("--episode-index", type=int, required=True)

    real_episode = subparsers.add_parser("run-real-episode")
    add_shared(real_episode)
    add_prompt_profile(real_episode)
    real_episode.add_argument("--condition", choices=["C0", "C1", "C2"], required=True)
    real_episode.add_argument("--task", choices=["T1", "T2", "T3", "T4"], required=True)
    real_episode.add_argument("--episode-index", type=int, required=True)

    batch = subparsers.add_parser("run-batch")
    add_shared(batch)
    batch.add_argument("--conditions", nargs="+", default=["C0", "C1"])
    batch.add_argument("--tasks", nargs="+", default=["T1", "T2", "T3", "T4"])
    batch.add_argument("--repetitions", type=int, default=5)
    batch.add_argument("--prompt-levels", nargs="+", choices=list(PROMPT_LEVELS))
    batch.add_argument("--prompt-variants", nargs="+", choices=list(PROMPT_VARIANTS))
    batch.add_argument("--freeze-c2", action="store_true")
    batch.add_argument("--resume", action="store_true")
    batch.add_argument("--max-attempts", type=int, default=3)
    batch.add_argument(
        "--retry-at-end",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    phase = subparsers.add_parser("run-phase")
    add_shared(phase)
    phase.add_argument("phase", choices=[name for name, spec in STUDY_PHASES.items() if spec.automated])
    phase.add_argument("--freeze-c2", action="store_true")
    phase.add_argument("--resume", action="store_true")
    phase.add_argument("--max-attempts", type=int, default=3)
    phase.add_argument(
        "--retry-at-end",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    educational = subparsers.add_parser("run-educational-batch")
    add_shared(educational)
    educational.add_argument("--tasks", nargs="+", choices=list(EDUCATIONAL_PROMPT_TASKS), default=list(EDUCATIONAL_PROMPT_TASKS))
    educational.add_argument(
        "--prompt-levels",
        nargs="+",
        choices=list(PROMPT_LEVELS),
        default=list(PROMPT_LEVELS),
    )
    educational.add_argument(
        "--prompt-variants",
        nargs="+",
        choices=list(PROMPT_VARIANTS),
        default=list(PROMPT_VARIANTS),
    )
    educational.add_argument("--resume", action="store_true")
    educational.add_argument("--max-attempts", type=int, default=3)
    educational.add_argument(
        "--retry-at-end",
        action=argparse.BooleanOptionalAction,
        default=True,
    )

    analyze = subparsers.add_parser("analyze-batch")
    analyze.add_argument("--batch-dir", required=True)
    analyze.add_argument("--freeze-path", default=str(DEFAULT_C2_FREEZE_PATH))
    analyze.add_argument("--write-freeze", action="store_true")

    audit = subparsers.add_parser("audit-batch")
    audit.add_argument("--batch-dir", required=True)
    audit.add_argument("--write-path")

    plan = subparsers.add_parser("plan-study")
    plan.add_argument("--write-path")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "run-episode":
        run_episode(args)
    elif args.command == "run-real-episode":
        run_real_episode(args)
    elif args.command == "run-batch":
        run_batch(args)
    elif args.command == "run-phase":
        run_phase(args)
    elif args.command == "run-educational-batch":
        run_educational_batch(args)
    elif args.command == "analyze-batch":
        analysis = analyze_batch(Path(args.batch_dir))
        _write_json(Path(args.batch_dir) / "analysis.json", analysis)
        if args.write_freeze:
            _write_json(Path(args.freeze_path), analysis["selection"])
    elif args.command == "audit-batch":
        audit = audit_batch(Path(args.batch_dir))
        if args.write_path:
            _write_json(Path(args.write_path), audit)
        else:
            _write_json(Path(args.batch_dir) / "audit.json", audit)
    elif args.command == "plan-study":
        summary = study_plan_summary()
        if args.write_path:
            _write_json(Path(args.write_path), summary)
        else:
            print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
