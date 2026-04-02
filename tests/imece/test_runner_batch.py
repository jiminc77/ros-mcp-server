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
        prompt_level=None,
        prompt_variant=None,
        prompt_levels=None,
        prompt_variants=None,
    )


def test_study_plan_summary_matches_spec_counts():
    summary = runner.study_plan_summary()
    assert summary["phases"]["discovery"]["episode_count"] == 40
    assert summary["phases"]["c2_freeze"]["episode_count"] == 20
    assert summary["phases"]["official_sim"]["episode_count"] == 120
    assert summary["phases"]["official_real"]["episode_count"] == 20
    assert summary["simulation_total_before_real"] == 180
    assert summary["fixed_total_with_one_c2_freeze_batch"] == 200


def test_build_episode_matrix_expands_prompt_profiles():
    matrix = runner.build_episode_matrix(
        ["C2"],
        ["T1", "T2"],
        1,
        prompt_levels=["elementary", "college"],
        prompt_variants=["a", "c"],
    )

    keys = [entry.key for entry in matrix]
    assert len(matrix) == 8
    assert "C2:T1:elementary:a:01" in keys
    assert "C2:T2:college:c:01" in keys


def test_build_episode_matrix_rejects_t4_prompt_profiles():
    try:
        runner.build_episode_matrix(
            ["C2"],
            ["T4"],
            1,
            prompt_levels=["elementary"],
            prompt_variants=["a"],
        )
    except ValueError as exc:
        assert "defined only for T1, T2, T3" in str(exc)
    else:
        raise AssertionError("expected unsupported educational task validation")


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
        lambda batch_dir: {
            "reports": [],
            "selection": {"selected_helpers": [], "status": "pending"},
            "audit": {"notes": []},
        },
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
        lambda batch_dir: {
            "reports": [],
            "selection": {"selected_helpers": [], "status": "pending"},
            "audit": {"notes": []},
        },
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
        lambda batch_dir: {
            "reports": [],
            "selection": {"selected_helpers": [], "status": "pending"},
            "audit": {"notes": []},
        },
    )

    args = _shared_args(tmp_path)
    runner.run_batch(args)

    stdout = capsys.readouterr().out
    assert "[batch] ready" in stdout
    assert "[batch] start 1/1 C0:T1:01 attempt=1" in stdout
    assert "[batch] end 1/1 C0:T1:01 status=completed" in stdout
    assert "[batch] quota-warning C0:T1:01" in stdout


def test_merge_env_file_loads_missing_keys_from_repo_env(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        'GEMINI_API_KEY="secret"\nEXISTING=from_file\n# comment\n',
        encoding="utf-8",
    )
    env = runner._merge_env_file({"EXISTING": "from_env"}, env_path)
    assert env["GEMINI_API_KEY"] == "secret"
    assert env["EXISTING"] == "from_env"


def test_start_rosbag_discards_shell_logs(tmp_path, monkeypatch):
    captured = {}

    class DummyProcess:
        def poll(self) -> int:
            return 0

    monkeypatch.setattr(runner.shutil, "which", lambda name: "/usr/bin/ros2")

    def fake_popen(args, stdout=None, stderr=None, text=None):
        captured["args"] = args
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["text"] = text
        return DummyProcess()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)

    process = runner._start_rosbag(tmp_path / "rosbag")

    assert process is not None
    assert captured["stdout"] == runner.subprocess.DEVNULL
    assert captured["stderr"] == runner.subprocess.DEVNULL
    assert captured["text"] is True


def test_cleanup_episode_artifacts_removes_transient_logs(tmp_path):
    episode_dir = tmp_path / "episode-01"
    rosbag_dir = episode_dir / "rosbag"
    rosbag_dir.mkdir(parents=True)
    (episode_dir / "watchdog.heartbeat").write_text("alive", encoding="utf-8")
    (rosbag_dir / "rosbag.stdout.log").write_text("stdout", encoding="utf-8")
    (rosbag_dir / "rosbag.stderr.log").write_text("stderr", encoding="utf-8")

    runner._cleanup_episode_artifacts(episode_dir)

    assert not (episode_dir / "watchdog.heartbeat").exists()
    assert not (rosbag_dir / "rosbag.stdout.log").exists()
    assert not (rosbag_dir / "rosbag.stderr.log").exists()


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
                callback({"pose": {"position": {"z": 0.0}, "orientation": {"x": 0.0, "y": 0.0}}})

        def stop(self) -> None:
            return

    monkeypatch.setattr(runner, "RosbridgeSubscriber", FakeSubscriber)

    requester = FakeRequester()
    runner._normalize_episode_start_state(requester, host="127.0.0.1", port=9090, timeout_s=0.1)

    assert requester.calls[0][0] == runner.SET_MODE_SERVICE
    assert requester.calls[1][0] == runner.ARMING_SERVICE


def test_vehicle_ready_requires_connected_pose_and_system_status():
    healthy = {
        "connected": True,
        "armed": False,
        "mode": "AUTO.LOITER",
        "z": 0.0,
        "system_status": 3,
        "orientation_x": 0.0,
        "orientation_y": 0.0,
    }
    assert runner._vehicle_ready(healthy) is True
    assert runner._vehicle_ready({**healthy, "system_status": 0}) is False
    assert runner._vehicle_ready({**healthy, "connected": False}) is False
    assert runner._vehicle_ready({**healthy, "armed": True}) is False
    assert runner._vehicle_ready({**healthy, "mode": runner.OFFBOARD_MODE}) is False
    assert runner._vehicle_ready({**healthy, "orientation_x": 0.7, "orientation_y": 0.0}) is False


def test_ensure_real_episode_ready_rejects_unhealthy_baseline(monkeypatch):
    monkeypatch.setattr(
        runner,
        "_sample_vehicle_state",
        lambda **_: {
            "connected": True,
            "armed": True,
            "mode": "OFFBOARD",
            "z": 1.0,
            "system_status": 4,
            "orientation_x": 0.0,
            "orientation_y": 0.0,
        },
    )

    try:
        runner._ensure_real_episode_ready(host="127.0.0.1", port=9090, progress_enabled=False)
    except RuntimeError as exc:
        assert "real-flight preflight check failed" in str(exc)
    else:
        raise AssertionError("expected real-flight preflight failure")


def test_parser_accepts_run_real_episode_command():
    parser = runner.build_parser()
    args = parser.parse_args(
        ["run-real-episode", "--condition", "C2", "--task", "T1", "--episode-index", "1"]
    )
    assert args.command == "run-real-episode"
    assert args.condition == "C2"
    assert args.task == "T1"
    assert args.episode_index == 1

def test_ensure_episode_stack_ready_restarts_on_unhealthy_baseline(monkeypatch, tmp_path):
    snapshots = iter(
        [
            {"connected": True, "armed": False, "mode": "AUTO.LOITER", "z": 0.0, "system_status": 0, "orientation_x": 0.0, "orientation_y": 0.0},
            {"connected": True, "armed": False, "mode": "AUTO.LOITER", "z": 0.0, "system_status": 0, "orientation_x": 0.0, "orientation_y": 0.0},
            {"connected": True, "armed": False, "mode": "AUTO.LOITER", "z": 0.0, "system_status": 3, "orientation_x": 0.0, "orientation_y": 0.0},
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
            {"connected": True, "armed": False, "mode": "AUTO.LOITER", "z": 0.0, "system_status": 0, "orientation_x": 0.0, "orientation_y": 0.0},
            {"connected": True, "armed": False, "mode": "AUTO.LOITER", "z": 0.0, "system_status": 3, "orientation_x": 0.0, "orientation_y": 0.0},
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


def test_square_pattern_metrics_requires_ordered_waypoints(tmp_path):
    log_path = tmp_path / "monitor.jsonl"
    records = [
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 0.0, "z": 0.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 0.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 1.0, "y": 0.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 1.0, "y": 1.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 1.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 0.0, "z": 1.0}}}},
    ]
    log_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    metrics = runner._square_pattern_metrics(log_path)

    assert metrics["square_waypoints_reached"] == 5
    assert metrics["square_pattern_complete"] is True


def test_square_pattern_metrics_fails_without_return_to_start(tmp_path):
    log_path = tmp_path / "monitor.jsonl"
    records = [
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 0.0, "z": 0.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 0.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 1.0, "y": 0.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 1.0, "y": 1.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 1.0, "z": 1.0}}}},
        {"kind": "pose", "payload": {"pose": {"position": {"x": 0.0, "y": 1.0, "z": 0.0}}}},
    ]
    log_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")

    metrics = runner._square_pattern_metrics(log_path)

    assert metrics["square_waypoints_reached"] == 4
    assert metrics["square_pattern_complete"] is False


def test_parser_accepts_run_real_episode_with_prompt_profile():
    parser = runner.build_parser()
    args = parser.parse_args(
        [
            "run-real-episode",
            "--condition",
            "C2",
            "--task",
            "T1",
            "--episode-index",
            "1",
            "--prompt-level",
            "high",
            "--prompt-variant",
            "c",
        ]
    )
    assert args.command == "run-real-episode"
    assert args.prompt_level == "high"
    assert args.prompt_variant == "c"


def test_run_educational_batch_sets_c2_prompt_matrix(monkeypatch):
    captured = {}

    def fake_run_batch(args):
        captured.update(vars(args))
        return Path("/tmp/educational")

    monkeypatch.setattr(runner, "run_batch", fake_run_batch)

    parser = runner.build_parser()
    args = parser.parse_args(["run-educational-batch", "--batch-id", "edu-001"])
    runner.run_educational_batch(args)

    assert captured["conditions"] == ["C2"]
    assert captured["tasks"] == ["T1", "T2", "T3"]
    assert captured["repetitions"] == 1
    assert captured["prompt_levels"] == ["elementary", "middle", "high", "college"]
    assert captured["prompt_variants"] == ["a", "b", "c"]
    assert captured["phase"] == "educational_sim"


def test_run_batch_uses_profiled_episode_directory(tmp_path, monkeypatch):
    def fake_run_episode(args: Namespace) -> Path:
        spec = runner.EpisodeMatrixEntry(
            condition=args.condition,
            task_id=args.task,
            episode_index=args.episode_index,
            prompt_level=args.prompt_level,
            prompt_variant=args.prompt_variant,
        )
        episode_dir = runner._episode_dir_for(Path(args.output_root) / args.batch_id, spec)
        if args.clean_existing and episode_dir.exists():
            shutil.rmtree(episode_dir)
        episode_dir.mkdir(parents=True, exist_ok=True)
        metrics = {
            "condition": args.condition,
            "task_id": args.task,
            "episode_index": args.episode_index,
            "prompt_level": args.prompt_level,
            "prompt_variant": args.prompt_variant,
            "infra_error": False,
            "infra_error_reasons": [],
            "task_success": True,
            "failure_codes": [],
        }
        (episode_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        (episode_dir / "metadata.json").write_text(
            json.dumps({"turns": [], "selected_helpers": [], "prompt_level": args.prompt_level, "prompt_variant": args.prompt_variant}),
            encoding="utf-8",
        )
        return episode_dir

    monkeypatch.setattr(runner, "run_episode", fake_run_episode)
    monkeypatch.setattr(
        runner,
        "analyze_batch",
        lambda batch_dir: {
            "reports": [],
            "selection": {"selected_helpers": [], "status": "pending"},
            "audit": {"notes": []},
        },
    )

    args = _shared_args(tmp_path)
    args.conditions = ["C2"]
    args.tasks = ["T1"]
    args.prompt_levels = ["elementary"]
    args.prompt_variants = ["a"]
    runner.run_batch(args)

    profiled_dir = tmp_path / "batch-001" / "C2" / "T1" / "elementary" / "a" / "episode-01"
    assert profiled_dir.exists()
    state = json.loads((tmp_path / "batch-001" / "batch_state.json").read_text(encoding="utf-8"))
    assert "C2:T1:elementary:a:01" in state["episodes"]
