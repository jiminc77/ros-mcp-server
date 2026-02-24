import threading

import numpy as np
import rclpy
from cv_bridge import CvBridge
from drone_interfaces.srv import ProjectPixelTo3D
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener


class PixelProjectionNode(Node):
    def __init__(self):
        super().__init__("pixel_projection")

        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/camera/color/camera_info")
        self.declare_parameter("camera_frame", "")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("default_window_size", 5)
        self.declare_parameter("min_valid_ratio", 0.25)

        depth_topic = self.get_parameter("depth_topic").get_parameter_value().string_value
        camera_info_topic = self.get_parameter("camera_info_topic").get_parameter_value().string_value

        self.bridge = CvBridge()
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self._lock = threading.Lock()
        self._latest_depth: np.ndarray | None = None
        self._latest_depth_encoding = ""
        self._latest_camera_info: CameraInfo | None = None

        self.create_subscription(Image, depth_topic, self._depth_cb, qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, camera_info_topic, self._camera_info_cb, qos_profile_sensor_data
        )

        self.create_service(
            ProjectPixelTo3D,
            "/drone_perception/project_pixel_to_3d",
            self._handle_project_pixel,
        )
        self.get_logger().info("Pixel projection service ready: /drone_perception/project_pixel_to_3d")

    def _depth_cb(self, msg: Image) -> None:
        try:
            depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode depth image: {exc}")
            return

        with self._lock:
            self._latest_depth = depth
            self._latest_depth_encoding = msg.encoding

    def _camera_info_cb(self, msg: CameraInfo) -> None:
        with self._lock:
            self._latest_camera_info = msg

    def _resolve_window_size(self, requested: int) -> int:
        default_size = int(self.get_parameter("default_window_size").value)
        size = requested if requested > 0 else default_size
        size = max(1, min(size, 31))
        if size % 2 == 0:
            size += 1
        return size

    def _extract_depth_m(
        self, pixel_x: int, pixel_y: int, depth_img: np.ndarray, encoding: str, window_size: int
    ) -> tuple[float | None, float]:
        h, w = depth_img.shape[:2]
        half = window_size // 2
        x0 = max(0, pixel_x - half)
        x1 = min(w, pixel_x + half + 1)
        y0 = max(0, pixel_y - half)
        y1 = min(h, pixel_y + half + 1)
        patch = depth_img[y0:y1, x0:x1].astype(np.float32)

        total = patch.size
        if total == 0:
            return None, 0.0

        valid = patch[np.isfinite(patch) & (patch > 0.0)]
        valid_ratio = float(valid.size) / float(total)
        if valid.size == 0:
            return None, valid_ratio

        depth = float(np.median(valid))
        if encoding.upper() in {"16UC1", "MONO16"} or depth > 100.0:
            depth *= 0.001

        if depth <= 0.0:
            return None, valid_ratio
        return depth, valid_ratio

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

    def _handle_project_pixel(
        self, request: ProjectPixelTo3D.Request, response: ProjectPixelTo3D.Response
    ):
        with self._lock:
            depth = None if self._latest_depth is None else self._latest_depth.copy()
            depth_encoding = self._latest_depth_encoding
            camera_info = self._latest_camera_info

        map_frame = self.get_parameter("map_frame").get_parameter_value().string_value
        response.frame_id = map_frame

        if depth is None or camera_info is None:
            response.success = False
            response.message = "Depth/CameraInfo data is not ready yet"
            return response

        pixel_x = int(request.pixel_x)
        pixel_y = int(request.pixel_y)
        h, w = depth.shape[:2]
        if pixel_x < 0 or pixel_x >= w or pixel_y < 0 or pixel_y >= h:
            response.success = False
            response.message = f"Pixel out of image bounds: ({pixel_x}, {pixel_y}) not in {w}x{h}"
            return response

        window_size = self._resolve_window_size(int(request.window_size))
        depth_m, valid_ratio = self._extract_depth_m(
            pixel_x, pixel_y, depth, depth_encoding, window_size
        )
        min_valid_ratio = float(self.get_parameter("min_valid_ratio").value)
        if depth_m is None or valid_ratio < min_valid_ratio:
            response.success = False
            response.message = (
                f"Insufficient valid depth near pixel (valid_ratio={valid_ratio:.2f}, "
                f"required>={min_valid_ratio:.2f})"
            )
            response.confidence = float(valid_ratio)
            return response

        fx = float(camera_info.k[0])
        fy = float(camera_info.k[4])
        cx = float(camera_info.k[2])
        cy = float(camera_info.k[5])
        if fx == 0.0 or fy == 0.0:
            response.success = False
            response.message = "Camera intrinsics are invalid"
            return response

        x_cam = (pixel_x - cx) * depth_m / fx
        y_cam = (pixel_y - cy) * depth_m / fy
        z_cam = depth_m

        source_frame = camera_info.header.frame_id
        if not source_frame:
            source_frame = self.get_parameter("camera_frame").get_parameter_value().string_value
        if not source_frame:
            response.success = False
            response.message = "Camera frame is empty in CameraInfo and camera_frame parameter"
            return response

        try:
            x_map, y_map, z_map = self._transform_to_map(x_cam, y_cam, z_cam, source_frame)
        except TransformException as exc:
            response.success = False
            response.message = f"TF lookup failed ({source_frame} -> {map_frame}): {exc}"
            return response

        response.success = True
        response.message = "Pixel projected to map frame"
        response.position.x = float(x_map)
        response.position.y = float(y_map)
        response.position.z = float(z_map)
        response.depth_m = float(depth_m)
        response.confidence = float(valid_ratio)
        return response


def main():
    rclpy.init()
    node = PixelProjectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
