import threading
from typing import Sequence

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from drone_interfaces.srv import GetObject3D
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener


class ObjectGroundingNode(Node):
    def __init__(self):
        super().__init__("object_grounding")

        self.declare_parameter("color_topic", "/camera/camera/color/image_raw")
        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/camera/color/camera_info")
        self.declare_parameter("camera_frame", "")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("min_contour_area", 800.0)
        self.declare_parameter("depth_window_size", 5)

        color_topic = self.get_parameter("color_topic").get_parameter_value().string_value
        depth_topic = self.get_parameter("depth_topic").get_parameter_value().string_value
        camera_info_topic = self.get_parameter("camera_info_topic").get_parameter_value().string_value

        self.bridge = CvBridge()
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self._lock = threading.Lock()
        self._latest_color: np.ndarray | None = None
        self._latest_depth: np.ndarray | None = None
        self._latest_depth_encoding = ""
        self._latest_camera_info: CameraInfo | None = None

        self.create_subscription(Image, color_topic, self._color_cb, qos_profile_sensor_data)
        self.create_subscription(Image, depth_topic, self._depth_cb, qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, camera_info_topic, self._camera_info_cb, qos_profile_sensor_data
        )

        self.create_service(GetObject3D, "/drone_perception/get_object_3d", self._handle_get_object)
        self.get_logger().info("Object grounding service ready: /drone_perception/get_object_3d")

    def _color_cb(self, msg: Image) -> None:
        try:
            cv_img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode color image: {exc}")
            return

        with self._lock:
            self._latest_color = cv_img

    def _depth_cb(self, msg: Image) -> None:
        try:
            cv_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode depth image: {exc}")
            return

        with self._lock:
            self._latest_depth = cv_depth
            self._latest_depth_encoding = msg.encoding

    def _camera_info_cb(self, msg: CameraInfo) -> None:
        with self._lock:
            self._latest_camera_info = msg

    @staticmethod
    def _hsv_ranges_for_color(color: str) -> list[tuple[np.ndarray, np.ndarray]]:
        table: dict[str, list[tuple[Sequence[int], Sequence[int]]]] = {
            "red": [([0, 120, 80], [10, 255, 255]), ([170, 120, 80], [180, 255, 255])],
            "green": [([35, 80, 60], [90, 255, 255])],
            "blue": [([90, 80, 60], [130, 255, 255])],
            "yellow": [([20, 100, 100], [35, 255, 255])],
            "orange": [([10, 120, 80], [20, 255, 255])],
        }
        ranges = table.get(color.lower(), [])
        return [(np.array(low, dtype=np.uint8), np.array(high, dtype=np.uint8)) for low, high in ranges]

    @staticmethod
    def _contour_matches_shape(contour, shape: str) -> bool:
        normalized = shape.strip().lower()
        if normalized in {"", "any", "object", "target"}:
            return True

        area = float(cv2.contourArea(contour))
        if area <= 0.0:
            return False

        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0.0:
            return False

        if normalized in {"box", "square", "rectangle"}:
            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            return len(approx) == 4 and cv2.isContourConvex(approx)

        if normalized in {"circle", "round"}:
            circularity = (4.0 * np.pi * area) / (perimeter * perimeter)
            return circularity > 0.72

        return True

    def _extract_depth_m(self, cx: int, cy: int, depth_img: np.ndarray, encoding: str) -> float | None:
        h, w = depth_img.shape[:2]
        window_size = max(1, int(self.get_parameter("depth_window_size").value))
        half = window_size // 2

        x0 = max(0, cx - half)
        x1 = min(w, cx + half + 1)
        y0 = max(0, cy - half)
        y1 = min(h, cy + half + 1)
        patch = depth_img[y0:y1, x0:x1]

        values = patch.astype(np.float32)
        values = values[np.isfinite(values) & (values > 0.0)]
        if values.size == 0:
            return None

        depth = float(np.median(values))
        enc = encoding.upper()
        if enc in {"16UC1", "MONO16"} or depth > 100.0:
            depth *= 0.001
        if depth <= 0.0:
            return None
        return depth

    @staticmethod
    def _rotate_vector_by_quat(
        vx: float, vy: float, vz: float, qx: float, qy: float, qz: float, qw: float
    ) -> tuple[float, float, float]:
        tx = 2.0 * (qy * vz - qz * vy)
        ty = 2.0 * (qz * vx - qx * vz)
        tz = 2.0 * (qx * vy - qy * vx)

        rx = vx + qw * tx + (qy * tz - qz * ty)
        ry = vy + qw * ty + (qz * tx - qx * tz)
        rz = vz + qw * tz + (qx * ty - qy * tx)
        return rx, ry, rz

    def _transform_to_map(
        self, x: float, y: float, z: float, source_frame: str
    ) -> tuple[float, float, float]:
        map_frame = self.get_parameter("map_frame").get_parameter_value().string_value
        if source_frame == map_frame:
            return x, y, z

        transform = self.tf_buffer.lookup_transform(
            map_frame,
            source_frame,
            Time(),
            timeout=Duration(seconds=0.2),
        )

        t = transform.transform.translation
        q = transform.transform.rotation
        rx, ry, rz = self._rotate_vector_by_quat(x, y, z, q.x, q.y, q.z, q.w)
        return rx + t.x, ry + t.y, rz + t.z

    def _handle_get_object(self, request: GetObject3D.Request, response: GetObject3D.Response):
        with self._lock:
            color = None if self._latest_color is None else self._latest_color.copy()
            depth = None if self._latest_depth is None else self._latest_depth.copy()
            depth_encoding = self._latest_depth_encoding
            camera_info = self._latest_camera_info

        if color is None or depth is None or camera_info is None:
            response.success = False
            response.message = "Color/Depth/CameraInfo data is not ready yet"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        color_name = request.color.strip().lower()
        ranges = self._hsv_ranges_for_color(color_name)
        if not ranges:
            response.success = False
            response.message = f"Unsupported color '{request.color}'"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for low, high in ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, low, high))

        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        min_area = float(self.get_parameter("min_contour_area").value)

        best_contour = None
        best_area = 0.0
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < min_area:
                continue
            if not self._contour_matches_shape(contour, request.shape):
                continue
            if area > best_area:
                best_area = area
                best_contour = contour

        if best_contour is None:
            response.success = False
            response.message = "No matching object found"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        moments = cv2.moments(best_contour)
        if moments["m00"] == 0.0:
            response.success = False
            response.message = "Object contour center is invalid"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        px = int(moments["m10"] / moments["m00"])
        py = int(moments["m01"] / moments["m00"])

        depth_m = self._extract_depth_m(px, py, depth, depth_encoding)
        if depth_m is None:
            response.success = False
            response.message = "No valid depth around detected object center"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        fx = float(camera_info.k[0])
        fy = float(camera_info.k[4])
        cx = float(camera_info.k[2])
        cy = float(camera_info.k[5])
        if fx == 0.0 or fy == 0.0:
            response.success = False
            response.message = "Camera intrinsics are invalid"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        x_cam = (px - cx) * depth_m / fx
        y_cam = (py - cy) * depth_m / fy
        z_cam = depth_m

        source_frame = camera_info.header.frame_id
        if not source_frame:
            source_frame = self.get_parameter("camera_frame").get_parameter_value().string_value
        if not source_frame:
            response.success = False
            response.message = "Camera frame is empty in CameraInfo and camera_frame parameter"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        try:
            x_map, y_map, z_map = self._transform_to_map(x_cam, y_cam, z_cam, source_frame)
        except TransformException as exc:
            response.success = False
            response.message = f"TF lookup failed ({source_frame} -> map): {exc}"
            response.frame_id = self.get_parameter("map_frame").value
            return response

        response.success = True
        response.message = f"Detected {color_name} {request.shape or 'object'}"
        response.position.x = float(x_map)
        response.position.y = float(y_map)
        response.position.z = float(z_map)
        response.confidence = float(min(1.0, best_area / (best_area + min_area)))
        response.frame_id = self.get_parameter("map_frame").value
        return response


def main():
    rclpy.init()
    node = ObjectGroundingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
