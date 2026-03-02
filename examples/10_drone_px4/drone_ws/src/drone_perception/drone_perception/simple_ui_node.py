import json
import threading

import cv2
import numpy as np
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
        self.declare_parameter("result_topic", "/drone_perception/object_result")
        self.declare_parameter("window_name", "Drone UI")
        self.declare_parameter("window_resizable", True)
        self.declare_parameter("window_width", 1280)
        self.declare_parameter("window_height", 720)
        self.declare_parameter("info_window_name", "Drone Info")
        self.declare_parameter("info_window_width", 560)
        self.declare_parameter("info_window_height", 720)
        self.declare_parameter("draw_overlay_on_image", False)

        color_topic = str(self.get_parameter("color_topic").value)
        result_topic = str(self.get_parameter("result_topic").value)
        self._window_name = str(self.get_parameter("window_name").value)
        self._window_resizable = bool(self.get_parameter("window_resizable").value)
        self._window_width = int(self.get_parameter("window_width").value)
        self._window_height = int(self.get_parameter("window_height").value)
        self._info_window_name = str(self.get_parameter("info_window_name").value)
        self._info_window_width = int(self.get_parameter("info_window_width").value)
        self._info_window_height = int(self.get_parameter("info_window_height").value)
        self._draw_overlay_on_image = bool(self.get_parameter("draw_overlay_on_image").value)

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._observer_data: dict = {}
        self._window_ready = False

        self.create_subscription(Image, color_topic, self._image_cb, qos_profile_sensor_data)
        self.create_subscription(String, result_topic, self._result_cb, 10)
        self.get_logger().info(
            "Simple UI ready: "
            f"image={color_topic}, observer={result_topic}, "
            f"draw_overlay_on_image={self._draw_overlay_on_image}"
        )

    def _result_cb(self, msg: String) -> None:
        result = self._decode_json(msg.data)
        if result is None:
            return

        observer = self._overlay_from_result(result)
        if not observer:
            return

        with self._lock:
            self._observer_data = observer

    def _image_cb(self, msg: Image) -> None:
        try:
            image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"Failed to decode image: {exc}")
            return

        self._ensure_windows()

        with self._lock:
            observer = dict(self._observer_data)

        if self._draw_overlay_on_image:
            self._draw_geometry_overlay(image, observer)

        info_panel = self._build_info_panel(observer)
        cv2.imshow(self._window_name, image)
        cv2.imshow(self._info_window_name, info_panel)
        cv2.waitKey(1)

    def _ensure_windows(self) -> None:
        if self._window_ready:
            return

        flags = cv2.WINDOW_NORMAL if self._window_resizable else cv2.WINDOW_AUTOSIZE
        cv2.namedWindow(self._window_name, flags)
        cv2.namedWindow(self._info_window_name, flags)
        if self._window_resizable and self._window_width > 0 and self._window_height > 0:
            cv2.resizeWindow(self._window_name, self._window_width, self._window_height)
        if self._window_resizable and self._info_window_width > 0 and self._info_window_height > 0:
            cv2.resizeWindow(
                self._info_window_name,
                self._info_window_width,
                self._info_window_height,
            )
        self._window_ready = True

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
    def _draw_geometry_overlay(image, overlay: dict) -> None:
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

    def _build_info_panel(self, overlay: dict):
        width = max(320, self._info_window_width)
        height = max(240, self._info_window_height)
        panel = np.full((height, width, 3), (20, 22, 26), dtype=np.uint8)

        cv2.putText(
            panel,
            "Drone Perception",
            (18, 36),
            cv2.FONT_HERSHEY_DUPLEX,
            0.85,
            (245, 245, 245),
            1,
            cv2.LINE_AA,
        )
        cv2.line(panel, (18, 50), (width - 18, 50), (90, 90, 90), 1)

        lines = self._build_info_lines(overlay)
        y = 80
        for line in lines:
            if y > height - 16:
                break
            clipped = self._clip_line(line, width)
            cv2.putText(
                panel,
                clipped,
                (18, y),
                cv2.FONT_HERSHEY_DUPLEX,
                0.58,
                (220, 235, 220),
                1,
                cv2.LINE_AA,
            )
            y += 26
        return panel

    @staticmethod
    def _build_info_lines(overlay: dict) -> list[str]:
        lines = []
        status_code = overlay.get("status_code")
        if status_code:
            lines.append(f"status: {status_code}")

        status_message = overlay.get("status_message")
        if status_message:
            lines.append(f"message: {status_message}")

        label = overlay.get("label")
        if label is not None:
            lines.append(f"label: {label}")

        conf = overlay.get("confidence")
        if conf is not None:
            lines.append(f"confidence: {SimpleUiNode._format_number(conf)}")

        if "depth_m" in overlay:
            lines.append(f"depth(m): {SimpleUiNode._format_number(overlay['depth_m'])}")

        bbox = overlay.get("bbox")
        if isinstance(bbox, dict):
            keys = ("x_min", "y_min", "x_max", "y_max")
            if all(k in bbox for k in keys):
                lines.append(
                    "bbox(px): "
                    f"[{SimpleUiNode._format_number(bbox['x_min'])}, "
                    f"{SimpleUiNode._format_number(bbox['y_min'])}] -> "
                    f"[{SimpleUiNode._format_number(bbox['x_max'])}, "
                    f"{SimpleUiNode._format_number(bbox['y_max'])}]"
                )

        rep = overlay.get("representative_pixel")
        if isinstance(rep, dict) and "x" in rep and "y" in rep:
            lines.append(
                "pixel(px): "
                f"({SimpleUiNode._format_number(rep['x'])}, "
                f"{SimpleUiNode._format_number(rep['y'])})"
            )
        elif "representative_pixel_x" in overlay and "representative_pixel_y" in overlay:
            lines.append(
                "pixel(px): "
                f"({SimpleUiNode._format_number(overlay['representative_pixel_x'])}, "
                f"{SimpleUiNode._format_number(overlay['representative_pixel_y'])})"
            )

        object_map = overlay.get("object_map")
        if isinstance(object_map, dict):
            x = object_map.get("x")
            y = object_map.get("y")
            z = object_map.get("z")
            if x is not None or y is not None or z is not None:
                lines.append(
                    "map(m): "
                    f"({SimpleUiNode._format_number(x)}, "
                    f"{SimpleUiNode._format_number(y)}, "
                    f"{SimpleUiNode._format_number(z)})"
                )
            frame = object_map.get("frame_id", object_map.get("frame"))
            if frame:
                lines.append(f"frame: {frame}")
        elif object_map is not None:
            lines.append(f"object_map: {SimpleUiNode._format_json(object_map)}")

        caption = overlay.get("caption")
        if caption:
            lines.append(f"caption: {caption}")

        if not lines:
            lines.append("No detection result yet.")
        return lines

    @staticmethod
    def _format_number(value) -> str:
        if value is None:
            return "-"
        try:
            number = round(float(value), 2)
        except Exception:
            return str(value)
        return f"{number:.2f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_json(value) -> str:
        try:
            normalized = SimpleUiNode._normalize_for_display(value)
            return json.dumps(normalized, separators=(",", ":"))
        except Exception:
            return str(value)

    @staticmethod
    def _normalize_for_display(value):
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, (int, float)):
            return round(float(value), 2)
        if isinstance(value, dict):
            return {k: SimpleUiNode._normalize_for_display(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [SimpleUiNode._normalize_for_display(v) for v in value]
        return str(value)

    @staticmethod
    def _clip_line(text: str, width: int) -> str:
        max_chars = max(24, int(width / 9))
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    @staticmethod
    def _parse_bbox(overlay: dict, image_shape):
        height, width = image_shape
        bbox = overlay.get("bbox")
        if not isinstance(bbox, dict):
            return None

        required = ("x_min", "y_min", "x_max", "y_max")
        if not all(key in bbox for key in required):
            return None

        try:
            x_min = int(bbox["x_min"])
            y_min = int(bbox["y_min"])
            x_max = int(bbox["x_max"])
            y_max = int(bbox["y_max"])
        except Exception:
            return None

        x_min, x_max = sorted((x_min, x_max))
        y_min, y_max = sorted((y_min, y_max))

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
