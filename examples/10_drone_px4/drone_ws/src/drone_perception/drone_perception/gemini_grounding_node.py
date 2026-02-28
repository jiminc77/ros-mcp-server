import json
import os
import threading
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from drone_interfaces.action import DronePerception
from rclpy.action import ActionServer
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener

from drone_perception.config import load_perception_config
from drone_perception.gemini_client import GeminiClient
from drone_perception.projection import ProjectionEngine
from drone_perception.runtime import CancelToken, log_phase
from drone_perception.state_machine import build_status_payload, initial_idle_payload


class GeminiGroundingNode(Node):
    SOURCE = "gemini_grounding"

    def __init__(self):
        super().__init__("gemini_grounding")
        self._callback_group = ReentrantCallbackGroup()

        self.declare_parameter("color_topic_raw", "/camera/camera/color/image_raw")
        self.declare_parameter("color_rotated_topic", "/drone_perception/color/image_rotated")
        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/camera/color/camera_info")
        self.declare_parameter("result_topic", "/drone_perception/object_result")
        self.declare_parameter("detect_action_name", "drone_perception/detect_object")

        color_topic_raw = str(self.get_parameter("color_topic_raw").value)
        color_rotated_topic = str(self.get_parameter("color_rotated_topic").value)
        depth_topic = str(self.get_parameter("depth_topic").value)
        camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        result_topic = str(self.get_parameter("result_topic").value)
        action_name = str(self.get_parameter("detect_action_name").value)

        self.config = load_perception_config(self)
        self._bridge = CvBridge()
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._gemini = GeminiClient(self.config, self._trace)
        self._projection = ProjectionEngine(self.config, self._tf_buffer, self._trace)

        self._result_pub = self.create_publisher(String, result_topic, 10)
        self._rotated_image_pub = self.create_publisher(Image, color_rotated_topic, qos_profile_sensor_data)

        self._state_lock = threading.Lock()
        self._goal_lock = threading.Lock()
        self._active_goal_id = ""
        self._latest_rotated = None
        self._latest_stamp_sec = 0
        self._latest_stamp_nanosec = 0
        self._depth_history = []
        self._camera_info = None
        self._generation = 0
        self._last_result = initial_idle_payload(source=self.SOURCE)

        self._action_detect = ActionServer(
            self,
            DronePerception,
            action_name,
            self.execute_detect,
            callback_group=self._callback_group,
        )

        self.create_subscription(Image, color_topic_raw, self._color_cb, qos_profile_sensor_data)
        self.create_subscription(Image, depth_topic, self._depth_cb, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, camera_info_topic, self._camera_info_cb, qos_profile_sensor_data)
        self.create_timer(self.config.status_heartbeat_sec, self._heartbeat_cb)

        log_phase(
            self,
            "startup",
            detail=(
                f"color={color_topic_raw} depth={depth_topic} "
                f"result={result_topic} action={action_name}"
            ),
        )
        self._publish_result(self._last_result)

    def _trace(self, message: str) -> None:
        if self.config.debug_trace:
            self.get_logger().info(f"[trace] {message}")

    def _color_cb(self, msg: Image) -> None:
        try:
            image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            if self.config.rotate_180:
                image = cv2.rotate(image, cv2.ROTATE_180)
            rotated_msg = self._bridge.cv2_to_imgmsg(image, encoding="bgr8")
            rotated_msg.header = msg.header
            self._rotated_image_pub.publish(rotated_msg)
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode/rotate/publish color image: {exc}")
            return

        with self._state_lock:
            self._latest_rotated = image
            self._latest_stamp_sec = int(msg.header.stamp.sec)
            self._latest_stamp_nanosec = int(msg.header.stamp.nanosec)

    def _depth_cb(self, msg: Image) -> None:
        try:
            depth = self._bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode depth image: {exc}")
            return

        stamp_ns = int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)
        with self._state_lock:
            self._depth_history.append((depth, msg.encoding, stamp_ns))
            if len(self._depth_history) > self.config.max_depth_history_size:
                self._depth_history = self._depth_history[-self.config.max_depth_history_size :]

    def _camera_info_cb(self, msg: CameraInfo) -> None:
        with self._state_lock:
            self._camera_info = msg

    def _heartbeat_cb(self) -> None:
        with self._state_lock:
            payload = dict(self._last_result)
        self._publish_json(self._result_pub, payload)

    def _claim_goal(self, goal_id: str) -> tuple[bool, str]:
        if not self._goal_lock.acquire(blocking=False):
            return False, self._active_goal_id or "unknown"
        self._active_goal_id = goal_id
        return True, ""

    def _release_goal(self) -> None:
        self._active_goal_id = ""
        self._goal_lock.release()

    def _next_generation(self) -> int:
        with self._state_lock:
            self._generation += 1
            return self._generation

    def _snapshot_inputs(self):
        with self._state_lock:
            image = None if self._latest_rotated is None else self._latest_rotated.copy()
            stamp_sec = self._latest_stamp_sec
            stamp_nanosec = self._latest_stamp_nanosec
            depth_history = list(self._depth_history)
            camera_info = self._camera_info
        return image, stamp_sec, stamp_nanosec, depth_history, camera_info

    @staticmethod
    def _extract_goal_id(goal_handle) -> str:
        goal_id = getattr(goal_handle, "goal_id", None)
        raw_uuid = getattr(goal_id, "uuid", None)
        if raw_uuid is not None:
            try:
                return bytes(int(v) & 0xFF for v in raw_uuid).hex()
            except Exception:
                pass
        return f"goal_{id(goal_handle):x}"

    def _publish_json(self, publisher, payload: dict) -> None:
        try:
            encoded = json.dumps(payload, separators=(",", ":"))
        except Exception as exc:
            self.get_logger().warn(f"Failed to encode JSON payload: {exc}")
            return
        msg = String()
        msg.data = encoded
        publisher.publish(msg)

    def _publish_result(self, payload: dict) -> None:
        data = dict(payload)
        data.setdefault("source", self.SOURCE)
        with self._state_lock:
            self._last_result = dict(data)
        self._publish_json(self._result_pub, data)

    def _build_error_payload(
        self,
        *,
        query: str,
        generation: int,
        code: str,
        message: str,
        extra: dict | None = None,
    ) -> dict:
        return build_status_payload(
            query=query,
            generation=generation,
            status="error",
            status_code=code,
            status_message=message,
            source=self.SOURCE,
            extra=extra,
        )

    @staticmethod
    def _to_action_result(payload: dict, success: bool) -> DronePerception.Result:
        result = DronePerception.Result()
        result.success = bool(success)
        result.message = json.dumps(payload, separators=(",", ":"))
        return result

    @staticmethod
    def _publish_feedback(
        goal_handle,
        *,
        generation: int,
        status: str,
        status_code: str,
        status_message: str,
    ) -> None:
        feedback = DronePerception.Feedback()
        feedback.generation = int(generation)
        feedback.status = status
        feedback.status_code = status_code
        feedback.status_message = status_message
        goal_handle.publish_feedback(feedback)

    async def _detect_once(
        self,
        *,
        query: str,
        generation: int,
        image,
        stamp_sec: int,
        stamp_nanosec: int,
        depth_frame,
        depth_encoding: str,
        camera_info: CameraInfo,
        cancel_token: CancelToken,
    ) -> dict:
        api_key = os.environ.get(self.config.gemini_api_key_env, "").strip()
        if not api_key:
            return self._build_error_payload(
                query=query,
                generation=generation,
                code="E_GEMINI_API_KEY",
                message=f"{self.config.gemini_api_key_env} is not set",
                extra={"image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)}},
            )

        detection = await self._gemini.detect_bbox_and_caption(
            api_key=api_key,
            query=query,
            image=image,
            cancel_token=cancel_token,
        )
        if cancel_token.canceled:
            return self._build_error_payload(
                query=query,
                generation=generation,
                code="E_CANCELED",
                message="Detection canceled",
            )

        if not detection.get("ok", False):
            return self._build_error_payload(
                query=query,
                generation=generation,
                code="E_DETECTION",
                message=str(detection.get("error", "Detection failed")),
                extra={"image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)}},
            )

        confidence = float(detection.get("confidence", 0.0))
        if confidence < self.config.default_min_confidence:
            return self._build_error_payload(
                query=query,
                generation=generation,
                code="E_LOW_CONFIDENCE",
                message=(
                    "Detection confidence too low "
                    f"({confidence:.2f} < {self.config.default_min_confidence:.2f})"
                ),
                extra={
                    "image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)},
                    "detection": {"bbox": detection.get("bbox")},
                },
            )

        projected = self._projection.project_rotated_bbox_to_map(
            bbox=detection["bbox"],
            depth_frame=depth_frame,
            depth_encoding=depth_encoding,
            camera_info=camera_info,
            image_stamp_sec=stamp_sec,
            image_stamp_nanosec=stamp_nanosec,
        )
        if not projected.get("ok", False):
            return self._build_error_payload(
                query=query,
                generation=generation,
                code=str(projected.get("code", "E_PROJECTION")),
                message=str(projected.get("message", "Projection failed")),
                extra={
                    "image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)},
                    "detection": {"bbox": detection.get("bbox")},
                },
            )

        object_map = projected["object_map"]
        return build_status_payload(
            query=query,
            generation=generation,
            status="success",
            status_code="OK",
            status_message="Detection/depth/position ready",
            source=self.SOURCE,
            extra={
                "image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)},
                "detection": {
                    "label": str(detection.get("label", query)),
                    "confidence": float(detection.get("confidence", 0.0)),
                    "bbox": detection.get("bbox"),
                },
                "caption": str(detection.get("caption", "")),
                "depth_m": float(projected["depth_m"]),
                "object_map": object_map,
                "representative_pixel": projected["representative_pixel"],
            },
        )

    async def execute_detect(self, goal_handle):
        goal_id = self._extract_goal_id(goal_handle)
        claimed, active_goal_id = self._claim_goal(goal_id)
        if not claimed:
            goal_handle.abort()
            payload = self._build_error_payload(
                query="",
                generation=0,
                code="E_GOAL_BUSY",
                message=f"Another goal is already running ({active_goal_id})",
            )
            return self._to_action_result(payload, False)

        started = time.monotonic()
        token = CancelToken()
        try:
            query = goal_handle.request.query.strip()
            generation = self._next_generation()
            log_phase(self, "detect_start", generation=generation, goal_id=goal_id, detail=query)

            if not query:
                goal_handle.abort()
                payload = self._build_error_payload(
                    query="",
                    generation=generation,
                    code="E_INVALID_REQUEST",
                    message="query must not be empty",
                )
                self._publish_result(payload)
                return self._to_action_result(payload, False)

            if goal_handle.is_cancel_requested:
                token.cancel()
                goal_handle.canceled()
                payload = self._build_error_payload(
                    query=query,
                    generation=generation,
                    code="E_CANCELED",
                    message="Detection canceled",
                )
                self._publish_result(payload)
                return self._to_action_result(payload, False)

            image, stamp_sec, stamp_nanosec, depth_history, camera_info = self._snapshot_inputs()
            if image is None:
                goal_handle.abort()
                payload = self._build_error_payload(
                    query=query,
                    generation=generation,
                    code="E_NO_IMAGE",
                    message="No image available yet",
                )
                self._publish_result(payload)
                return self._to_action_result(payload, False)

            snapshot = self._projection.snapshot_inputs(
                depth_history=depth_history,
                camera_info=camera_info,
                image_stamp_sec=stamp_sec,
                image_stamp_nanosec=stamp_nanosec,
            )
            if not snapshot.get("ok", False):
                goal_handle.abort()
                payload = self._build_error_payload(
                    query=query,
                    generation=generation,
                    code=str(snapshot.get("code", "E_DATA_NOT_READY")),
                    message=str(snapshot.get("message", "Depth/CameraInfo data is not ready yet")),
                    extra={"image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)}},
                )
                self._publish_result(payload)
                return self._to_action_result(payload, False)

            running_payload = build_status_payload(
                query=query,
                generation=generation,
                status="running",
                status_code="RUNNING",
                status_message="Vision grounding in progress",
                source=self.SOURCE,
                extra={"image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)}},
            )
            self._publish_result(running_payload)
            self._publish_feedback(
                goal_handle,
                generation=generation,
                status="running",
                status_code="RUNNING",
                status_message="Vision grounding in progress",
            )

            payload = await self._detect_once(
                query=query,
                generation=generation,
                image=image,
                stamp_sec=stamp_sec,
                stamp_nanosec=stamp_nanosec,
                depth_frame=snapshot["depth_frame"],
                depth_encoding=snapshot["depth_encoding"],
                camera_info=snapshot["camera_info"],
                cancel_token=token,
            )

            if goal_handle.is_cancel_requested:
                token.cancel()
            if token.canceled:
                goal_handle.canceled()
                canceled_payload = self._build_error_payload(
                    query=query,
                    generation=generation,
                    code="E_CANCELED",
                    message="Detection canceled",
                )
                self._publish_result(canceled_payload)
                return self._to_action_result(canceled_payload, False)

            self._publish_result(payload)
            self._publish_feedback(
                goal_handle,
                generation=generation,
                status=str(payload.get("status", "error")),
                status_code=str(payload.get("status_code", "E_UNKNOWN")),
                status_message=str(payload.get("status_message", "Detection finished")),
            )

            is_success = payload.get("status") == "success"
            if is_success:
                goal_handle.succeed()
            else:
                goal_handle.abort()
            log_phase(
                self,
                "detect_end",
                generation=generation,
                goal_id=goal_id,
                detail=f"success={is_success} elapsed={time.monotonic() - started:.3f}s",
            )
            return self._to_action_result(payload, is_success)
        except Exception as exc:
            goal_handle.abort()
            payload = self._build_error_payload(
                query="",
                generation=0,
                code="E_INTERNAL",
                message=f"Unhandled exception: {type(exc).__name__}: {exc}",
            )
            self._publish_result(payload)
            log_phase(
                self,
                "detect_exception",
                goal_id=goal_id,
                level="error",
                detail=f"{type(exc).__name__}: {exc}",
            )
            return self._to_action_result(payload, False)
        finally:
            self._release_goal()


def main() -> None:
    rclpy.init()
    node = GeminiGroundingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
