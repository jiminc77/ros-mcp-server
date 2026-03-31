from ros_mcp.imece.analysis import classify_episode_report, select_c2_helpers
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
        "x_span_m": 0.95,
        "y_span_m": 0.91,
    }
    assert _task_success("T3", report) is True


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
