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
        self.declare_parameter("result_topic", "/drone_perception/object_result")
        self.declare_parameter("window_name", "Drone UI")
        self.declare_parameter("window_resizable", True)
        self.declare_parameter("window_width", 1280)
        self.declare_parameter("window_height", 720)

        color_topic = str(self.get_parameter("color_topic").value)
        result_topic = str(self.get_parameter("result_topic").value)
        self._window_name = str(self.get_parameter("window_name").value)
        self._window_resizable = bool(self.get_parameter("window_resizable").value)
        self._window_width = int(self.get_parameter("window_width").value)
        self._window_height = int(self.get_parameter("window_height").value)

        self._bridge = CvBridge()
        self._lock = threading.Lock()
        self._observer_data: dict = {}
        self._window_ready = False

        self.create_subscription(Image, color_topic, self._image_cb, qos_profile_sensor_data)
        self.create_subscription(String, result_topic, self._result_cb, 10)
        self.get_logger().info(f"Simple UI ready: image={color_topic}, observer={result_topic}")

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

        self._ensure_window()

        with self._lock:
            observer = dict(self._observer_data)

        self._draw_overlay(image, observer)
        cv2.imshow(self._window_name, image)
        cv2.waitKey(1)

    def _ensure_window(self) -> None:
        if self._window_ready:
            return

        flags = cv2.WINDOW_NORMAL if self._window_resizable else cv2.WINDOW_AUTOSIZE
        cv2.namedWindow(self._window_name, flags)
        if self._window_resizable and self._window_width > 0 and self._window_height > 0:
            cv2.resizeWindow(self._window_name, self._window_width, self._window_height)
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
