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

    def local_cb(self, msg: PoseStamped) -> None:
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
        if not self.is_primed:
            return

        self.target_pose.header.stamp = self.get_clock().now().to_msg()
        self.target_pose.header.frame_id = "map"
        self.local_pos_pub.publish(self.target_pose)

    def _claim_goal(self, name: str) -> tuple[bool, str]:
        if not self._goal_lock.acquire(blocking=False):
            active = self._active_goal_name or "another goal"
            return False, f"Goal rejected: {active} is already running"
        self._active_goal_name = name
        return True, ""

    def _release_goal(self) -> None:
        self._active_goal_name = ""
        self._goal_lock.release()

    @staticmethod
    def _distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
        return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)

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

    async def prepare_for_flight(self) -> bool:
        if not self.current_state.connected:
            self.get_logger().error("FCU not connected")
            return False

        if not self.is_primed:
            self.get_logger().warn("Waiting for local position lock")
            return False

        if not self.mode_cli.wait_for_service(timeout_sec=1.0):
            self.get_logger().error("SetMode service unavailable")
            return False
        if not self.arm_cli.wait_for_service(timeout_sec=1.0):
            self.get_logger().error("Arming service unavailable")
            return False

        if self.current_state.mode != "OFFBOARD":
            mode_req = SetMode.Request(custom_mode="OFFBOARD")
            mode_resp = await self.mode_cli.call_async(mode_req)
            if not mode_resp or not mode_resp.mode_sent:
                self.get_logger().error("Failed to set OFFBOARD mode")
                return False
            await asyncio.sleep(0.5)

        if not self.current_state.armed:
            arm_req = CommandBool.Request(value=True)
            arm_resp = await self.arm_cli.call_async(arm_req)
            if not arm_resp or not arm_resp.success:
                self.get_logger().error("Failed to arm")
                return False

        return True

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
                    success=False, message="target_altitude must be greater than 0"
                )

            self.get_logger().info(f"Takeoff goal received: {target_altitude:.2f}m")
            if not await self.prepare_for_flight():
                goal_handle.abort()
                return DroneTakeoff.Result(success=False, message="Failed to arm/offboard")

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
                    return DroneTakeoff.Result(success=False, message="Canceled")

                current_z = float(self.current_pose.pose.position.z)
                error = abs(target_altitude - current_z)
                feedback.current_altitude = current_z
                goal_handle.publish_feedback(feedback)

                if error <= self.TAKEOFF_TOLERANCE_M:
                    goal_handle.succeed()
                    return DroneTakeoff.Result(success=True, message="Takeoff complete")

                if time.monotonic() - start_time > self.TAKEOFF_TIMEOUT_SEC:
                    goal_handle.abort()
                    return DroneTakeoff.Result(success=False, message="Takeoff timeout")

                await asyncio.sleep(0.1)

            goal_handle.abort()
            return DroneTakeoff.Result(success=False, message="ROS shutdown")
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
                return DroneTrajectory.Result(success=False, message="No trajectory points provided")

            self.get_logger().info(
                f"Trajectory goal received: {len(points)} points, fly_through={req.fly_through}"
            )
            if not await self.prepare_for_flight():
                goal_handle.abort()
                return DroneTrajectory.Result(success=False, message="Failed to arm/offboard")

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
                        return DroneTrajectory.Result(success=False, message="Canceled")

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
                    drone_dist_to_target = self._distance(current, target)

                    feedback.current_point_index = idx
                    feedback.distance_remaining = float(drone_dist_to_target)
                    goal_handle.publish_feedback(feedback)

                    if drone_dist_to_target <= tolerance:
                        break

                    if time.monotonic() - waypoint_start > self.WAYPOINT_TIMEOUT_SEC:
                        goal_handle.abort()
                        return DroneTrajectory.Result(
                            success=False,
                            message=f"Timeout while reaching waypoint {idx}",
                        )

                    await asyncio.sleep(self.CONTROL_DT)

                if not req.fly_through:
                    await asyncio.sleep(self.HOLD_TIME_SEC)

            goal_handle.succeed()
            return DroneTrajectory.Result(success=True, message="Trajectory complete")
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
