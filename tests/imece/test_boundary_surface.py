from ros_mcp.imece.constants import ALLOWED_SERVICES, ALLOWED_TOPIC_TYPES
from ros_mcp.imece.monitor import FlightMonitor


def test_surface_is_limited_to_pose_state_battery_and_mode_arming():
    assert "/mavros/set_mode" in ALLOWED_SERVICES
    assert "/mavros/cmd/arming" in ALLOWED_SERVICES
    assert "/mavros/cmd/takeoff" not in ALLOWED_SERVICES
    assert "/mavros/state" in ALLOWED_TOPIC_TYPES
    assert "/mavros/local_position/pose" in ALLOWED_TOPIC_TYPES
    assert "/mavros/setpoint_position/local" in ALLOWED_TOPIC_TYPES


def test_monitor_does_not_count_auto_land_as_offboard_drop(tmp_path):
    monitor = FlightMonitor("127.0.0.1", 9090, tmp_path / "monitor.jsonl")
    monitor._latest_mode = "OFFBOARD"
    monitor._latest_position = {"x": 0.0, "y": 0.0, "z": 1.0}

    monitor._on_state({"mode": "AUTO.LAND", "armed": True})

    assert monitor.snapshot().offboard_drop_count == 0
