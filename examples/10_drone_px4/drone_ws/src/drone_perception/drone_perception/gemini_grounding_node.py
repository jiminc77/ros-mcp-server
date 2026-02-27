import asyncio
import json
import os
import threading
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener

from drone_perception.config import load_perception_config
from drone_perception.gemini_client import GeminiClient
from drone_perception.projection import ProjectionEngine
from drone_perception.runtime import CancelToken, log_phase, status_detail
from drone_perception.state_machine import build_status_payload, initial_idle_payload


class GeminiGroundingNode(Node):
    SOURCE = "gemini_grounding"

    def __init__(self):
        super().__init__("gemini_grounding")

        self.declare_parameter("color_topic_raw", "/camera/camera/color/image_raw")
        self.declare_parameter("color_rotated_topic", "/drone_perception/color/image_rotated")
        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/camera/color/camera_info")
        self.declare_parameter("query_topic", "/drone_perception/object_query")
        self.declare_parameter("overlay_topic", "/drone_perception/ui_overlay")
        self.declare_parameter("result_topic", "/drone_perception/object_result")

        color_topic_raw = str(self.get_parameter("color_topic_raw").value)
        color_rotated_topic = str(self.get_parameter("color_rotated_topic").value)
        depth_topic = str(self.get_parameter("depth_topic").value)
        camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        query_topic = str(self.get_parameter("query_topic").value)
        overlay_topic = str(self.get_parameter("overlay_topic").value)
        result_topic = str(self.get_parameter("result_topic").value)

        self.config = load_perception_config(self)
        self._bridge = CvBridge()
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._gemini = GeminiClient(self.config, self._trace)
        self._projection = ProjectionEngine(self.config, self._tf_buffer, self._trace)

        self._overlay_pub = self.create_publisher(String, overlay_topic, 10)
        self._result_pub = self.create_publisher(String, result_topic, 10)
        self._rotated_image_pub = self.create_publisher(Image, color_rotated_topic, qos_profile_sensor_data)

        self._state_lock = threading.Lock()
        self._latest_rotated = None
        self._latest_stamp_sec = 0
        self._latest_stamp_nanosec = 0
        self._depth_history = []
        self._camera_info = None
        self._generation = 0
        self._last_result = initial_idle_payload(source=self.SOURCE)

        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()
        self._active_future = None
        self._active_token = None

        self.create_subscription(Image, color_topic_raw, self._color_cb, qos_profile_sensor_data)
        self.create_subscription(Image, depth_topic, self._depth_cb, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, camera_info_topic, self._camera_info_cb, qos_profile_sensor_data)
        self.create_subscription(String, query_topic, self._query_cb, 10)
        self.create_timer(self.config.status_heartbeat_sec, self._heartbeat_cb)

        log_phase(
            self,
            "startup",
            detail=f"color={color_topic_raw} depth={depth_topic} query={query_topic}",
        )
        self._publish_json(self._result_pub, self._last_result)

    def destroy_node(self):
        self._cancel_active_query()
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._loop_thread.is_alive():
            self._loop_thread.join(timeout=1.0)
        self._loop.close()
        return super().destroy_node()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

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

    def _query_cb(self, msg: String) -> None:
        query = msg.data.strip()
        with self._state_lock:
            self._generation += 1
            generation = self._generation
            image = None if self._latest_rotated is None else self._latest_rotated.copy()
            stamp_sec = self._latest_stamp_sec
            stamp_nanosec = self._latest_stamp_nanosec
            depth_history = list(self._depth_history)
            camera_info = self._camera_info

        log_phase(self, "query_received", generation=generation, detail=f"query={query!r}")
        self._cancel_active_query()

        if not query:
            self._publish_overlay(
                {
                    "query": "",
                    "generation": generation,
                    "status_code": "IDLE",
                    "status_message": "No active query",
                }
            )
            self._publish_result(
                build_status_payload(
                    query="",
                    generation=generation,
                    status="idle",
                    status_code="IDLE",
                    status_message="No active query",
                    source=self.SOURCE,
                )
            )
            return

        if image is None:
            self._publish_error(query, generation, "E_NO_IMAGE", "No image available yet")
            return

        snapshot = self._projection.snapshot_inputs(
            depth_history=depth_history,
            camera_info=camera_info,
            image_stamp_sec=stamp_sec,
            image_stamp_nanosec=stamp_nanosec,
        )
        if not snapshot.get("ok", False):
            self._publish_error(
                query,
                generation,
                str(snapshot.get("code", "E_DATA_NOT_READY")),
                str(snapshot.get("message", "Depth/CameraInfo data is not ready yet")),
                image_stamp_sec=stamp_sec,
                image_stamp_nanosec=stamp_nanosec,
            )
            return

        self._publish_overlay(
            {
                "query": query,
                "generation": generation,
                "status_code": "RUNNING",
                "status_message": "Vision grounding in progress",
            }
        )
        self._publish_result(
            build_status_payload(
                query=query,
                generation=generation,
                status="running",
                status_code="RUNNING",
                status_message="Vision grounding in progress",
                source=self.SOURCE,
                extra={
                    "image_stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)},
                },
            )
        )

        token = CancelToken()
        with self._state_lock:
            self._active_token = token
        self._active_future = asyncio.run_coroutine_threadsafe(
            self._process_query_async(
                query=query,
                generation=generation,
                rotated_image=image,
                image_stamp_sec=stamp_sec,
                image_stamp_nanosec=stamp_nanosec,
                depth_frame=snapshot["depth_frame"],
                depth_encoding=snapshot["depth_encoding"],
                camera_info=snapshot["camera_info"],
                token=token,
            ),
            self._loop,
        )

    def _cancel_active_query(self) -> None:
        with self._state_lock:
            token = self._active_token
            future = self._active_future
            self._active_token = None
            self._active_future = None
        if token is not None:
            token.cancel()
        if future is not None and not future.done():
            future.cancel()

    def _is_current_generation(self, generation: int) -> bool:
        with self._state_lock:
            return generation == self._generation

    async def _process_query_async(
        self,
        *,
        query: str,
        generation: int,
        rotated_image,
        image_stamp_sec: int,
        image_stamp_nanosec: int,
        depth_frame,
        depth_encoding: str,
        camera_info: CameraInfo,
        token: CancelToken,
    ) -> None:
        started = time.monotonic()
        log_phase(self, "query_process_start", generation=generation)
        if token.canceled or not self._is_current_generation(generation):
            return

        api_key = os.environ.get(self.config.gemini_api_key_env, "").strip()
        if not api_key:
            self._publish_error(
                query,
                generation,
                "E_GEMINI_API_KEY",
                f"{self.config.gemini_api_key_env} is not set",
                image_stamp_sec=image_stamp_sec,
                image_stamp_nanosec=image_stamp_nanosec,
            )
            return

        detection = await self._gemini.detect_bbox_and_caption(
            api_key=api_key,
            query=query,
            image=rotated_image,
            cancel_token=token,
        )
        if token.canceled or not self._is_current_generation(generation):
            return
        if not detection.get("ok", False):
            self._publish_error(
                query,
                generation,
                "E_DETECTION",
                str(detection.get("error", "Detection failed")),
                image_stamp_sec=image_stamp_sec,
                image_stamp_nanosec=image_stamp_nanosec,
            )
            return

        confidence = float(detection.get("confidence", 0.0))
        if confidence < self.config.default_min_confidence:
            self._publish_error(
                query,
                generation,
                "E_LOW_CONFIDENCE",
                (
                    "Detection confidence too low "
                    f"({confidence:.2f} < {self.config.default_min_confidence:.2f})"
                ),
                bbox=detection.get("bbox"),
                image_stamp_sec=image_stamp_sec,
                image_stamp_nanosec=image_stamp_nanosec,
            )
            return

        projected = self._projection.project_rotated_bbox_to_map(
            bbox=detection["bbox"],
            depth_frame=depth_frame,
            depth_encoding=depth_encoding,
            camera_info=camera_info,
            image_stamp_sec=image_stamp_sec,
            image_stamp_nanosec=image_stamp_nanosec,
        )
        if token.canceled or not self._is_current_generation(generation):
            return
        if not projected.get("ok", False):
            self._publish_error(
                query,
                generation,
                str(projected.get("code", "E_PROJECTION")),
                str(projected.get("message", "Projection failed")),
                bbox=detection.get("bbox"),
                image_stamp_sec=image_stamp_sec,
                image_stamp_nanosec=image_stamp_nanosec,
            )
            return

        object_map = projected["object_map"]
        overlay = {
            "query": query,
            "generation": int(generation),
            "label": str(detection.get("label", query)),
            "confidence": float(detection.get("confidence", 0.0)),
            "bbox": detection.get("bbox"),
            "caption": str(detection.get("caption", "")),
            "representative_pixel": projected["representative_pixel"],
            "depth_m": float(projected["depth_m"]),
            "object_map": object_map,
            "status_code": "OK",
            "status_message": "Detection/depth/position ready",
        }
        self._publish_overlay(overlay)

        result = build_status_payload(
            query=query,
            generation=generation,
            status="success",
            status_code="OK",
            status_message="Detection/depth/position ready",
            source=self.SOURCE,
            extra={
                "image_stamp": {"sec": int(image_stamp_sec), "nanosec": int(image_stamp_nanosec)},
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
        self._publish_result(result)
        log_phase(
            self,
            "query_process_success",
            generation=generation,
            detail=f"elapsed={time.monotonic() - started:.3f}s",
        )

    def _publish_json(self, publisher, payload: dict) -> None:
        try:
            encoded = json.dumps(payload, separators=(",", ":"))
        except Exception as exc:
            self.get_logger().warn(f"Failed to encode JSON payload: {exc}")
            return
        msg = String()
        msg.data = encoded
        publisher.publish(msg)

    def _publish_overlay(self, payload: dict) -> None:
        data = dict(payload)
        code = str(data.get("status_code", ""))
        message = str(data.get("status_message", ""))
        if code and message and "status_detail" not in data:
            data["status_detail"] = status_detail(code, message)
        data.setdefault("source", self.SOURCE)
        self._publish_json(self._overlay_pub, data)

    def _publish_result(self, payload: dict) -> None:
        data = dict(payload)
        data.setdefault("source", self.SOURCE)
        code = str(data.get("status_code", ""))
        message = str(data.get("status_message", ""))
        if code and message and "status_detail" not in data:
            data["status_detail"] = status_detail(code, message)
        with self._state_lock:
            self._last_result = dict(data)
        self._publish_json(self._result_pub, data)

    def _heartbeat_cb(self) -> None:
        with self._state_lock:
            payload = dict(self._last_result)
        self._publish_json(self._result_pub, payload)

    def _publish_error(
        self,
        query: str,
        generation: int,
        code: str,
        message: str,
        bbox: dict | None = None,
        image_stamp_sec: int = 0,
        image_stamp_nanosec: int = 0,
    ) -> None:
        overlay = {
            "query": query,
            "generation": int(generation),
            "status_code": code,
            "status_message": message,
        }
        if bbox is not None:
            overlay["bbox"] = bbox
        self._publish_overlay(overlay)

        extra = {}
        if bbox is not None:
            extra["detection"] = {"bbox": bbox}
        if image_stamp_sec > 0:
            extra["image_stamp"] = {"sec": int(image_stamp_sec), "nanosec": int(image_stamp_nanosec)}

        result = build_status_payload(
            query=query,
            generation=generation,
            status="error",
            status_code=code,
            status_message=message,
            source=self.SOURCE,
            extra=extra,
        )
        self._publish_result(result)
        log_phase(self, "query_process_error", generation=generation, level="warn", detail=result["status_detail"])


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
