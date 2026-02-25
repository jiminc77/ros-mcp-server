from collections import deque
import threading

import numpy as np
import rclpy
from cv_bridge import CvBridge
from drone_interfaces.srv import ProjectBBoxTo3D
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import Buffer, TransformException, TransformListener


class BBoxProjectionNode(Node):
    def __init__(self):
        super().__init__("bbox_projection")

        self.declare_parameter("depth_topic", "/camera/camera/aligned_depth_to_color/image_raw")
        self.declare_parameter("camera_info_topic", "/camera/camera/color/camera_info")
        self.declare_parameter("camera_frame", "")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("default_window_size", 5)
        self.declare_parameter("depth_history_size", 5)
        self.declare_parameter("min_valid_ratio", 0.25)
        self.declare_parameter("max_sync_gap_sec", 0.20)
        self.declare_parameter("bbox_input_rotated_180", False)

        depth_topic = self.get_parameter("depth_topic").get_parameter_value().string_value
        camera_info_topic = self.get_parameter("camera_info_topic").get_parameter_value().string_value
        depth_history_size = max(1, int(self.get_parameter("depth_history_size").value))

        self.bridge = CvBridge()
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self._lock = threading.Lock()
        self._depth_history: deque[tuple[np.ndarray, str, int]] = deque(maxlen=depth_history_size)
        self._latest_camera_info: CameraInfo | None = None

        self.create_subscription(Image, depth_topic, self._depth_cb, qos_profile_sensor_data)
        self.create_subscription(
            CameraInfo, camera_info_topic, self._camera_info_cb, qos_profile_sensor_data
        )

        self.create_service(
            ProjectBBoxTo3D,
            "/drone_perception/project_bbox_to_3d",
            self._handle_project_bbox,
        )
        self.get_logger().info("BBox projection service ready: /drone_perception/project_bbox_to_3d")

    def _depth_cb(self, msg: Image) -> None:
        try:
            depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode depth image: {exc}")
            return

        with self._lock:
            stamp = msg.header.stamp
            stamp_ns = int(stamp.sec) * 1_000_000_000 + int(stamp.nanosec)
            self._depth_history.append((depth, msg.encoding, stamp_ns))

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
    def _status(code: str, detail: str) -> str:
        return f"{code}: {detail}"

    def _to_meters(self, raw_depth: np.ndarray, encoding: str) -> np.ndarray:
        depth = raw_depth.astype(np.float32)
        if encoding.upper() in {"16UC1", "MONO16"}:
            depth *= 0.001
        return depth

    def _average_patch_from_history(
        self, depth_history: list[tuple[np.ndarray, str, int]], ys: np.ndarray, xs: np.ndarray
    ) -> np.ndarray | None:
        patches = []
        y_max = int(ys[-1])
        x_max = int(xs[-1])

        for depth_img, encoding, _ in depth_history:
            h, w = depth_img.shape[:2]
            if y_max >= h or x_max >= w:
                continue
            patch = self._to_meters(depth_img[np.ix_(ys, xs)], encoding)
            patch[~np.isfinite(patch) | (patch <= 0.0)] = np.nan
            patches.append(patch)

        if not patches:
            return None

        stack = np.stack(patches, axis=0)
        valid = np.isfinite(stack) & (stack > 0.0)
        counts = valid.sum(axis=0)
        sums = np.where(valid, stack, 0.0).sum(axis=0)
        return np.divide(
            sums,
            counts,
            out=np.full(sums.shape, np.nan, dtype=np.float32),
            where=counts > 0,
        )

    def _extract_depth_from_history(
        self,
        pixel_x: int,
        pixel_y: int,
        depth_history: list[tuple[np.ndarray, str, int]],
        window_size: int,
    ) -> tuple[float | None, float]:
        depths = []
        valid_ratios = []

        for depth_img, encoding, _ in depth_history:
            depth_m, valid_ratio = self._extract_depth_m(
                pixel_x, pixel_y, depth_img, encoding, window_size
            )
            valid_ratios.append(valid_ratio)
            if depth_m is not None:
                depths.append(depth_m)

        if not valid_ratios:
            return None, 0.0

        avg_valid_ratio = float(sum(valid_ratios) / len(valid_ratios))
        if not depths:
            return None, avg_valid_ratio

        return float(sum(depths) / len(depths)), avg_valid_ratio

    @staticmethod
    def _request_stamp_ns(request: ProjectBBoxTo3D.Request) -> int:
        return int(request.image_stamp_sec) * 1_000_000_000 + int(request.image_stamp_nanosec)

    def _select_depth_history(
        self, request: ProjectBBoxTo3D.Request, depth_history: list[tuple[np.ndarray, str, int]]
    ) -> tuple[list[tuple[np.ndarray, str, int]] | None, float]:
        target_ns = self._request_stamp_ns(request)
        if target_ns <= 0:
            return depth_history, 0.0

        best = min(depth_history, key=lambda item: abs(item[2] - target_ns))
        sync_gap_sec = abs(best[2] - target_ns) / 1_000_000_000.0
        max_sync_gap = float(self.get_parameter("max_sync_gap_sec").value)
        if sync_gap_sec > max_sync_gap:
            return None, sync_gap_sec
        return [best], sync_gap_sec

    @staticmethod
    def _clamp_bbox(
        x_min: int, y_min: int, x_max: int, y_max: int, width: int, height: int
    ) -> tuple[int, int, int, int]:
        x0 = max(0, min(min(x_min, x_max), width - 1))
        y0 = max(0, min(min(y_min, y_max), height - 1))
        x1 = max(0, min(max(x_min, x_max), width - 1))
        y1 = max(0, min(max(y_min, y_max), height - 1))
        return x0, y0, x1, y1

    @staticmethod
    def _bbox_rotated_to_raw(
        x_min: int, y_min: int, x_max: int, y_max: int, width: int, height: int
    ) -> tuple[int, int, int, int]:
        raw_x_min = (width - 1) - x_max
        raw_x_max = (width - 1) - x_min
        raw_y_min = (height - 1) - y_max
        raw_y_max = (height - 1) - y_min
        return raw_x_min, raw_y_min, raw_x_max, raw_y_max

    @staticmethod
    def _pixel_raw_to_rotated(px: int, py: int, width: int, height: int) -> tuple[int, int]:
        return (width - 1) - px, (height - 1) - py

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

    def _handle_project_bbox(
        self, request: ProjectBBoxTo3D.Request, response: ProjectBBoxTo3D.Response
    ):
        with self._lock:
            depth_history = [(d.copy(), enc, ts_ns) for d, enc, ts_ns in self._depth_history]
            camera_info = self._latest_camera_info

        map_frame = self.get_parameter("map_frame").get_parameter_value().string_value
        response.frame_id = map_frame

        if not depth_history or camera_info is None:
            response.success = False
            response.message = self._status(
                "E_DATA_NOT_READY", "Depth/CameraInfo data is not ready yet"
            )
            return response

        selected_history, sync_gap_sec = self._select_depth_history(request, depth_history)
        if selected_history is None:
            max_sync_gap = float(self.get_parameter("max_sync_gap_sec").value)
            response.success = False
            response.message = self._status(
                "E_TIME_SYNC",
                (
                    f"No depth frame near image stamp "
                    f"(gap={sync_gap_sec:.3f}s, max={max_sync_gap:.3f}s)"
                ),
            )
            return response

        latest_depth = selected_history[-1][0]
        h, w = latest_depth.shape[:2]
        x0_in, y0_in, x1_in, y1_in = self._clamp_bbox(
            int(request.x_min), int(request.y_min), int(request.x_max), int(request.y_max), w, h
        )
        use_rotated_bbox = bool(self.get_parameter("bbox_input_rotated_180").value)
        if use_rotated_bbox:
            x0, y0, x1, y1 = self._bbox_rotated_to_raw(x0_in, y0_in, x1_in, y1_in, w, h)
            x0, y0, x1, y1 = self._clamp_bbox(x0, y0, x1, y1, w, h)
        else:
            x0, y0, x1, y1 = x0_in, y0_in, x1_in, y1_in

        if x0 > x1 or y0 > y1:
            response.success = False
            response.message = self._status("E_INVALID_BBOX", "Invalid bbox range")
            return response

        requested_step = int(request.sample_step)
        sample_step = max(1, min(16, requested_step if requested_step > 0 else 1))
        ys = np.arange(y0, y1 + 1, sample_step, dtype=np.int32)
        xs = np.arange(x0, x1 + 1, sample_step, dtype=np.int32)
        if ys.size == 0 or xs.size == 0:
            response.success = False
            response.message = self._status("E_INVALID_BBOX", "Empty bbox after sampling")
            return response

        patch_m = self._average_patch_from_history(selected_history, ys, xs)
        if patch_m is None:
            response.success = False
            response.message = self._status("E_DATA_NOT_READY", "No usable depth frames in buffer")
            return response

        valid_mask = np.isfinite(patch_m) & (patch_m > 0.0)
        total = patch_m.size
        valid_count = int(np.count_nonzero(valid_mask))
        valid_ratio = float(valid_count) / float(total) if total > 0 else 0.0
        min_valid_ratio = float(self.get_parameter("min_valid_ratio").value)

        if valid_count == 0 or valid_ratio < min_valid_ratio:
            response.success = False
            response.message = self._status(
                "E_DEPTH_INVALID",
                (
                    f"Insufficient valid depth in bbox (valid_ratio={valid_ratio:.2f}, "
                    f"required>={min_valid_ratio:.2f})"
                ),
            )
            response.confidence = float(valid_ratio)
            return response

        grid_y, grid_x = np.meshgrid(ys, xs, indexing="ij")
        valid_depths = patch_m[valid_mask]
        valid_x = grid_x[valid_mask]
        valid_y = grid_y[valid_mask]

        median_depth = float(np.median(valid_depths))
        rep_index = int(np.argmin(np.abs(valid_depths - median_depth)))
        rep_x = int(valid_x[rep_index])
        rep_y = int(valid_y[rep_index])

        window_size = self._resolve_window_size(0)
        depth_m, local_ratio = self._extract_depth_from_history(
            rep_x, rep_y, selected_history, window_size
        )
        if depth_m is None:
            depth_m = median_depth
        confidence = min(valid_ratio, local_ratio if local_ratio > 0 else valid_ratio)

        fx = float(camera_info.k[0])
        fy = float(camera_info.k[4])
        cx = float(camera_info.k[2])
        cy = float(camera_info.k[5])
        if fx == 0.0 or fy == 0.0:
            response.success = False
            response.message = self._status("E_CAMERA_INTRINSICS", "Camera intrinsics are invalid")
            return response

        x_cam = (rep_x - cx) * depth_m / fx
        y_cam = (rep_y - cy) * depth_m / fy
        z_cam = depth_m

        source_frame = camera_info.header.frame_id
        if not source_frame:
            source_frame = self.get_parameter("camera_frame").get_parameter_value().string_value
        if not source_frame:
            response.success = False
            response.message = self._status(
                "E_CAMERA_FRAME", "Camera frame is empty in CameraInfo and camera_frame parameter"
            )
            return response

        try:
            x_map, y_map, z_map = self._transform_to_map(x_cam, y_cam, z_cam, source_frame)
        except TransformException as exc:
            response.success = False
            response.message = self._status(
                "E_TF_LOOKUP", f"TF lookup failed ({source_frame} -> {map_frame}): {exc}"
            )
            return response

        response.success = True
        response.message = self._status("OK_BBOX_PROJECTED", "BBox projected to map frame")
        response.position.x = float(x_map)
        response.position.y = float(y_map)
        response.position.z = float(z_map)
        if use_rotated_bbox:
            rep_x_out, rep_y_out = self._pixel_raw_to_rotated(rep_x, rep_y, w, h)
        else:
            rep_x_out, rep_y_out = rep_x, rep_y
        response.representative_pixel_x = int(rep_x_out)
        response.representative_pixel_y = int(rep_y_out)
        response.depth_m = float(depth_m)
        response.confidence = float(confidence)
        return response


def main():
    rclpy.init()
    node = BBoxProjectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
