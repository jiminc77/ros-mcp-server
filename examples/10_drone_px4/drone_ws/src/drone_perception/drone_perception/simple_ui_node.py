import json
import threading

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String


class SimpleUiNode(Node):
    def __init__(self):
        super().__init__("simple_ui")

        self.declare_parameter("color_topic", "/drone_perception/color/image_rotated")
        self.declare_parameter("overlay_topic", "/drone_perception/ui_overlay")
        self.declare_parameter("result_topic", "/drone_perception/object_result")
        self.declare_parameter("window_name", "Drone UI")

        color_topic = str(self.get_parameter("color_topic").value)
        overlay_topic = str(self.get_parameter("overlay_topic").value)
        result_topic = str(self.get_parameter("result_topic").value)
        self._window_name = str(self.get_parameter("window_name").value)

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._overlay: dict = {}

        self.create_subscription(Image, color_topic, self._image_cb, qos_profile_sensor_data)
        self.create_subscription(String, overlay_topic, self._overlay_cb, 10)
        self.create_subscription(String, result_topic, self._result_cb, 10)
        self.get_logger().info(
            f"Simple UI ready: image={color_topic}, overlay={overlay_topic}, result={result_topic}"
        )

    def _overlay_cb(self, msg: String) -> None:
        overlay = self._decode_json(msg.data)
        if overlay is None:
            return

        with self._lock:
            self._overlay = overlay

    def _result_cb(self, msg: String) -> None:
        result = self._decode_json(msg.data)
        if result is None:
            return

        overlay = self._overlay_from_result(result)
        if not overlay:
            return

        with self._lock:
            merged = dict(self._overlay)
            merged.update(overlay)
            self._overlay = merged

    def _image_cb(self, msg: Image) -> None:
        try:
            image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode image: {exc}")
            return

        with self._lock:
            overlay = dict(self._overlay)

        self._draw_overlay(image, overlay)
        cv2.imshow(self._window_name, image)
        cv2.waitKey(1)

    @staticmethod
    def _decode_json(raw: str) -> dict | None:
        try:
            obj = json.loads(raw) if raw.strip() else {}
            if not isinstance(obj, dict):
                return None
            return obj
        except Exception:
            return None

    @staticmethod
    def _overlay_from_result(result: dict) -> dict:
        out = {}

        det = result.get("detection")
        if isinstance(det, dict):
            if "bbox" in det:
                out["bbox"] = det["bbox"]
            if "label" in det:
                out["label"] = det["label"]
            if "confidence" in det:
                out["confidence"] = det["confidence"]

        for key in (
            "representative_pixel",
            "representative_pixel_x",
            "representative_pixel_y",
            "depth_m",
            "object_map",
            "caption",
            "status_code",
            "status_message",
        ):
            if key in result:
                out[key] = result[key]

        return out

    @staticmethod
    def _draw_overlay(image, overlay: dict) -> None:
        bbox = SimpleUiNode._parse_bbox(overlay, image.shape[:2])
        if bbox is not None:
            x_min, y_min, x_max, y_max = bbox
            cv2.rectangle(image, (x_min, y_min), (x_max, y_max), (0, 255, 255), 2)

        rep = overlay.get("representative_pixel")
        if isinstance(rep, dict) and "x" in rep and "y" in rep:
            cv2.circle(image, (int(rep["x"]), int(rep["y"])), 4, (0, 0, 255), -1)
        elif "representative_pixel_x" in overlay and "representative_pixel_y" in overlay:
            cv2.circle(
                image,
                (int(overlay["representative_pixel_x"]), int(overlay["representative_pixel_y"])),
                4,
                (0, 0, 255),
                -1,
            )

        det = overlay.get("detection") if isinstance(overlay.get("detection"), dict) else {}

        lines = []
        label = overlay.get("label", det.get("label"))
        if label is not None:
            lines.append(f"label: {label}")

        conf = overlay.get("confidence", det.get("confidence"))
        if conf is not None:
            try:
                lines.append(f"conf: {float(conf):.2f}")
            except Exception:
                pass

        if "depth_m" in overlay:
            try:
                lines.append(f"depth: {float(overlay['depth_m']):.2f}m")
            except Exception:
                pass

        if "object_map" in overlay:
            lines.append(f"object_map: {overlay['object_map']}")

        if "status_code" in overlay:
            lines.append(f"status: {overlay['status_code']}")

        for idx, line in enumerate(lines):
            y = 25 + (idx * 24)
            cv2.putText(
                image,
                line,
                (12, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (50, 255, 50),
                2,
                cv2.LINE_AA,
            )

    @staticmethod
    def _parse_bbox(overlay: dict, image_shape):
        h, w = image_shape

        candidates = []
        bbox = overlay.get("bbox")
        if bbox is not None:
            candidates.append(bbox)

        det = overlay.get("detection")
        if isinstance(det, dict) and det.get("bbox") is not None:
            candidates.append(det["bbox"])

        candidates.append(overlay)

        for candidate in candidates:
            parsed = SimpleUiNode._bbox_from_any(candidate, w, h)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _bbox_from_any(candidate, width: int, height: int):
        if isinstance(candidate, dict):
            key_sets = [
                ("x_min", "y_min", "x_max", "y_max", "xyxy"),
                ("xmin", "ymin", "xmax", "ymax", "xyxy"),
                ("x1", "y1", "x2", "y2", "xyxy"),
                ("left", "top", "right", "bottom", "xyxy"),
                ("ymin", "xmin", "ymax", "xmax", "yxyx"),
            ]
            for k0, k1, k2, k3, order in key_sets:
                if all(k in candidate for k in (k0, k1, k2, k3)):
                    return SimpleUiNode._bbox_from_values(
                        candidate[k0],
                        candidate[k1],
                        candidate[k2],
                        candidate[k3],
                        width,
                        height,
                        order,
                    )
            return None

        if isinstance(candidate, (list, tuple)) and len(candidate) == 4:
            parsed_xyxy = SimpleUiNode._bbox_from_values(
                candidate[0], candidate[1], candidate[2], candidate[3], width, height, "xyxy"
            )
            parsed_yxyx = SimpleUiNode._bbox_from_values(
                candidate[0], candidate[1], candidate[2], candidate[3], width, height, "yxyx"
            )
            if parsed_xyxy is None:
                return parsed_yxyx
            if parsed_yxyx is None:
                return parsed_xyxy

            area_xyxy = (parsed_xyxy[2] - parsed_xyxy[0]) * (parsed_xyxy[3] - parsed_xyxy[1])
            area_yxyx = (parsed_yxyx[2] - parsed_yxyx[0]) * (parsed_yxyx[3] - parsed_yxyx[1])
            return parsed_xyxy if area_xyxy >= area_yxyx else parsed_yxyx

        return None

    @staticmethod
    def _bbox_from_values(a, b, c, d, width: int, height: int, order: str):
        try:
            v0, v1, v2, v3 = float(a), float(b), float(c), float(d)
        except Exception:
            return None

        is_normalized = all(0.0 <= v <= 1.0 for v in (v0, v1, v2, v3))

        if order == "xyxy":
            x_min, y_min, x_max, y_max = v0, v1, v2, v3
        else:
            y_min, x_min, y_max, x_max = v0, v1, v2, v3

        if is_normalized:
            x_min *= max(1, width - 1)
            x_max *= max(1, width - 1)
            y_min *= max(1, height - 1)
            y_max *= max(1, height - 1)

        x_min, x_max = sorted((int(round(x_min)), int(round(x_max))))
        y_min, y_max = sorted((int(round(y_min)), int(round(y_max))))

        x_min = max(0, min(x_min, width - 1))
        x_max = max(0, min(x_max, width - 1))
        y_min = max(0, min(y_min, height - 1))
        y_max = max(0, min(y_max, height - 1))

        if x_min >= x_max or y_min >= y_max:
            return None
        return x_min, y_min, x_max, y_max


def main() -> None:
    rclpy.init()
    node = SimpleUiNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()
