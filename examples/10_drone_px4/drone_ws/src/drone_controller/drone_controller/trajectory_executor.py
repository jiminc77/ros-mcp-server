import math
import time
from dataclasses import dataclass

import rclpy
from drone_interfaces.action import DroneTrajectory

from drone_controller.flight_prep import prepare_for_flight
from drone_controller.runtime import CancelToken


@dataclass(frozen=True)
class TrajectoryOutcome:
    success: bool
    status: str
    status_code: str
    status_message: str


async def execute_trajectory_goal(
    node,
    goal_handle,
    token: CancelToken,
    goal_id: str,
) -> TrajectoryOutcome:
    req = goal_handle.request
    points = [(float(p.x), float(p.y), float(p.z)) for p in req.points]
    if not points:
        goal_handle.abort()
        return TrajectoryOutcome(False, "error", "E_INVALID_REQUEST", "No trajectory points provided")

    ready, code, message = await prepare_for_flight(node, token, goal_id)
    if not ready:
        goal_handle.abort()
        return TrajectoryOutcome(False, "error", code, message)

    requested_speed = float(req.speed) if req.speed > 0.0 else node.config.default_speed_mps
    speed = min(requested_speed, node.config.max_trajectory_speed_mps)
    tolerance = (
        float(req.tolerance) if req.tolerance > 0.0 else node.config.default_trajectory_tolerance_m
    )

    setpoint = [
        float(node.current_pose.pose.position.x),
        float(node.current_pose.pose.position.y),
        float(node.current_pose.pose.position.z),
    ]
    virtual_speed = 0.0
    feedback = DroneTrajectory.Feedback()
    feedback_period_sec = 0.1
    last_feedback_ts = 0.0

    for idx, target in enumerate(points):
        waypoint_start = time.monotonic()

        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                token.cancel()
            if token.canceled:
                goal_handle.canceled()
                return TrajectoryOutcome(False, "error", "E_CANCELED", "Trajectory canceled")

            dx = target[0] - setpoint[0]
            dy = target[1] - setpoint[1]
            dz = target[2] - setpoint[2]
            dist_setpoint_to_target = math.sqrt(dx * dx + dy * dy + dz * dz)

            if dist_setpoint_to_target > 1e-4:
                decel_distance = (virtual_speed * virtual_speed) / (2.0 * node.config.max_setpoint_accel_mps2)
                if dist_setpoint_to_target <= decel_distance:
                    virtual_speed = max(
                        0.0,
                        virtual_speed - node.config.max_setpoint_accel_mps2 * node.config.control_dt,
                    )
                else:
                    virtual_speed = min(
                        speed,
                        virtual_speed + node.config.max_setpoint_accel_mps2 * node.config.control_dt,
                    )

                step = min(dist_setpoint_to_target, virtual_speed * node.config.control_dt)
                if step > 0.0:
                    scale = step / dist_setpoint_to_target
                    setpoint[0] += dx * scale
                    setpoint[1] += dy * scale
                    setpoint[2] += dz * scale
                    node._set_heading_towards(dx, dy)
            else:
                setpoint[0], setpoint[1], setpoint[2] = target
                virtual_speed = 0.0

            node._set_target_pose(setpoint[0], setpoint[1], setpoint[2])

            current = (
                float(node.current_pose.pose.position.x),
                float(node.current_pose.pose.position.y),
                float(node.current_pose.pose.position.z),
            )
            drone_dist_to_target = math.dist(current, target)

            now = time.monotonic()
            if now - last_feedback_ts >= feedback_period_sec:
                feedback.current_point_index = idx
                feedback.distance_remaining = float(drone_dist_to_target)
                goal_handle.publish_feedback(feedback)
                last_feedback_ts = now

            if drone_dist_to_target <= tolerance:
                break

            if time.monotonic() - waypoint_start > node.config.timeout_waypoint_sec:
                goal_handle.abort()
                return TrajectoryOutcome(
                    False,
                    "error",
                    "E_WAYPOINT_TIMEOUT",
                    f"Timeout while reaching waypoint {idx}",
                )

            token.sleep(node.config.control_dt)

        if not req.fly_through:
            token.sleep(node.config.default_hold_time_sec)

    goal_handle.succeed()
    return TrajectoryOutcome(True, "success", "OK_TRAJECTORY_COMPLETE", "Trajectory complete")
