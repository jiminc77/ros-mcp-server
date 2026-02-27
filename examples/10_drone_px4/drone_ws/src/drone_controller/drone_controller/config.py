from dataclasses import dataclass

from rclpy.node import Node


@dataclass(frozen=True)
class ControllerConfig:
    control_rate_hz: float
    default_speed_mps: float
    max_trajectory_speed_mps: float
    max_setpoint_accel_mps2: float
    max_takeoff_altitude_m: float
    default_takeoff_tolerance_m: float
    default_trajectory_tolerance_m: float
    timeout_service_ready_sec: float
    timeout_takeoff_sec: float
    timeout_waypoint_sec: float
    timeout_offboard_prime_sec: float
    default_hold_time_sec: float

    @property
    def control_dt(self) -> float:
        hz = max(1e-3, float(self.control_rate_hz))
        return 1.0 / hz


def _param(node: Node, name: str, default):
    if not node.has_parameter(name):
        node.declare_parameter(name, default)
    return node.get_parameter(name).value


def load_controller_config(node: Node) -> ControllerConfig:
    return ControllerConfig(
        control_rate_hz=float(_param(node, "control_rate_hz", 50.0)),
        default_speed_mps=float(_param(node, "default_speed_mps", 0.8)),
        max_trajectory_speed_mps=max(0.1, float(_param(node, "max_trajectory_speed_mps", 3.0))),
        max_setpoint_accel_mps2=float(_param(node, "max_setpoint_accel_mps2", 0.8)),
        max_takeoff_altitude_m=max(0.5, float(_param(node, "max_takeoff_altitude_m", 20.0))),
        default_takeoff_tolerance_m=float(_param(node, "default_takeoff_tolerance_m", 0.2)),
        default_trajectory_tolerance_m=float(
            _param(node, "default_trajectory_tolerance_m", 0.3)
        ),
        timeout_service_ready_sec=max(0.1, float(_param(node, "timeout_service_ready_sec", 3.0))),
        timeout_takeoff_sec=float(_param(node, "timeout_takeoff_sec", 45.0)),
        timeout_waypoint_sec=float(_param(node, "timeout_waypoint_sec", 45.0)),
        timeout_offboard_prime_sec=float(_param(node, "timeout_offboard_prime_sec", 1.0)),
        default_hold_time_sec=float(_param(node, "default_hold_time_sec", 0.5)),
    )
