"""Shared IMECE constants."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "imece"
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "imece" / "gemini-policy.toml"
DEFAULT_C2_FREEZE_PATH = REPO_ROOT / "config" / "imece" / "c2_freeze.json"

ROSBRIDGE_DEFAULT_IP = "127.0.0.1"
ROSBRIDGE_DEFAULT_PORT = 9090

MCP_SERVER_NAME = "ros-mcp-imece"

GENERIC_TOOL_NAMES = [
    "connect_to_robot",
    "ping_robot",
    "detect_ros_version",
    "get_topics",
    "get_topic_type",
    "get_topic_details",
    "get_message_details",
    "subscribe_once",
    "subscribe_for_duration",
    "publish_once",
    "publish_for_durations",
    "get_services",
    "get_service_type",
    "get_service_details",
    "call_service",
]

VISIBLE_HELPER_TOOL_NAMES = ["setpoint_relay", "mode_guard"]
INTERNAL_HELPER_NAMES = ["frame_guard", "abort_watchdog"]
ALL_HELPER_NAMES = VISIBLE_HELPER_TOOL_NAMES + INTERNAL_HELPER_NAMES

MONITOR_TOPICS = {
    "state": ("/mavros/state", "mavros_msgs/msg/State"),
    "pose": ("/mavros/local_position/pose", "geometry_msgs/msg/PoseStamped"),
    "setpoint": ("/mavros/setpoint_position/local", "geometry_msgs/msg/PoseStamped"),
}

ROSBAG_TOPICS = [
    "/mavros/state",
    "/mavros/local_position/pose",
    "/mavros/setpoint_position/local",
    "/mavros/battery",
]

ALLOWED_TOPIC_TYPES = {
    "/mavros/state": "mavros_msgs/msg/State",
    "/mavros/local_position/pose": "geometry_msgs/msg/PoseStamped",
    "/mavros/setpoint_position/local": "geometry_msgs/msg/PoseStamped",
    "/mavros/battery": "sensor_msgs/msg/BatteryState",
}

SET_MODE_SERVICE = "/mavros/set_mode"
SET_MODE_SERVICE_TYPE = "mavros_msgs/srv/SetMode"
ARMING_SERVICE = "/mavros/cmd/arming"
ARMING_SERVICE_TYPE = "mavros_msgs/srv/CommandBool"

ALLOWED_SERVICES = {
    SET_MODE_SERVICE: SET_MODE_SERVICE_TYPE,
    ARMING_SERVICE: ARMING_SERVICE_TYPE,
}

OFFBOARD_MODE = "OFFBOARD"
LAND_MODE = "AUTO.LAND"

TERMINAL_TAGS = ("CLARIFY", "REFUSE", "DONE")

HELPER_PROMPT_DESCRIPTIONS = {
    "setpoint_relay": "maintains the last valid local `PoseStamped` target at `20 Hz` on `/mavros/setpoint_position/local`",
    "frame_guard": "rejects obvious `ENU` frame or sign mistakes before accepting a relay target",
    "mode_guard": "enforces the guarded order `prestream -> OFFBOARD -> arm` and exposes `LAND` mode",
    "abort_watchdog": "commands `AUTO.LAND` if the runner heartbeat stops or an abort flag is raised",
}
