import base64
import copy
import json
import os
import re
import threading
import time
from urllib import error as url_error
from urllib import request as url_request

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener


class GeminiGroundingNode(Node):
    def __init__(self):
        super().__init__("gemini_grounding")

        self.declare_parameter("color_topic_raw", "/camera/camera/color/image_raw")
        self.declare_parameter("color_rotated_topic", "/drone_perception/color/image_rotated")
        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/camera/color/camera_info")
        self.declare_parameter("query_topic", "/drone_perception/object_query")
        self.declare_parameter("overlay_topic", "/drone_perception/ui_overlay")
        self.declare_parameter("result_topic", "/drone_perception/object_result")

        self.declare_parameter("rotate_180", True)
        self.declare_parameter("depth_history_size", 30)
        self.declare_parameter("max_sync_gap_sec", 0.10)
        self.declare_parameter("patch_size", 7)
        self.declare_parameter("min_depth_m", 0.15)
        self.declare_parameter("max_depth_m", 8.0)
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("camera_frame", "")

        self.declare_parameter("gemini_model", "gemini-3.0-flash")
        self.declare_parameter("gemini_api_key_env", "GEMINI_API_KEY")
        self.declare_parameter("gemini_temperature", 0.1)
        self.declare_parameter("request_timeout_sec", 15.0)
        self.declare_parameter("min_confidence", 0.5)
        self.declare_parameter("publish_retries", 12)
        self.declare_parameter("publish_retry_interval_sec", 0.2)

        color_topic_raw = str(self.get_parameter("color_topic_raw").value)
        color_rotated_topic = str(self.get_parameter("color_rotated_topic").value)
        depth_topic = str(self.get_parameter("depth_topic"ㄴ).value)
        camera_info_topic = str(self.get_parameter("camera_info_topic").value)
        query_topic = str(self.get_parameter("query_topic").value)
        overlay_topic = str(self.get_parameter("overlay_topic").value)
        result_topic = str(self.get_parameter("result_topic").value)

        self._bridge = CvBridge()
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        self._overlay_pub = self.create_publisher(String, overlay_topic, 10)
        self._result_pub = self.create_publisher(String, result_topic, 10)
        self._rotated_image_pub = self.create_publisher(Image, color_rotated_topic, qos_profile_sensor_data)

        self._state_lock = threading.Lock()
        self._latest_rotated = None
        self._latest_stamp_sec = 0
        self._latest_stamp_nanosec = 0
        self._depth_history = []
        self._depth_history_limit = max(1, int(self.get_parameter("depth_history_size").value))
        self._camera_info = None
        self._generation = 0

        self.create_subscription(Image, color_topic_raw, self._color_cb, qos_profile_sensor_data)
        self.create_subscription(Image, depth_topic, self._depth_cb, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, camera_info_topic, self._camera_info_cb, qos_profile_sensor_data)
        self.create_subscription(String, query_topic, self._query_cb, 10)

        self.get_logger().info(
            "Gemini grounding ready: color=%s depth=%s query=%s"
            % (color_topic_raw, depth_topic, query_topic)
        )

    def _color_cb(self, msg: Image) -> None:
        try:
            image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            if bool(self.get_parameter("rotate_180").value):
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
            if len(self._depth_history) > self._depth_history_limit:
                self._depth_history = self._depth_history[-self._depth_history_limit :]

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

        if not query:
            self._publish_overlay({"status_code": "IDLE", "status_message": "No active query"})
            return

        if image is None:
            self._publish_error(query, generation, "E_NO_IMAGE", "No image available yet")
            return

        snap = self._snapshot_projection_inputs(stamp_sec, stamp_nanosec)
        if not snap["ok"]:
            self._publish_error(
                query,
                generation,
                str(snap["code"]),
                str(snap["message"]),
                image_stamp_sec=stamp_sec,
                image_stamp_nanosec=stamp_nanosec,
            )
            return

        self._publish_overlay({"label": query, "status_code": "RUNNING", "status_message": "Processing"})
        self._publish_result(
            {
                "query": query,
                "generation": int(generation),
                "status": "running",
                "status_code": "RUNNING",
                "status_message": "Vision grounding in progress",
                "image_stamp": {
                    "sec": int(stamp_sec),
                    "nanosec": int(stamp_nanosec),
                },
            }
        )

        threading.Thread(
            target=self._process_query,
            args=(
                query,
                generation,
                image,
                stamp_sec,
                stamp_nanosec,
                snap["depth_frame"],
                snap["depth_encoding"],
                snap["camera_info"],
            ),
            daemon=True,
        ).start()

    def _process_query(
        self,
        query: str,
        generation: int,
        rotated_image,
        image_stamp_sec: int,
        image_stamp_nanosec: int,
        depth_frame,
        depth_encoding: str,
        camera_info: CameraInfo,
    ) -> None:
        try:
            api_key_env = str(self.get_parameter("gemini_api_key_env").value)
            api_key = os.environ.get(api_key_env, "").strip()
            if not api_key:
                if self._is_current(generation):
                    self._publish_error(
                        query,
                        generation,
                        "E_GEMINI_API_KEY",
                        f"{api_key_env} is not set",
                        image_stamp_sec,
                        image_stamp_nanosec,
                    )
                return

            detection = self._gemini_detect_bbox_and_caption(api_key, query, rotated_image)
            if not self._is_current(generation):
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
            min_confidence = float(self.get_parameter("min_confidence").value)
            if confidence < min_confidence:
                self._publish_error(
                    query,
                    generation,
                    "E_LOW_CONFIDENCE",
                    f"Detection confidence too low ({confidence:.2f} < {min_confidence:.2f})",
                    bbox=detection.get("bbox"),
                    image_stamp_sec=image_stamp_sec,
                    image_stamp_nanosec=image_stamp_nanosec,
                )
                return

            projected = self._project_rotated_bbox_to_map(
                detection["bbox"],
                depth_frame,
                depth_encoding,
                camera_info,
            )
            if not self._is_current(generation):
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

            self._publish_result(
                {
                    "query": query,
                    "generation": int(generation),
                    "status": "success",
                    "status_code": "OK",
                    "status_message": "Detection/depth/position ready",
                    "image_stamp": {
                        "sec": int(image_stamp_sec),
                        "nanosec": int(image_stamp_nanosec),
                    },
                    "detection": {
                        "label": str(detection.get("label", query)),
                        "confidence": float(detection.get("confidence", 0.0)),
                        "bbox": detection.get("bbox"),
                    },
                    "caption": str(detection.get("caption", "")),
                    "depth_m": float(projected["depth_m"]),
                    "object_map": object_map,
                    "representative_pixel": projected["representative_pixel"],
                }
            )
        except Exception as exc:
            if self._is_current(generation):
                self._publish_error(
                    query,
                    generation,
                    "E_INTERNAL",
                    str(exc),
                    image_stamp_sec=image_stamp_sec,
                    image_stamp_nanosec=image_stamp_nanosec,
                )

    def _project_rotated_bbox_to_map(
        self,
        bbox: dict,
        depth_frame,
        depth_encoding: str,
        camera_info: CameraInfo,
    ) -> dict:
        h, w = depth_frame.shape[:2]
        x0_rot, y0_rot, x1_rot, y1_rot = self._clamp_bbox(
            int(bbox["x_min"]),
            int(bbox["y_min"]),
            int(bbox["x_max"]),
            int(bbox["y_max"]),
            w,
            h,
        )

        if bool(self.get_parameter("rotate_180").value):
            x0_raw, y0_raw, x1_raw, y1_raw = self._bbox_rotated_to_raw(x0_rot, y0_rot, x1_rot, y1_rot, w, h)
            x0_raw, y0_raw, x1_raw, y1_raw = self._clamp_bbox(x0_raw, y0_raw, x1_raw, y1_raw, w, h)
        else:
            x0_raw, y0_raw, x1_raw, y1_raw = x0_rot, y0_rot, x1_rot, y1_rot

        center_x = (x0_raw + x1_raw) // 2
        center_y = (y0_raw + y1_raw) // 2

        patch_size = max(3, int(self.get_parameter("patch_size").value))
        if patch_size % 2 == 0:
            patch_size += 1

        depth_m, valid_ratio = self._depth_from_center_patch(
            depth_frame,
            depth_encoding,
            center_x,
            center_y,
            patch_size,
            float(self.get_parameter("min_depth_m").value),
            float(self.get_parameter("max_depth_m").value),
        )
        if depth_m is None:
            return {
                "ok": False,
                "code": "E_DEPTH_INVALID",
                "message": "No valid depth in center patch",
                "confidence": float(valid_ratio),
            }

        fx = float(camera_info.k[0])
        fy = float(camera_info.k[4])
        cx = float(camera_info.k[2])
        cy = float(camera_info.k[5])
        if fx == 0.0 or fy == 0.0:
            return {
                "ok": False,
                "code": "E_CAMERA_INTRINSICS",
                "message": "Camera intrinsics are invalid",
            }

        x_cam = (float(center_x) - cx) * depth_m / fx
        y_cam = (float(center_y) - cy) * depth_m / fy
        z_cam = depth_m

        source_frame = camera_info.header.frame_id.strip()
        if not source_frame:
            source_frame = str(self.get_parameter("camera_frame").value).strip()
        if not source_frame:
            return {
                "ok": False,
                "code": "E_CAMERA_FRAME",
                "message": "Camera frame is empty in CameraInfo and camera_frame parameter",
            }

        try:
            x_map, y_map, z_map = self._transform_to_map(x_cam, y_cam, z_cam, source_frame)
        except TransformException as exc:
            map_frame = str(self.get_parameter("map_frame").value)
            return {
                "ok": False,
                "code": "E_TF_LOOKUP",
                "message": f"TF lookup failed ({source_frame} -> {map_frame}): {exc}",
            }

        if bool(self.get_parameter("rotate_180").value):
            rep_x, rep_y = self._pixel_raw_to_rotated(center_x, center_y, w, h)
        else:
            rep_x, rep_y = center_x, center_y

        map_frame = str(self.get_parameter("map_frame").value)

        return {
            "ok": True,
            "depth_m": float(depth_m),
            "confidence": float(valid_ratio),
            "representative_pixel": {"x": int(rep_x), "y": int(rep_y)},
            "object_map": {
                "x": float(x_map),
                "y": float(y_map),
                "z": float(z_map),
                "frame_id": map_frame,
            },
        }

    def _snapshot_projection_inputs(self, image_stamp_sec: int, image_stamp_nanosec: int) -> dict:
        target_ns = int(image_stamp_sec) * 1_000_000_000 + int(image_stamp_nanosec)
        with self._state_lock:
            if not self._depth_history or self._camera_info is None:
                return {
                    "ok": False,
                    "code": "E_DATA_NOT_READY",
                    "message": "Depth/CameraInfo data is not ready yet",
                }

            depth, encoding, stamp_ns = min(
                self._depth_history,
                key=lambda item: abs(item[2] - target_ns),
            )
            camera_info = copy.deepcopy(self._camera_info)

        gap_sec = abs(stamp_ns - target_ns) / 1_000_000_000.0 if target_ns > 0 else 0.0
        max_sync_gap = float(self.get_parameter("max_sync_gap_sec").value)
        if target_ns > 0 and gap_sec > max_sync_gap:
            return {
                "ok": False,
                "code": "E_TIME_SYNC",
                "message": f"No depth frame near image stamp (gap={gap_sec:.3f}s, max={max_sync_gap:.3f}s)",
            }

        return {
            "ok": True,
            "depth_frame": depth.copy(),
            "depth_encoding": str(encoding),
            "camera_info": camera_info,
        }

    def _depth_from_center_patch(
        self,
        depth_img,
        encoding: str,
        center_x: int,
        center_y: int,
        patch_size: int,
        min_depth_m: float,
        max_depth_m: float,
    ) -> tuple[float | None, float]:
        h, w = depth_img.shape[:2]
        half = patch_size // 2
        x0 = max(0, center_x - half)
        x1 = min(w, center_x + half + 1)
        y0 = max(0, center_y - half)
        y1 = min(h, center_y + half + 1)

        if x0 >= x1 or y0 >= y1:
            return None, 0.0

        patch = depth_img[y0:y1, x0:x1].astype(np.float32)
        if encoding.upper() in {"16UC1", "MONO16"}:
            patch *= 0.001

        valid = patch[np.isfinite(patch)]
        valid = valid[(valid > 0.0) & (valid >= min_depth_m) & (valid <= max_depth_m)]

        total = patch.size
        valid_ratio = float(valid.size) / float(total) if total > 0 else 0.0
        if valid.size == 0:
            return None, valid_ratio

        return float(np.median(valid)), valid_ratio

    def _transform_to_map(
        self,
        x: float,
        y: float,
        z: float,
        source_frame: str,
    ) -> tuple[float, float, float]:
        map_frame = str(self.get_parameter("map_frame").value)
        if source_frame == map_frame:
            return x, y, z

        transform = self._tf_buffer.lookup_transform(
            map_frame,
            source_frame,
            Time(),
            timeout=Duration(seconds=0.2),
        )
        t = transform.transform.translation
        q = transform.transform.rotation
        rx, ry, rz = self._rotate_vector_by_quat(x, y, z, q.x, q.y, q.z, q.w)
        return rx + t.x, ry + t.y, rz + t.z

    @staticmethod
    def _rotate_vector_by_quat(
        vx: float,
        vy: float,
        vz: float,
        qx: float,
        qy: float,
        qz: float,
        qw: float,
    ) -> tuple[float, float, float]:
        tx = 2.0 * (qy * vz - qz * vy)
        ty = 2.0 * (qz * vx - qx * vz)
        tz = 2.0 * (qx * vy - qy * vx)
        rx = vx + qw * tx + (qy * tz - qz * ty)
        ry = vy + qw * ty + (qz * tx - qx * tz)
        rz = vz + qw * tz + (qx * ty - qy * tx)
        return rx, ry, rz

    @staticmethod
    def _clamp_bbox(
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        width: int,
        height: int,
    ) -> tuple[int, int, int, int]:
        x0 = max(0, min(min(x_min, x_max), width - 1))
        y0 = max(0, min(min(y_min, y_max), height - 1))
        x1 = max(0, min(max(x_min, x_max), width - 1))
        y1 = max(0, min(max(y_min, y_max), height - 1))
        return x0, y0, x1, y1

    @staticmethod
    def _bbox_rotated_to_raw(
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        width: int,
        height: int,
    ) -> tuple[int, int, int, int]:
        raw_x_min = (width - 1) - x_max
        raw_x_max = (width - 1) - x_min
        raw_y_min = (height - 1) - y_max
        raw_y_max = (height - 1) - y_min
        return raw_x_min, raw_y_min, raw_x_max, raw_y_max

    @staticmethod
    def _pixel_raw_to_rotated(px: int, py: int, width: int, height: int) -> tuple[int, int]:
        return (width - 1) - px, (height - 1) - py

    def _publish_json(self, publisher, payload: dict) -> None:
        try:
            encoded = json.dumps(payload, separators=(",", ":"))
        except Exception as exc:
            self.get_logger().warn(f"Failed to encode JSON payload: {exc}")
            return

        retries = max(1, int(self.get_parameter("publish_retries").value))
        interval_sec = max(0.0, float(self.get_parameter("publish_retry_interval_sec").value))

        def _worker() -> None:
            for i in range(retries):
                msg = String()
                msg.data = encoded
                publisher.publish(msg)
                if i + 1 < retries and interval_sec > 0.0:
                    time.sleep(interval_sec)

        threading.Thread(target=_worker, daemon=True).start()

    def _publish_overlay(self, payload: dict) -> None:
        self._publish_json(self._overlay_pub, payload)

    def _publish_result(self, payload: dict) -> None:
        data = dict(payload)
        data["source"] = "gemini_grounding"
        self._publish_json(self._result_pub, data)

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
            "label": query,
            "status_code": code,
            "status_message": message,
        }
        if bbox is not None:
            overlay["bbox"] = bbox
        self._publish_overlay(overlay)

        result = {
            "query": query,
            "generation": int(generation),
            "status": "error",
            "status_code": code,
            "status_message": message,
        }
        if bbox is not None:
            result["detection"] = {"bbox": bbox}
        if image_stamp_sec > 0:
            result["image_stamp"] = {
                "sec": int(image_stamp_sec),
                "nanosec": int(image_stamp_nanosec),
            }
        self._publish_result(result)

    def _is_current(self, generation: int) -> bool:
        with self._state_lock:
            return generation == self._generation

    def _gemini_detect_bbox_and_caption(self, api_key: str, query: str, image) -> dict:
        ok, jpg = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return {"ok": False, "error": "Failed to encode image"}

        image_b64 = base64.b64encode(jpg.tobytes()).decode("ascii")
        h, w = image.shape[:2]

        model = str(self.get_parameter("gemini_model").value)
        timeout_sec = float(self.get_parameter("request_timeout_sec").value)
        temperature = float(self.get_parameter("gemini_temperature").value)

        prompt = (
            "You are a robotics vision grounding module. "
            "Detect one object for the query and return strict JSON. "
            f"Query: {query}. "
            f"Image width={w}, height={h}. "
            "Coordinates must be integer pixel coordinates in this exact image (top-left origin, x to right, y to bottom). "
            "Do not return normalized coordinates. "
            "If not found, set found=false and bbox to zeros."
        )

        schema = {
            "type": "OBJECT",
            "properties": {
                "found": {"type": "BOOLEAN"},
                "label": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
                "bbox": {
                    "type": "OBJECT",
                    "properties": {
                        "x_min": {"type": "INTEGER"},
                        "y_min": {"type": "INTEGER"},
                        "x_max": {"type": "INTEGER"},
                        "y_max": {"type": "INTEGER"},
                    },
                    "required": ["x_min", "y_min", "x_max", "y_max"],
                },
                "caption": {"type": "STRING"},
            },
            "required": ["found", "label", "confidence", "bbox", "caption"],
        }

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_b64,
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }

        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={api_key}"
        )
        req = url_request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with url_request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
        except url_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            return {"ok": False, "error": f"Gemini HTTP {exc.code}: {detail}"}
        except Exception as exc:
            return {"ok": False, "error": f"Gemini request failed: {exc}"}

        parsed = self._parse_response_json(raw)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "Gemini output is not a JSON object"}
        if not bool(parsed.get("found", False)):
            return {"ok": False, "error": "Target object not found"}

        bbox_obj = parsed.get("bbox")
        if not isinstance(bbox_obj, dict):
            return {"ok": False, "error": "bbox is missing"}

        try:
            x_min = int(bbox_obj["x_min"])
            y_min = int(bbox_obj["y_min"])
            x_max = int(bbox_obj["x_max"])
            y_max = int(bbox_obj["y_max"])
        except Exception:
            return {"ok": False, "error": "Invalid bbox fields"}

        if x_min > x_max:
            x_min, x_max = x_max, x_min
        if y_min > y_max:
            y_min, y_max = y_max, y_min

        x_min = max(0, min(x_min, w - 1))
        x_max = max(0, min(x_max, w - 1))
        y_min = max(0, min(y_min, h - 1))
        y_max = max(0, min(y_max, h - 1))
        if x_min >= x_max or y_min >= y_max:
            return {"ok": False, "error": "Degenerate bbox"}

        try:
            confidence = float(parsed.get("confidence", 0.0))
        except Exception:
            return {"ok": False, "error": "Invalid confidence field"}

        return {
            "ok": True,
            "label": str(parsed.get("label", query)),
            "confidence": confidence,
            "bbox": {
                "x_min": x_min,
                "y_min": y_min,
                "x_max": x_max,
                "y_max": y_max,
            },
            "caption": str(parsed.get("caption", "")),
        }

    def _parse_response_json(self, raw: str):
        try:
            response_json = json.loads(raw)
        except Exception:
            return None

        candidates = response_json.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        text_chunks = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_chunks.append(part["text"])

        text = "\n".join(text_chunks).strip()
        if not text:
            return None

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\\s*", "", text)
            text = re.sub(r"\\s*```$", "", text)

        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except Exception:
                return None


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
