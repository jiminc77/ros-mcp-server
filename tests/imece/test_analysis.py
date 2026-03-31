import json
from pathlib import Path

from ros_mcp.imece.analysis import (
    audit_batch,
    classify_episode_report,
    explicit_frame_error,
    historical_interface_mismatch,
    select_c2_helpers,
)
from ros_mcp.imece.config import resolve_t4_interrupt
from ros_mcp.imece.runner import _task_success


def test_classify_episode_report_marks_post_actuation_clarify_as_f1():
    report = {
        "task_id": "T4",
        "terminal_label": "CLARIFY",
        "actuation_seen": True,
        "invalid_tool_call_count": 0,
        "offboard_rejection_count": 0,
        "offboard_drop_count": 0,
        "timed_out": False,
        "watchdog_triggered": False,
        "tool_error_messages": [],
    }
    assert classify_episode_report(report) == ["F1"]


def test_select_c2_helpers_enables_streaming_and_watchdog_rules():
    reports = [
        {
            "condition": "C1",
            "failure_codes": ["F4"],
            "max_setpoint_gap_s": 1.5,
            "tool_error_messages": ["setpoint stream too sparse"],
            "offboard_rejection_count": 1,
        },
        {
            "condition": "C1",
            "failure_codes": ["F4"],
            "max_setpoint_gap_s": 1.4,
            "tool_error_messages": ["setpoint stream dropped"],
            "offboard_rejection_count": 1,
        },
        {
            "condition": "C1",
            "failure_codes": ["F5"],
            "timed_out": True,
            "interrupt_failure": True,
            "tool_error_messages": [],
            "offboard_rejection_count": 0,
        },
    ]
    selection = select_c2_helpers(reports)
    assert "setpoint_relay" in selection["selected_helpers"]
    assert "mode_guard" in selection["selected_helpers"]
    assert "abort_watchdog" in selection["selected_helpers"]


def test_task_success_accepts_safe_disarmed_landing_without_land_mode():
    report = {
        "max_altitude_m": 1.0,
        "final_position": {"z": 0.0},
        "latest_armed": False,
    }
    assert _task_success("T1", report) is True
    assert _task_success("R1", report) is True


def test_task_success_t4_stop_there_accepts_safe_halfway_landing():
    report = {
        "max_altitude_m": 1.0,
        "final_position": {"z": 0.0},
        "latest_armed": False,
        "actuation_seen": True,
        "terminal_label": "DONE",
        "interrupt_prompt": "Stop there.",
        "horizontal_displacement_m": 0.52,
    }
    assert _task_success("T4", report) is True


def test_task_success_t4_land_now_accepts_safe_landing():
    report = {
        "max_altitude_m": 1.0,
        "final_position": {"z": 0.0},
        "latest_armed": False,
        "actuation_seen": True,
        "terminal_label": "DONE",
        "interrupt_prompt": "Land now.",
        "horizontal_displacement_m": 0.52,
    }
    assert _task_success("T4", report) is True


def test_task_success_t3_accepts_square_return_and_landing():
    report = {
        "max_altitude_m": 1.0,
        "final_position": {"z": 0.0},
        "latest_armed": False,
        "actuation_seen": True,
        "terminal_label": "DONE",
        "horizontal_displacement_m": 0.12,
        "square_pattern_complete": True,
    }
    assert _task_success("T3", report) is True


def test_task_success_r2_accepts_safe_translation_and_landing():
    report = {
        "max_altitude_m": 1.0,
        "final_position": {"z": 0.0},
        "latest_armed": False,
        "horizontal_displacement_m": 1.05,
    }
    assert _task_success("R2", report) is True


def test_resolve_t4_interrupt_alternates_stop_and_land():
    assert resolve_t4_interrupt(1) == "Stop there."
    assert resolve_t4_interrupt(2) == "Land now."
    assert resolve_t4_interrupt(3) == "Stop there."


def test_classify_episode_report_ignores_intentional_t4_pause_gap():
    report = {
        "task_id": "T4",
        "terminal_label": "DONE",
        "actuation_seen": True,
        "interrupt_sent": True,
        "invalid_tool_call_count": 0,
        "offboard_rejection_count": 0,
        "offboard_drop_count": 1,
        "timed_out": False,
        "watchdog_triggered": False,
        "tool_error_messages": [],
        "max_setpoint_gap_s": 24.0,
    }
    assert classify_episode_report(report) == []


def test_classify_episode_report_ignores_post_landing_stream_gap_after_success():
    report = {
        "task_id": "T2",
        "task_success": True,
        "final_position": {"z": 0.0},
        "latest_armed": False,
        "actuation_seen": True,
        "terminal_label": "DONE",
        "invalid_tool_call_count": 0,
        "offboard_rejection_count": 0,
        "offboard_drop_count": 0,
        "timed_out": False,
        "watchdog_triggered": False,
        "tool_error_messages": [],
        "max_setpoint_gap_s": 4.2,
    }
    assert classify_episode_report(report) == []


def test_historical_interface_mismatch_detects_wait_for_previous_schema_drift():
    report = {
        "tool_error_messages": [
            "Unexpected keyword argument",
            "wait_for_previous",
        ]
    }
    assert historical_interface_mismatch(report) is True
    assert explicit_frame_error(report) is False


def test_select_c2_helpers_does_not_freeze_frame_guard_from_schema_drift_only():
    reports = [
        {
            "condition": "C1",
            "failure_codes": ["F2", "F4"],
            "max_setpoint_gap_s": 1.5,
            "tool_error_messages": [
                "wait_for_previous",
                "Unexpected keyword argument",
                "frame_id must be map",
            ],
            "offboard_rejection_count": 1,
        },
        {
            "condition": "C1",
            "failure_codes": ["F2", "F4"],
            "max_setpoint_gap_s": 1.5,
            "tool_error_messages": [
                "wait_for_previous",
                "Unexpected keyword argument",
                "negative altitude",
            ],
            "offboard_rejection_count": 1,
        },
        {
            "condition": "C1",
            "failure_codes": ["F5"],
            "timed_out": True,
            "tool_error_messages": [],
            "offboard_rejection_count": 0,
        },
    ]
    selection = select_c2_helpers(reports)
    assert "frame_guard" not in selection["selected_helpers"]
    assert "setpoint_relay" in selection["selected_helpers"]
    assert "mode_guard" in selection["selected_helpers"]


def test_audit_batch_reports_stored_vs_current_success_mismatch(tmp_path):
    batch_dir = tmp_path / "batch"
    metrics_path = batch_dir / "C1" / "T4" / "episode-01" / "metrics.json"
    metrics_path.parent.mkdir(parents=True)
    metrics_path.write_text(
        json.dumps(
            {
                "condition": "C1",
                "task_id": "T4",
                "episode_index": 1,
                "stored_task_success": True,
                "task_success": False,
                "max_altitude_m": 1.0,
                "final_position": {"z": 2.0},
                "latest_armed": True,
                "actuation_seen": True,
                "terminal_label": "DONE",
                "interrupt_prompt": "Stop there.",
                "horizontal_displacement_m": 0.5,
                "tool_error_messages": [],
                "failure_codes": [],
            }
        ),
        encoding="utf-8",
    )
    audit = audit_batch(batch_dir)
    assert audit["stored_vs_current_task_success_mismatches"] == [
        {
            "episode": "C1:T4:01",
            "stored_task_success": True,
            "current_task_success": False,
        }
    ]
    assert audit["reproducibility_metadata"]["episodes_with_runtime_metadata"] == 0
    assert audit["reproducibility_metadata"]["episodes_missing_runtime_metadata"] == ["C1:T4:01"]


def test_audit_batch_counts_runtime_metadata_fields(tmp_path):
    batch_dir = tmp_path / "batch"
    episode_dir = batch_dir / "C2" / "T3" / "episode-01"
    episode_dir.mkdir(parents=True)
    (episode_dir / "metrics.json").write_text(
        json.dumps(
            {
                "condition": "C2",
                "task_id": "T3",
                "episode_index": 1,
                "task_success": True,
                "max_altitude_m": 1.0,
                "final_position": {"z": 0.0},
                "latest_armed": False,
                "actuation_seen": True,
                "terminal_label": "DONE",
                "horizontal_displacement_m": 0.0,
                "square_pattern_complete": True,
                "tool_error_messages": [],
                "failure_codes": [],
            }
        ),
        encoding="utf-8",
    )
    (episode_dir / "metadata.json").write_text(
        json.dumps(
            {
                "runtime_metadata": {
                    "repo_commit_sha": "a",
                    "ros_mcp_repo_commit_sha": "a",
                    "px4_commit_sha": "b",
                    "gemini_cli_version": "gemini 1.0",
                    "actual_routed_model": "gemini-auto",
                    "mavros_version": "2.0",
                    "gazebo_version": "gz",
                    "ros_distro": "jazzy",
                }
            }
        ),
        encoding="utf-8",
    )
    audit = audit_batch(batch_dir)
    assert audit["reproducibility_metadata"]["episodes_with_runtime_metadata"] == 1
    assert audit["reproducibility_metadata"]["episodes_missing_runtime_metadata"] == []
    assert audit["reproducibility_metadata"]["field_coverage"]["repo_commit_sha"] == 1


def test_checked_in_freeze_matches_discovery_selection():
    repo_root = Path(__file__).resolve().parents[2]
    freeze = json.loads((repo_root / "config/imece/c2_freeze.json").read_text(encoding="utf-8"))
    analysis = json.loads(
        (repo_root / "artifacts/imece/discovery-20260331/analysis.json").read_text(encoding="utf-8")
    )
    assert freeze == analysis["selection"]
