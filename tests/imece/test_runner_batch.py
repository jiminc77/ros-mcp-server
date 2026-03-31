import json
import shutil
from argparse import Namespace
from pathlib import Path

from ros_mcp.imece import runner


def _shared_args(tmp_path: Path) -> Namespace:
    return Namespace(
        cwd=str(tmp_path),
        output_root=str(tmp_path),
        policy_path=str(tmp_path / "policy.toml"),
        freeze_path=str(tmp_path / "c2_freeze.json"),
        gemini_binary="gemini",
        rosbridge_ip="127.0.0.1",
        rosbridge_port=9090,
        timeout=120.0,
        watchdog_timeout=5.0,
        batch_id="batch-001",
        clean_existing=False,
        progress=True,
        conditions=["C0"],
        tasks=["T1"],
        repetitions=1,
        freeze_c2=False,
        resume=False,
        max_attempts=2,
        retry_at_end=True,
        phase=None,
    )


def test_study_plan_summary_matches_spec_counts():
    summary = runner.study_plan_summary()
    assert summary["phases"]["discovery"]["episode_count"] == 40
    assert summary["phases"]["c2_freeze"]["episode_count"] == 20
    assert summary["phases"]["official_sim"]["episode_count"] == 120
    assert summary["phases"]["official_real"]["episode_count"] == 10
    assert summary["simulation_total_before_real"] == 180
    assert summary["fixed_total_with_one_c2_freeze_batch"] == 190


def test_run_batch_retries_infra_errors_at_end(tmp_path, monkeypatch):
    attempts: dict[tuple[str, str, int], int] = {}

    def fake_run_episode(args: Namespace) -> Path:
        key = (args.condition, args.task, args.episode_index)
        attempts[key] = attempts.get(key, 0) + 1
        episode_dir = (
            Path(args.output_root)
            / args.batch_id
            / args.condition
            / args.task
            / f"episode-{args.episode_index:02d}"
        )
        if args.clean_existing and episode_dir.exists():
            shutil.rmtree(episode_dir)
        episode_dir.mkdir(parents=True, exist_ok=True)
        infra_error = attempts[key] == 1
        metrics = {
            "condition": args.condition,
            "task_id": args.task,
            "episode_index": args.episode_index,
            "infra_error": infra_error,
            "infra_error_reasons": ["gemini model error"] if infra_error else [],
            "task_success": not infra_error,
            "failure_codes": [],
        }
        (episode_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        (episode_dir / "metadata.json").write_text(
            json.dumps({"turns": [], "selected_helpers": []}),
            encoding="utf-8",
        )
        return episode_dir

    monkeypatch.setattr(runner, "run_episode", fake_run_episode)
    monkeypatch.setattr(
        runner,
        "analyze_batch",
        lambda batch_dir: {"reports": [], "selection": {"selected_helpers": [], "status": "pending"}},
    )

    args = _shared_args(tmp_path)
    runner.run_batch(args)

    state = json.loads((tmp_path / "batch-001" / "batch_state.json").read_text(encoding="utf-8"))
    record = state["episodes"]["C0:T1:01"]
    assert attempts[("C0", "T1", 1)] == 2
    assert record["status"] == "completed"
    assert record["attempts"] == 2


def test_run_batch_resume_continues_from_infra_error(tmp_path, monkeypatch):
    attempts: dict[tuple[str, str, int], int] = {}

    def fake_run_episode(args: Namespace) -> Path:
        key = (args.condition, args.task, args.episode_index)
        attempts[key] = attempts.get(key, 0) + 1
        episode_dir = (
            Path(args.output_root)
            / args.batch_id
            / args.condition
            / args.task
            / f"episode-{args.episode_index:02d}"
        )
        if args.clean_existing and episode_dir.exists():
            shutil.rmtree(episode_dir)
        episode_dir.mkdir(parents=True, exist_ok=True)
        infra_error = attempts[key] == 1
        metrics = {
            "condition": args.condition,
            "task_id": args.task,
            "episode_index": args.episode_index,
            "infra_error": infra_error,
            "infra_error_reasons": ["connector error"] if infra_error else [],
            "task_success": not infra_error,
            "failure_codes": [],
        }
        (episode_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        (episode_dir / "metadata.json").write_text(
            json.dumps({"turns": [], "selected_helpers": []}),
            encoding="utf-8",
        )
        return episode_dir

    monkeypatch.setattr(runner, "run_episode", fake_run_episode)
    monkeypatch.setattr(
        runner,
        "analyze_batch",
        lambda batch_dir: {"reports": [], "selection": {"selected_helpers": [], "status": "pending"}},
    )

    first_args = _shared_args(tmp_path)
    first_args.retry_at_end = False
    runner.run_batch(first_args)

    resumed_args = _shared_args(tmp_path)
    resumed_args.resume = True
    runner.run_batch(resumed_args)

    state = json.loads((tmp_path / "batch-001" / "batch_state.json").read_text(encoding="utf-8"))
    record = state["episodes"]["C0:T1:01"]
    assert attempts[("C0", "T1", 1)] == 2
    assert record["status"] == "completed"
    assert record["attempts"] == 2


def test_run_batch_prints_progress_and_quota_warning(tmp_path, monkeypatch, capsys):
    def fake_run_episode(args: Namespace) -> Path:
        episode_dir = (
            Path(args.output_root)
            / args.batch_id
            / args.condition
            / args.task
            / f"episode-{args.episode_index:02d}"
        )
        if args.clean_existing and episode_dir.exists():
            shutil.rmtree(episode_dir)
        episode_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
            "condition": args.condition,
            "task_id": args.task,
            "episode_index": args.episode_index,
            "infra_error": False,
            "infra_error_reasons": [],
            "task_success": False,
            "failure_codes": ["F4"],
        }
        (episode_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        (episode_dir / "metadata.json").write_text(
            json.dumps({"turns": [], "selected_helpers": []}),
            encoding="utf-8",
        )
        (episode_dir / "gemini.stderr.log").write_text(
            "Attempt 1 failed: You have exhausted your capacity on this model.\n",
            encoding="utf-8",
        )
        return episode_dir

    monkeypatch.setattr(runner, "run_episode", fake_run_episode)
    monkeypatch.setattr(
        runner,
        "analyze_batch",
        lambda batch_dir: {"reports": [], "selection": {"selected_helpers": [], "status": "pending"}},
    )

    args = _shared_args(tmp_path)
    runner.run_batch(args)

    stdout = capsys.readouterr().out
    assert "[batch] ready" in stdout
    assert "[batch] start 1/1 C0:T1:01 attempt=1" in stdout
    assert "[batch] end 1/1 C0:T1:01 status=completed" in stdout
    assert "[batch] quota-warning C0:T1:01" in stdout


def test_normalize_episode_start_state_forces_landed_disarmed_baseline(monkeypatch):
    class FakeRequester:
        def __init__(self) -> None:
            self.calls = []

        def call_service(self, service: str, service_type: str, args: dict, timeout: float = 5.0) -> dict:
            self.calls.append((service, service_type, args, timeout))
            if service.endswith("set_mode"):
                return {"values": {"mode_sent": True}}
            return {"values": {"success": True, "result": 0}}

    class FakeSubscriber:
        def __init__(self, host: str, port: int, timeout: float = 1.0) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def subscribe(self, topic: str, msg_type: str, callback, **_: object) -> None:
            if topic == "/mavros/state":
                callback({"armed": False, "mode": "AUTO.LOITER", "system_status": 3})
            elif topic == "/mavros/local_position/pose":
                callback({"pose": {"position": {"z": 0.0}}})

        def stop(self) -> None:
            return

    monkeypatch.setattr(runner, "RosbridgeSubscriber", FakeSubscriber)

    requester = FakeRequester()
    runner._normalize_episode_start_state(requester, host="127.0.0.1", port=9090, timeout_s=0.1)

    assert requester.calls[0][0] == runner.SET_MODE_SERVICE
    assert requester.calls[1][0] == runner.ARMING_SERVICE


def test_vehicle_ready_requires_connected_pose_and_system_status():
    assert runner._vehicle_ready({"connected": True, "z": 0.0, "system_status": 3}) is True
    assert runner._vehicle_ready({"connected": True, "z": 0.0, "system_status": 0}) is False
    assert runner._vehicle_ready({"connected": False, "z": 0.0, "system_status": 3}) is False

def test_ensure_episode_stack_ready_restarts_on_unhealthy_baseline(monkeypatch, tmp_path):
    snapshots = iter(
        [
            {"connected": True, "z": 0.0, "system_status": 0},
            {"connected": True, "z": 0.0, "system_status": 0},
            {"connected": True, "z": 0.0, "system_status": 3},
        ]
    )
    restarted = {"count": 0}

    monkeypatch.setattr(
        runner,
        "_sample_vehicle_state",
        lambda **_: next(snapshots),
    )
    monkeypatch.setattr(
        runner,
        "_restart_sim_stack",
        lambda **_: restarted.__setitem__("count", restarted["count"] + 1),
    )
    monkeypatch.setattr(runner, "_normalize_episode_start_state", lambda *_, **__: None)

    runner._ensure_episode_stack_ready(
        cwd=tmp_path,
        host="127.0.0.1",
        port=9090,
        progress_enabled=False,
    )

    assert restarted["count"] == 1


def test_ensure_episode_stack_ready_prefers_local_recovery(monkeypatch, tmp_path):
    snapshots = iter(
        [
            {"connected": True, "z": 0.0, "system_status": 0},
            {"connected": True, "z": 0.0, "system_status": 3},
        ]
    )
    restarted = {"count": 0}

    monkeypatch.setattr(
        runner,
        "_sample_vehicle_state",
        lambda **_: next(snapshots),
    )
    monkeypatch.setattr(runner, "_normalize_episode_start_state", lambda *_, **__: None)
    monkeypatch.setattr(
        runner,
        "_restart_sim_stack",
        lambda **_: restarted.__setitem__("count", restarted["count"] + 1),
    )

    runner._ensure_episode_stack_ready(
        cwd=tmp_path,
        host="127.0.0.1",
        port=9090,
        progress_enabled=False,
    )

    assert restarted["count"] == 0
