import asyncio
import math
import time
from threading import Lock

import rclpy
from drone_interfaces.action import DroneTakeoff, DroneTrajectory
from geometry_msgs.msg import PoseStamped
from mavros_msgs.msg import State
from mavros_msgs.srv import CommandBool, SetMode
from rclpy.action import ActionServer
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParameterClient
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy, qos_profile_sensor_data


class DroneMCPBridge(Node):
    CONTROL_RATE_HZ = 50.0
    CONTROL_DT = 1.0 / CONTROL_RATE_HZ
    DEFAULT_SPEED_MPS = 1.0
    MAX_SETPOINT_ACCEL_MPS2 = 0.8
    TAKEOFF_TOLERANCE_M = 0.2
    DEFAULT_TRAJECTORY_TOLERANCE_M = 0.3
    TAKEOFF_TIMEOUT_SEC = 45.0
    WAYPOINT_TIMEOUT_SEC = 120.0
    HOLD_TIME_SEC = 0.5

    def __init__(self):
        super().__init__("drone_mcp_bridge")
        self.callback_group = ReentrantCallbackGroup()

        setpoint_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.local_pos_pub = self.create_publisher(
            PoseStamped, "/mavros/setpoint_position/local", setpoint_qos
        )
        self.state_sub = self.create_subscription(State, "/mavros/state", self.state_cb, 10)
        self.local_pos_sub = self.create_subscription(
            PoseStamped, "/mavros/local_position/pose", self.local_cb, qos_profile_sensor_data
        )

        self.arm_cli = self.create_client(
            CommandBool, "/mavros/cmd/arming", callback_group=self.callback_group
        )
        self.mode_cli = self.create_client(
            SetMode, "/mavros/set_mode", callback_group=self.callback_group
        )
        self.local_pos_param_cli = AsyncParameterClient(self, "/mavros/local_position")
        self._local_pos_param_pending = False
        self._local_pos_param_ready = False
        self._local_pos_param_attempts = 0
        self._local_pos_param_last_try = 0.0

        self._action_takeoff = ActionServer(
            self,
            DroneTakeoff,
            "drone_control/takeoff",
            self.execute_takeoff,
            callback_group=self.callback_group,
        )
        self._action_trajectory = ActionServer(
            self,
            DroneTrajectory,
            "drone_control/trajectory",
            self.execute_trajectory,
            callback_group=self.callback_group,
        )

        self.current_state = State()
        self.current_pose = PoseStamped()
        self.target_pose = PoseStamped()
        self.target_pose.header.frame_id = "map"
        self.target_pose.pose.orientation.w = 1.0
        self.is_primed = False

        self._goal_lock = Lock()
        self._active_goal_name = ""

        self.timer = self.create_timer(
            self.CONTROL_DT, self.timer_callback, callback_group=self.callback_group
        )
        self.get_logger().info("--- Drone Bridge Online (Fixed 50Hz + Smoothed Setpoint) ---")

    def state_cb(self, msg: State) -> None:
        self.current_state = msg
        self.ensure_local_position_tf_params()

    def local_cb(self, msg: PoseStamped) -> None:
        self.ensure_local_position_tf_params()

        self.current_pose = msg
        if not self.is_primed:
            self.target_pose.pose.position.x = msg.pose.position.x
            self.target_pose.pose.position.y = msg.pose.position.y
            self.target_pose.pose.position.z = msg.pose.position.z
            self.target_pose.pose.orientation = msg.pose.orientation
            self.is_primed = True
            self.get_logger().info(
                f"Local pose locked at x={msg.pose.position.x:.2f}, "
                f"y={msg.pose.position.y:.2f}, z={msg.pose.position.z:.2f}"
            )

    def timer_callback(self) -> None:
        self.ensure_local_position_tf_params()

        if not self.is_primed:
            return

        self.target_pose.header.stamp = self.get_clock().now().to_msg()
        self.local_pos_pub.publish(self.target_pose)

    def ensure_local_position_tf_params(self) -> None:
        if self._local_pos_param_pending:
            return
        now = time.monotonic()
        if now - self._local_pos_param_last_try < 2.0:
            return

        params = [
            Parameter("tf.send", Parameter.Type.BOOL, True),
            Parameter("tf.frame_id", Parameter.Type.STRING, "map"),
            Parameter("tf.child_frame_id", Parameter.Type.STRING, "base_link"),
        ]
        self._local_pos_param_attempts += 1
        self._local_pos_param_last_try = now
        self._local_pos_param_pending = True
        try:
            future = self.local_pos_param_cli.set_parameters(params)
        except Exception as exc:
            self._local_pos_param_pending = False
            if self._local_pos_param_attempts % 5 == 0:
                self.get_logger().warn(
                    "Waiting for MAVROS local_position parameter service "
                    f"(attempt {self._local_pos_param_attempts}): {exc}"
                )
            return
        future.add_done_callback(self._on_local_position_tf_params_set)

    def _on_local_position_tf_params_set(self, future) -> None:
        self._local_pos_param_pending = False
        try:
            result_obj = future.result()
        except Exception as exc:
            self.get_logger().warn(f"Failed to set MAVROS local_position TF params: {exc}")
            return

        results = result_obj.results if hasattr(result_obj, "results") else result_obj
        if not results:
            self.get_logger().warn("MAVROS local_position TF param set returned empty response")
            return

        failed = [getattr(r, "reason", "") for r in results if not getattr(r, "successful", False)]
        if failed:
            self.get_logger().warn(
                "MAVROS local_position TF param set rejected "
                f"(attempt {self._local_pos_param_attempts}): {failed}"
            )
            return

        if results and all(r.successful for r in results):
            if not self._local_pos_param_ready:
                self.get_logger().info("MAVROS local_position TF params set (tf.send=true)")
            self._local_pos_param_ready = True

    def _claim_goal(self, name: str) -> tuple[bool, str]:
        if not self._goal_lock.acquire(blocking=False):
            active = self._active_goal_name or "another goal"
            return False, self._status("E_GOAL_BUSY", f"{active} is already running")
        self._active_goal_name = name
        return True, ""

    def _release_goal(self) -> None:
        self._active_goal_name = ""
        self._goal_lock.release()

    def _set_target_pose(self, x: float, y: float, z: float) -> None:
        self.target_pose.pose.position.x = x
        self.target_pose.pose.position.y = y
        self.target_pose.pose.position.z = z

    def _set_heading_towards(self, dx: float, dy: float) -> None:
        if math.hypot(dx, dy) < 0.05:
            return
        yaw = math.atan2(dy, dx)
        self.target_pose.pose.orientation.x = 0.0
        self.target_pose.pose.orientation.y = 0.0
        self.target_pose.pose.orientation.z = math.sin(yaw * 0.5)
        self.target_pose.pose.orientation.w = math.cos(yaw * 0.5)

    @staticmethod
    def _status(code: str, detail: str) -> str:
        return f"{code}: {detail}"

    async def prepare_for_flight(self) -> tuple[bool, str]:
        if not self.current_state.connected:
            message = self._status("E_FCU_NOT_CONNECTED", "FCU not connected")
            self.get_logger().error(message)
            return False, message

        if not self.is_primed:
            message = self._status("E_LOCAL_POSE_NOT_READY", "Local position lock not ready")
            self.get_logger().warn(message)
            return False, message

        if not self.mode_cli.wait_for_service(timeout_sec=1.0):
            message = self._status("E_SET_MODE_SERVICE_UNAVAILABLE", "SetMode service unavailable")
            self.get_logger().error(message)
            return False, message
        if not self.arm_cli.wait_for_service(timeout_sec=1.0):
            message = self._status("E_ARM_SERVICE_UNAVAILABLE", "Arming service unavailable")
            self.get_logger().error(message)
            return False, message

        if self.current_state.mode != "OFFBOARD":
            mode_req = SetMode.Request(custom_mode="OFFBOARD")
            mode_resp = await self.mode_cli.call_async(mode_req)
            if not mode_resp or not mode_resp.mode_sent:
                message = self._status("E_OFFBOARD_SET_FAILED", "Failed to set OFFBOARD mode")
                self.get_logger().error(message)
                return False, message
            await asyncio.sleep(0.5)

        if not self.current_state.armed:
            arm_req = CommandBool.Request(value=True)
            arm_resp = await self.arm_cli.call_async(arm_req)
            if not arm_resp or not arm_resp.success:
                message = self._status("E_ARM_FAILED", "Failed to arm")
                self.get_logger().error(message)
                return False, message

        return True, ""

    async def execute_takeoff(self, goal_handle):
        claimed, reason = self._claim_goal("takeoff")
        if not claimed:
            goal_handle.abort()
            return DroneTakeoff.Result(success=False, message=reason)

        try:
            target_altitude = float(goal_handle.request.target_altitude)
            if target_altitude <= 0.0:
                goal_handle.abort()
                return DroneTakeoff.Result(
                    success=False,
                    message=self._status(
                        "E_INVALID_REQUEST", "target_altitude must be greater than 0"
                    ),
                )

            self.get_logger().info(f"Takeoff goal received: {target_altitude:.2f}m")
            ready, reason = await self.prepare_for_flight()
            if not ready:
                goal_handle.abort()
                return DroneTakeoff.Result(success=False, message=reason)

            self._set_target_pose(
                self.current_pose.pose.position.x,
                self.current_pose.pose.position.y,
                target_altitude,
            )

            feedback = DroneTakeoff.Feedback()
            start_time = time.monotonic()
            while rclpy.ok():
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    return DroneTakeoff.Result(
                        success=False, message=self._status("E_CANCELED", "Takeoff canceled")
                    )

                current_z = float(self.current_pose.pose.position.z)
                error = abs(target_altitude - current_z)
                feedback.current_altitude = current_z
                goal_handle.publish_feedback(feedback)

                if error <= self.TAKEOFF_TOLERANCE_M:
                    goal_handle.succeed()
                    return DroneTakeoff.Result(
                        success=True,
                        message=self._status("OK_TAKEOFF_COMPLETE", "Takeoff complete"),
                    )

                if time.monotonic() - start_time > self.TAKEOFF_TIMEOUT_SEC:
                    goal_handle.abort()
                    return DroneTakeoff.Result(
                        success=False,
                        message=self._status("E_TAKEOFF_TIMEOUT", "Takeoff timeout"),
                    )

                await asyncio.sleep(0.1)

            goal_handle.abort()
            return DroneTakeoff.Result(
                success=False, message=self._status("E_ROS_SHUTDOWN", "ROS shutdown")
            )
        finally:
            self._release_goal()

    async def execute_trajectory(self, goal_handle):
        claimed, reason = self._claim_goal("trajectory")
        if not claimed:
            goal_handle.abort()
            return DroneTrajectory.Result(success=False, message=reason)

        try:
            req = goal_handle.request
            points = [(float(p.x), float(p.y), float(p.z)) for p in req.points]
            if not points:
                goal_handle.abort()
                return DroneTrajectory.Result(
                    success=False,
                    message=self._status("E_INVALID_REQUEST", "No trajectory points provided"),
                )

            self.get_logger().info(
                f"Trajectory goal received: {len(points)} points, fly_through={req.fly_through}"
            )
            ready, reason = await self.prepare_for_flight()
            if not ready:
                goal_handle.abort()
                return DroneTrajectory.Result(success=False, message=reason)

            speed = float(req.speed) if req.speed > 0.0 else self.DEFAULT_SPEED_MPS
            tolerance = (
                float(req.tolerance)
                if req.tolerance > 0.0
                else self.DEFAULT_TRAJECTORY_TOLERANCE_M
            )

            setpoint = [
                float(self.current_pose.pose.position.x),
                float(self.current_pose.pose.position.y),
                float(self.current_pose.pose.position.z),
            ]
            virtual_speed = 0.0
            feedback = DroneTrajectory.Feedback()

            for idx, target in enumerate(points):
                waypoint_start = time.monotonic()

                while rclpy.ok():
                    if goal_handle.is_cancel_requested:
                        goal_handle.canceled()
                        return DroneTrajectory.Result(
                            success=False,
                            message=self._status("E_CANCELED", "Trajectory canceled"),
                        )

                    dx = target[0] - setpoint[0]
                    dy = target[1] - setpoint[1]
                    dz = target[2] - setpoint[2]
                    dist_setpoint_to_target = math.sqrt(dx * dx + dy * dy + dz * dz)

                    if dist_setpoint_to_target > 1e-4:
                        decel_distance = (
                            (virtual_speed * virtual_speed) / (2.0 * self.MAX_SETPOINT_ACCEL_MPS2)
                        )
                        if dist_setpoint_to_target <= decel_distance:
                            virtual_speed = max(
                                0.0, virtual_speed - self.MAX_SETPOINT_ACCEL_MPS2 * self.CONTROL_DT
                            )
                        else:
                            virtual_speed = min(
                                speed, virtual_speed + self.MAX_SETPOINT_ACCEL_MPS2 * self.CONTROL_DT
                            )

                        step = min(dist_setpoint_to_target, virtual_speed * self.CONTROL_DT)
                        if step > 0.0:
                            scale = step / dist_setpoint_to_target
                            setpoint[0] += dx * scale
                            setpoint[1] += dy * scale
                            setpoint[2] += dz * scale
                            self._set_heading_towards(dx, dy)
                    else:
                        setpoint[0], setpoint[1], setpoint[2] = target
                        virtual_speed = 0.0

                    self._set_target_pose(setpoint[0], setpoint[1], setpoint[2])

                    current = (
                        float(self.current_pose.pose.position.x),
                        float(self.current_pose.pose.position.y),
                        float(self.current_pose.pose.position.z),
                    )
                    drone_dist_to_target = math.dist(current, target)

                    feedback.current_point_index = idx
                    feedback.distance_remaining = float(drone_dist_to_target)
                    goal_handle.publish_feedback(feedback)

                    if drone_dist_to_target <= tolerance:
                        break

                    if time.monotonic() - waypoint_start > self.WAYPOINT_TIMEOUT_SEC:
                        goal_handle.abort()
                        return DroneTrajectory.Result(
                            success=False,
                            message=self._status(
                                "E_WAYPOINT_TIMEOUT", f"Timeout while reaching waypoint {idx}"
                            ),
                        )

                    await asyncio.sleep(self.CONTROL_DT)

                if not req.fly_through:
                    await asyncio.sleep(self.HOLD_TIME_SEC)

            goal_handle.succeed()
            return DroneTrajectory.Result(
                success=True,
                message=self._status("OK_TRAJECTORY_COMPLETE", "Trajectory complete"),
            )
        finally:
            self._release_goal()


def main():
    rclpy.init()
    node = DroneMCPBridge()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
