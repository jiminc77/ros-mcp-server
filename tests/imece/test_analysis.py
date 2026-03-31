from ros_mcp.imece.analysis import classify_episode_report, select_c2_helpers
from ros_mcp.imece.runner import _task_success


def test_classify_episode_report_marks_t4_actuation_as_f1():
    report = {
        "task_id": "T4",
        "terminal_label": "DONE",
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
