import copy

import numpy as np
from rclpy.duration import Duration
from rclpy.time import Time
from sensor_msgs.msg import CameraInfo
from tf2_ros import TransformException

from drone_perception.config import PerceptionConfig


class ProjectionEngine:
    def __init__(self, config: PerceptionConfig, tf_buffer, trace):
        self._config = config
        self._tf_buffer = tf_buffer
        self._trace = trace

    def snapshot_inputs(
        self,
        *,
        depth_history: list,
        camera_info: CameraInfo | None,
        image_stamp_sec: int,
        image_stamp_nanosec: int,
    ) -> dict:
        target_ns = int(image_stamp_sec) * 1_000_000_000 + int(image_stamp_nanosec)
        if not depth_history or camera_info is None:
            return {
                "ok": False,
                "code": "E_DATA_NOT_READY",
                "message": "Depth/CameraInfo data is not ready yet",
            }

        depth, encoding, stamp_ns = min(
            depth_history,
            key=lambda item: abs(item[2] - target_ns),
        )
        gap_sec = abs(stamp_ns - target_ns) / 1_000_000_000.0 if target_ns > 0 else 0.0
        if target_ns > 0 and gap_sec > self._config.max_sync_gap_sec:
            self._trace(
                f"snapshot sync gap too large gap={gap_sec:.3f}s max={self._config.max_sync_gap_sec:.3f}s"
            )
            return {
                "ok": False,
                "code": "E_TIME_SYNC",
                "message": (
                    "No depth frame near image stamp "
                    f"(gap={gap_sec:.3f}s, max={self._config.max_sync_gap_sec:.3f}s)"
                ),
            }

        return {
            "ok": True,
            "depth_frame": depth.copy(),
            "depth_encoding": str(encoding),
            "camera_info": copy.deepcopy(camera_info),
        }

    def project_rotated_bbox_to_map(
        self,
        *,
        bbox: dict,
        depth_frame,
        depth_encoding: str,
        camera_info: CameraInfo,
        image_stamp_sec: int,
        image_stamp_nanosec: int,
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

        if self._config.rotate_180:
            x0_raw, y0_raw, x1_raw, y1_raw = self._bbox_rotated_to_raw(
                x0_rot, y0_rot, x1_rot, y1_rot, w, h
            )
            x0_raw, y0_raw, x1_raw, y1_raw = self._clamp_bbox(x0_raw, y0_raw, x1_raw, y1_raw, w, h)
        else:
            x0_raw, y0_raw, x1_raw, y1_raw = x0_rot, y0_rot, x1_rot, y1_rot

        center_x = (x0_raw + x1_raw) // 2
        center_y = (y0_raw + y1_raw) // 2

        depth_m, valid_ratio, rep_x_raw, rep_y_raw = self._depth_from_bbox_nearest_band(
            depth_img=depth_frame,
            encoding=depth_encoding,
            x_min=x0_raw,
            y_min=y0_raw,
            x_max=x1_raw,
            y_max=y1_raw,
            min_depth_m=self._config.min_depth_m,
            max_depth_m=self._config.max_depth_m,
            inset_ratio=self._config.default_depth_roi_inset_ratio,
            near_percentile=self._config.default_depth_near_percentile,
            near_margin_m=self._config.default_depth_near_margin_m,
        )
        if depth_m is None:
            return {
                "ok": False,
                "code": "E_DEPTH_INVALID",
                "message": "No valid depth in bbox ROI",
                "confidence": float(valid_ratio),
            }

        if rep_x_raw is None or rep_y_raw is None:
            rep_x_raw, rep_y_raw = center_x, center_y

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

        x_cam = (float(rep_x_raw) - cx) * depth_m / fx
        y_cam = (float(rep_y_raw) - cy) * depth_m / fy
        z_cam = depth_m

        source_frame = camera_info.header.frame_id.strip() or self._config.camera_frame
        if not source_frame:
            return {
                "ok": False,
                "code": "E_CAMERA_FRAME",
                "message": "Camera frame is empty in CameraInfo and camera_frame parameter",
            }

        try:
            x_map, y_map, z_map = self._transform_to_map(
                x_cam,
                y_cam,
                z_cam,
                source_frame=source_frame,
                stamp_sec=image_stamp_sec,
                stamp_nanosec=image_stamp_nanosec,
            )
        except TransformException as exc:
            return {
                "ok": False,
                "code": "E_TF_LOOKUP",
                "message": f"TF lookup failed ({source_frame} -> {self._config.map_frame}): {exc}",
            }

        if self._config.rotate_180:
            rep_x, rep_y = self._pixel_raw_to_rotated(rep_x_raw, rep_y_raw, w, h)
        else:
            rep_x, rep_y = rep_x_raw, rep_y_raw

        return {
            "ok": True,
            "depth_m": float(depth_m),
            "confidence": float(valid_ratio),
            "representative_pixel": {"x": int(rep_x), "y": int(rep_y)},
            "object_map": {
                "x": float(x_map),
                "y": float(y_map),
                "z": float(z_map),
                "frame_id": self._config.map_frame,
            },
        }

    def _transform_to_map(
        self,
        x: float,
        y: float,
        z: float,
        *,
        source_frame: str,
        stamp_sec: int,
        stamp_nanosec: int,
    ) -> tuple[float, float, float]:
        if source_frame == self._config.map_frame:
            return x, y, z

        stamp = Time(seconds=int(stamp_sec), nanoseconds=int(stamp_nanosec))
        if stamp_sec <= 0 and stamp_nanosec <= 0:
            stamp = Time()

        transform = self._tf_buffer.lookup_transform(
            self._config.map_frame,
            source_frame,
            stamp,
            timeout=Duration(seconds=0.2),
        )
        t = transform.transform.translation
        q = transform.transform.rotation
        rx, ry, rz = self._rotate_vector_by_quat(x, y, z, q.x, q.y, q.z, q.w)
        return rx + t.x, ry + t.y, rz + t.z

    @staticmethod
    def _depth_from_bbox_nearest_band(
        *,
        depth_img,
        encoding: str,
        x_min: int,
        y_min: int,
        x_max: int,
        y_max: int,
        min_depth_m: float,
        max_depth_m: float,
        inset_ratio: float,
        near_percentile: float,
        near_margin_m: float,
    ) -> tuple[float | None, float, int | None, int | None]:
        h, w = depth_img.shape[:2]
        x0 = max(0, min(x_min, x_max))
        y0 = max(0, min(y_min, y_max))
        x1 = min(w - 1, max(x_min, x_max))
        y1 = min(h - 1, max(y_min, y_max))
        if x0 > x1 or y0 > y1:
            return None, 0.0, None, None

        roi_w = x1 - x0 + 1
        roi_h = y1 - y0 + 1
        inset_ratio = max(0.0, min(0.4, float(inset_ratio)))
        inset_x = int(round(roi_w * inset_ratio))
        inset_y = int(round(roi_h * inset_ratio))
        xi0, yi0, xi1, yi1 = x0 + inset_x, y0 + inset_y, x1 - inset_x, y1 - inset_y
        if xi0 > xi1 or yi0 > yi1:
            xi0, yi0, xi1, yi1 = x0, y0, x1, y1

        roi = depth_img[yi0 : yi1 + 1, xi0 : xi1 + 1].astype(np.float32)
        depth_meters = ProjectionEngine._depth_to_meters(roi, encoding)
        finite = np.isfinite(depth_meters)
        valid_mask = (
            finite
            & (depth_meters > 0.0)
            & (depth_meters >= min_depth_m)
            & (depth_meters <= max_depth_m)
        )

        total = depth_meters.size
        valid_count = int(np.count_nonzero(valid_mask))
        valid_ratio = float(valid_count) / float(total) if total > 0 else 0.0
        if valid_count == 0:
            return None, valid_ratio, None, None

        valid_depths = depth_meters[valid_mask]
        near_percentile = max(0.0, min(100.0, float(near_percentile)))
        near_cut = float(np.percentile(valid_depths, near_percentile)) + max(0.0, float(near_margin_m))
        near_mask = valid_mask & (depth_meters <= near_cut)
        if not np.any(near_mask):
            near_mask = valid_mask

        selected_depths = depth_meters[near_mask]
        depth_m = float(np.median(selected_depths))

        diff = np.abs(depth_meters - depth_m)
        diff[~near_mask] = np.inf
        flat_idx = int(np.argmin(diff))
        py, px = np.unravel_index(flat_idx, diff.shape)
        rep_x = int(xi0 + px)
        rep_y = int(yi0 + py)
        return depth_m, valid_ratio, rep_x, rep_y

    @staticmethod
    def _depth_to_meters(depth_patch: np.ndarray, encoding: str) -> np.ndarray:
        if encoding.upper() in {"16UC1", "MONO16"}:
            return depth_patch * 0.001
        return depth_patch

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
