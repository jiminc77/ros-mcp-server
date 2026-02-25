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
        self.declare_parameter("window_name", "Drone UI")

        color_topic = self.get_parameter("color_topic").get_parameter_value().string_value
        overlay_topic = self.get_parameter("overlay_topic").get_parameter_value().string_value
        self._window_name = self.get_parameter("window_name").get_parameter_value().string_value

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._overlay: dict = {}

        self.create_subscription(Image, color_topic, self._image_cb, qos_profile_sensor_data)
        self.create_subscription(String, overlay_topic, self._overlay_cb, 10)
        self.get_logger().info(
            f"Simple UI ready: image={color_topic}, overlay={overlay_topic}"
        )

    def _overlay_cb(self, msg: String) -> None:
        try:
            overlay = json.loads(msg.data) if msg.data.strip() else {}
            if not isinstance(overlay, dict):
                raise ValueError("overlay must be a JSON object")
        except Exception as exc:
            self.get_logger().warn(f"Invalid overlay JSON: {exc}")
            return

        with self._lock:
            self._overlay = overlay

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

        lines = []
        if "label" in overlay:
            lines.append(f"label: {overlay['label']}")
        if "confidence" in overlay:
            lines.append(f"conf: {float(overlay['confidence']):.2f}")
        if "depth_m" in overlay:
            lines.append(f"depth: {float(overlay['depth_m']):.2f}m")

        if "object_map" in overlay:
            lines.append(f"object_map: {overlay['object_map']}")
        if "waypoint" in overlay:
            lines.append(f"waypoint: {overlay['waypoint']}")

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
        bbox = overlay.get("bbox", overlay)
        if not isinstance(bbox, dict):
            return None

        # Accept a few common key variants from LLM outputs.
        key_candidates = [
            ("x_min", "y_min", "x_max", "y_max"),
            ("xmin", "ymin", "xmax", "ymax"),
            ("left", "top", "right", "bottom"),
            ("x1", "y1", "x2", "y2"),
        ]
        values = None
        for keys in key_candidates:
            if all(k in bbox for k in keys):
                values = tuple(bbox[k] for k in keys)
                break
        if values is None:
            # Also accept x/y/w/h style boxes.
            if all(k in bbox for k in ("x", "y", "w", "h")):
                try:
                    x = float(bbox["x"])
                    y = float(bbox["y"])
                    w_box = float(bbox["w"])
                    h_box = float(bbox["h"])
                except Exception:
                    return None
                values = (x, y, x + w_box, y + h_box)
            else:
                return None

        try:
            x_min, y_min, x_max, y_max = [float(v) for v in values]
        except Exception:
            return None

        # Support normalized [0, 1] bbox values.
        if 0.0 <= min(x_min, y_min, x_max, y_max) and max(x_min, y_min, x_max, y_max) <= 1.0:
            x_min *= (w - 1)
            x_max *= (w - 1)
            y_min *= (h - 1)
            y_max *= (h - 1)

        x_min = int(round(x_min))
        y_min = int(round(y_min))
        x_max = int(round(x_max))
        y_max = int(round(y_max))

        if x_min > x_max:
            x_min, x_max = x_max, x_min
        if y_min > y_max:
            y_min, y_max = y_max, y_min

        # Clamp to image bounds when available.
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            x_min = max(0, min(x_min, w - 1))
            x_max = max(0, min(x_max, w - 1))
            y_min = max(0, min(y_min, h - 1))
            y_max = max(0, min(y_max, h - 1))

        if x_min == x_max or y_min == y_max:
            return None
        return x_min, y_min, x_max, y_max


def main():
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
