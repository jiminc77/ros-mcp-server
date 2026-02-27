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

from drone_controller.config import load_controller_config
from drone_controller.flight_prep import prepare_for_flight
from drone_controller.runtime import CancelToken, StatusEnvelope, extract_goal_id, log_phase
from drone_controller.trajectory_executor import execute_trajectory_goal


class DroneMCPBridge(Node):
    SOURCE = "drone_controller"

    def __init__(self):
        super().__init__("drone_mcp_bridge")
        self.callback_group = ReentrantCallbackGroup()
        self.config = load_controller_config(self)

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
        self._local_pos_param_configured = False
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
        self._active_goal_id = ""

        self.timer = self.create_timer(
            self.config.control_dt, self.timer_callback, callback_group=self.callback_group
        )
        log_phase(self, "startup", detail="Drone bridge online")

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
            log_phase(
                self,
                "pose_lock",
                detail=(
                    f"x={msg.pose.position.x:.2f} "
                    f"y={msg.pose.position.y:.2f} z={msg.pose.position.z:.2f}"
                ),
            )

    def timer_callback(self) -> None:
        self.ensure_local_position_tf_params()
        if not self.is_primed:
            return
        self.target_pose.header.stamp = self.get_clock().now().to_msg()
        self.local_pos_pub.publish(self.target_pose)

    def ensure_local_position_tf_params(self) -> None:
        if self._local_pos_param_configured or self._local_pos_param_pending:
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
            if not self._local_pos_param_configured:
                log_phase(self, "param_sync", detail="MAVROS local_position TF params set")
            self._local_pos_param_configured = True

    def _claim_goal(self, name: str, goal_id: str) -> tuple[bool, str]:
        if not self._goal_lock.acquire(blocking=False):
            active = self._active_goal_name or "another goal"
            active_id = self._active_goal_id or "unknown"
            return False, f"{active}({active_id})"
        self._active_goal_name = name
        self._active_goal_id = goal_id
        return True, ""

    def _release_goal(self) -> None:
        self._active_goal_name = ""
        self._active_goal_id = ""
        self._goal_lock.release()

    def _encode_result(
        self,
        *,
        status: str,
        status_code: str,
        status_message: str,
        goal_id: str,
        generation: int = 0,
    ) -> str:
        return StatusEnvelope(
            status=status,
            status_code=status_code,
            status_message=status_message,
            source=self.SOURCE,
            generation=generation,
            goal_id=goal_id,
        ).to_json()

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

    async def execute_takeoff(self, goal_handle):
        goal_id = extract_goal_id(goal_handle)
        claimed, active = self._claim_goal("takeoff", goal_id)
        if not claimed:
            goal_handle.abort()
            return DroneTakeoff.Result(
                success=False,
                message=self._encode_result(
                    status="error",
                    status_code="E_GOAL_BUSY",
                    status_message=f"{active} is already running",
                    goal_id=goal_id,
                ),
            )

        token = CancelToken()
        log_phase(self, "takeoff_start", goal_id=goal_id)
        try:
            target_altitude = float(goal_handle.request.target_altitude)
            if target_altitude <= 0.0:
                goal_handle.abort()
                return DroneTakeoff.Result(
                    success=False,
                    message=self._encode_result(
                        status="error",
                        status_code="E_INVALID_REQUEST",
                        status_message="target_altitude must be greater than 0",
                        goal_id=goal_id,
                    ),
                )
            if target_altitude > self.config.max_takeoff_altitude_m:
                goal_handle.abort()
                return DroneTakeoff.Result(
                    success=False,
                    message=self._encode_result(
                        status="error",
                        status_code="E_INVALID_REQUEST",
                        status_message=(
                            "target_altitude exceeds max_takeoff_altitude_m "
                            f"({target_altitude:.2f} > {self.config.max_takeoff_altitude_m:.2f})"
                        ),
                        goal_id=goal_id,
                    ),
                )

            ready, code, msg = await prepare_for_flight(self, token, goal_id)
            if not ready:
                goal_handle.abort()
                return DroneTakeoff.Result(
                    success=False,
                    message=self._encode_result(
                        status="error",
                        status_code=code,
                        status_message=msg,
                        goal_id=goal_id,
                    ),
                )

            self._set_target_pose(
                self.current_pose.pose.position.x,
                self.current_pose.pose.position.y,
                target_altitude,
            )

            feedback = DroneTakeoff.Feedback()
            feedback_period_sec = 0.1
            last_feedback_ts = 0.0
            start_time = time.monotonic()
            while rclpy.ok():
                if goal_handle.is_cancel_requested:
                    token.cancel()
                if token.canceled:
                    goal_handle.canceled()
                    return DroneTakeoff.Result(
                        success=False,
                        message=self._encode_result(
                            status="error",
                            status_code="E_CANCELED",
                            status_message="Takeoff canceled",
                            goal_id=goal_id,
                        ),
                    )

                current_z = float(self.current_pose.pose.position.z)
                error = abs(target_altitude - current_z)
                now = time.monotonic()
                if now - last_feedback_ts >= feedback_period_sec:
                    feedback.current_altitude = current_z
                    goal_handle.publish_feedback(feedback)
                    last_feedback_ts = now

                if error <= self.config.default_takeoff_tolerance_m:
                    goal_handle.succeed()
                    return DroneTakeoff.Result(
                        success=True,
                        message=self._encode_result(
                            status="success",
                            status_code="OK_TAKEOFF_COMPLETE",
                            status_message="Takeoff complete",
                            goal_id=goal_id,
                        ),
                    )

                if time.monotonic() - start_time > self.config.timeout_takeoff_sec:
                    goal_handle.abort()
                    return DroneTakeoff.Result(
                        success=False,
                        message=self._encode_result(
                            status="error",
                            status_code="E_TAKEOFF_TIMEOUT",
                            status_message="Takeoff timeout",
                            goal_id=goal_id,
                        ),
                    )

                token.sleep(self.config.control_dt)

            goal_handle.abort()
            return DroneTakeoff.Result(
                success=False,
                message=self._encode_result(
                    status="error",
                    status_code="E_ROS_SHUTDOWN",
                    status_message="ROS shutdown",
                    goal_id=goal_id,
                ),
            )
        except Exception as exc:
            log_phase(
                self,
                "takeoff_exception",
                goal_id=goal_id,
                level="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            goal_handle.abort()
            return DroneTakeoff.Result(
                success=False,
                message=self._encode_result(
                    status="error",
                    status_code="E_INTERNAL",
                    status_message=f"Unhandled exception: {type(exc).__name__}: {exc}",
                    goal_id=goal_id,
                ),
            )
        finally:
            log_phase(self, "takeoff_end", goal_id=goal_id)
            self._release_goal()

    async def execute_trajectory(self, goal_handle):
        goal_id = extract_goal_id(goal_handle)
        claimed, active = self._claim_goal("trajectory", goal_id)
        if not claimed:
            goal_handle.abort()
            return DroneTrajectory.Result(
                success=False,
                message=self._encode_result(
                    status="error",
                    status_code="E_GOAL_BUSY",
                    status_message=f"{active} is already running",
                    goal_id=goal_id,
                ),
            )

        token = CancelToken()
        log_phase(self, "trajectory_start", goal_id=goal_id)
        try:
            outcome = await execute_trajectory_goal(self, goal_handle, token, goal_id)
            return DroneTrajectory.Result(
                success=outcome.success,
                message=self._encode_result(
                    status=outcome.status,
                    status_code=outcome.status_code,
                    status_message=outcome.status_message,
                    goal_id=goal_id,
                ),
            )
        except Exception as exc:
            log_phase(
                self,
                "trajectory_exception",
                goal_id=goal_id,
                level="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            goal_handle.abort()
            return DroneTrajectory.Result(
                success=False,
                message=self._encode_result(
                    status="error",
                    status_code="E_INTERNAL",
                    status_message=f"Unhandled exception: {type(exc).__name__}: {exc}",
                    goal_id=goal_id,
                ),
            )
        finally:
            log_phase(self, "trajectory_end", goal_id=goal_id)
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
