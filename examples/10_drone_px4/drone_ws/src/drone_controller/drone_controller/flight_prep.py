import time

from mavros_msgs.srv import CommandBool, SetMode

from drone_controller.runtime import CancelToken, log_phase


def _wait_for_service(client, timeout_sec: float, token: CancelToken, poll_sec: float = 0.05) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout_sec))
    while time.monotonic() < deadline:
        if token.canceled:
            return False
        if client.service_is_ready():
            return True
        if not token.sleep(poll_sec):
            return False
    return client.service_is_ready()


async def prepare_for_flight(node, token: CancelToken, goal_id: str) -> tuple[bool, str, str]:
    if token.canceled:
        return False, "E_CANCELED", "Goal canceled"

    if not node.current_state.connected:
        return False, "E_FCU_NOT_CONNECTED", "FCU not connected"

    if not node.is_primed:
        return False, "E_LOCAL_POSE_NOT_READY", "Local position lock not ready"

    if not _wait_for_service(node.mode_cli, node.config.timeout_service_ready_sec, token):
        return False, "E_SET_MODE_SERVICE_UNAVAILABLE", "SetMode service unavailable"

    if not _wait_for_service(node.arm_cli, node.config.timeout_service_ready_sec, token):
        return False, "E_ARM_SERVICE_UNAVAILABLE", "Arming service unavailable"

    prime_until = time.monotonic() + node.config.timeout_offboard_prime_sec
    while time.monotonic() < prime_until:
        if token.canceled:
            return False, "E_CANCELED", "Goal canceled"
        if not node.current_state.connected:
            return False, "E_FCU_NOT_CONNECTED", "FCU connection lost"
        token.sleep(node.config.control_dt)

    if node.current_state.mode != "OFFBOARD":
        mode_req = SetMode.Request(custom_mode="OFFBOARD")
        mode_resp = await node.mode_cli.call_async(mode_req)
        mode_set = bool(mode_resp and mode_resp.mode_sent) or node.current_state.mode == "OFFBOARD"
        if not mode_set:
            log_phase(node, "flight_prep", goal_id=goal_id, level="error", detail="set OFFBOARD failed")
            return False, "E_OFFBOARD_SET_FAILED", "Failed to set OFFBOARD mode"

    if not node.current_state.armed:
        arm_req = CommandBool.Request(value=True)
        arm_resp = await node.arm_cli.call_async(arm_req)
        arm_ok = bool(arm_resp and arm_resp.success) or node.current_state.armed
        if not arm_ok:
            last_result = getattr(arm_resp, "result", None) if arm_resp is not None else None
            return (
                False,
                "E_ARM_FAILED",
                f"Failed to arm (last_result={last_result}, mode={node.current_state.mode})",
            )

    return True, "OK_READY", "Flight ready"
