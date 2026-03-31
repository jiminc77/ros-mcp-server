"""IMECE-scoped MCP server."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ros_mcp.tools.connection import register_connection_tools
from ros_mcp.utils.websocket import WebSocketManager

from .boundary_tools import register_filtered_service_tools, register_filtered_topic_tools
from .constants import ROSBRIDGE_DEFAULT_IP, ROSBRIDGE_DEFAULT_PORT
from .helpers import AbortWatchdog, ModeGuard, PoseRelay
from .rosbridge import RosbridgeRequester


def _register_detect_ros_version_tool(mcp: FastMCP, ws_manager: WebSocketManager) -> None:
    @mcp.tool(
        description="Detect the ROS version and distribution via rosbridge.",
        annotations=ToolAnnotations(title="Detect ROS Version", readOnlyHint=True),
    )
    def detect_ros_version() -> dict:
        ros2_request = {
            "op": "call_service",
            "id": "imece_ros2_version_check",
            "service": "/rosapi/get_ros_version",
            "args": {},
        }
        with ws_manager:
            response = ws_manager.request(ros2_request)
            values = response.get("values") if response else None
            if isinstance(values, dict) and "version" in values:
                return {"version": values.get("version"), "distro": values.get("distro")}
            return {"error": "Could not detect ROS version"}


def build_mcp() -> FastMCP:
    rosbridge_ip = os.getenv("ROSBRIDGE_IP", ROSBRIDGE_DEFAULT_IP)
    rosbridge_port = int(os.getenv("ROSBRIDGE_PORT", str(ROSBRIDGE_DEFAULT_PORT)))
    selected_helpers = {
        helper.strip()
        for helper in os.getenv("IMECE_SELECTED_HELPERS", "").split(",")
        if helper.strip()
    }

    mcp = FastMCP("ros-mcp-imece")
    ws_manager = WebSocketManager(rosbridge_ip, rosbridge_port, default_timeout=5.0)

    register_connection_tools(mcp, ws_manager, rosbridge_ip, rosbridge_port)
    _register_detect_ros_version_tool(mcp, ws_manager)
    register_filtered_service_tools(mcp, ws_manager)
    register_filtered_topic_tools(mcp, ws_manager)

    if selected_helpers:
        helper_ws = RosbridgeRequester(
            rosbridge_ip,
            rosbridge_port,
            timeout=5.0,
        )
        relay = PoseRelay(
            helper_ws,
            frame_guard_enabled="frame_guard" in selected_helpers,
        )
        mode_guard_runtime = ModeGuard(helper_ws, relay)
        watchdog = AbortWatchdog(
            mode_guard_runtime,
            heartbeat_file=(
                Path(os.environ["IMECE_WATCHDOG_HEARTBEAT_FILE"])
                if os.getenv("IMECE_WATCHDOG_HEARTBEAT_FILE")
                else None
            ),
            timeout_s=float(os.getenv("IMECE_WATCHDOG_TIMEOUT_S", "5.0")),
            enabled="abort_watchdog" in selected_helpers,
        )
        watchdog.start()

        if "setpoint_relay" in selected_helpers:

            @mcp.tool(
                description=(
                    "Maintain the last valid local PoseStamped target at 20 Hz on /mavros/setpoint_position/local."
                ),
                annotations=ToolAnnotations(title="Setpoint Relay", destructiveHint=True),
            )
            def setpoint_relay(target: dict, wait_for_previous: bool | None = None) -> dict:
                del wait_for_previous
                return relay.set_target(target)

        if "mode_guard" in selected_helpers:

            @mcp.tool(
                description=(
                    "Guarded mode helper. Use action='engage_offboard' after setpoint_relay or action='land' to command AUTO.LAND."
                ),
                annotations=ToolAnnotations(title="Mode Guard", destructiveHint=True),
            )
            def mode_guard(
                action: str,
                arm: bool = True,
                prestream_seconds: float = 1.0,
                wait_for_previous: bool | None = None,
            ) -> dict:
                del wait_for_previous
                if action == "engage_offboard":
                    return mode_guard_runtime.engage_offboard(
                        arm=arm,
                        prestream_seconds=prestream_seconds,
                    )
                if action == "land":
                    return mode_guard_runtime.land()
                return {"error": "action must be 'engage_offboard' or 'land'"}

    return mcp


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="IMECE-scoped ros-mcp server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "streamable-http", "sse"],
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    mcp = build_mcp()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
