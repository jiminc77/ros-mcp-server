import json
import threading

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from std_msgs.msg import String


class DebugViewNode(Node):
    def __init__(self):
        super().__init__("debug_view")
        self.declare_parameter("color_topic", "/camera/camera/color/image_raw")
        self.declare_parameter("overlay_topic", "/drone_perception/debug_overlay")
        self.declare_parameter("window_name", "Drone Perception Debug")

        color_topic = self.get_parameter("color_topic").get_parameter_value().string_value
        overlay_topic = self.get_parameter("overlay_topic").get_parameter_value().string_value
        self.window_name = self.get_parameter("window_name").get_parameter_value().string_value

        self.bridge = CvBridge()
        self._lock = threading.Lock()
        self._image = None
        self._overlay = {}

        self.create_subscription(Image, color_topic, self._image_cb, qos_profile_sensor_data)
        self.create_subscription(String, overlay_topic, self._overlay_cb, 10)
        self.create_timer(0.1, self._render)
        self.get_logger().info(
            f"Debug view ready. Publish JSON to {overlay_topic} to draw bbox/depth/waypoint."
        )

    def _image_cb(self, msg: Image) -> None:
        try:
            img = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception:
            return
        with self._lock:
            self._image = img

    def _overlay_cb(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            if isinstance(data, dict):
                with self._lock:
                    self._overlay = data
        except Exception:
            return

    @staticmethod
    def _as_int_pair(value, keys=("x", "y")):
        if isinstance(value, dict):
            try:
                return int(value.get(keys[0], 0)), int(value.get(keys[1], 0))
            except Exception:
                return None
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            try:
                return int(value[0]), int(value[1])
            except Exception:
                return None
        return None

    def _draw_text_lines(self, img, lines):
        y = 28
        for line in lines:
            cv2.putText(
                img,
                line,
                (16, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (32, 255, 32),
                2,
                cv2.LINE_AA,
            )
            y += 24

    def _render(self) -> None:
        with self._lock:
            if self._image is None:
                return
            img = self._image.copy()
            overlay = dict(self._overlay)

        bbox = overlay.get("bbox")
        if isinstance(bbox, dict):
            try:
                x0 = int(bbox.get("x_min", bbox.get("xmin", 0)))
                y0 = int(bbox.get("y_min", bbox.get("ymin", 0)))
                x1 = int(bbox.get("x_max", bbox.get("xmax", 0)))
                y1 = int(bbox.get("y_max", bbox.get("ymax", 0)))
                cv2.rectangle(img, (x0, y0), (x1, y1), (0, 200, 255), 2)
            except Exception:
                pass

        for key, color in (("pixel", (0, 255, 0)), ("representative_pixel", (0, 0, 255))):
            p = self._as_int_pair(overlay.get(key))
            if p is not None:
                cv2.circle(img, p, 4, color, -1)

        lines = []
        if "label" in overlay:
            lines.append(f"label: {overlay['label']}")
        if "det_confidence" in overlay:
            lines.append(f"det_conf: {overlay['det_confidence']}")
        if "depth_m" in overlay:
            lines.append(f"depth_m: {overlay['depth_m']}")
        if "object_map" in overlay:
            lines.append(f"object_map: {overlay['object_map']}")
        if "waypoint" in overlay:
            lines.append(f"waypoint: {overlay['waypoint']}")
        self._draw_text_lines(img, lines)

        cv2.imshow(self.window_name, img)
        cv2.waitKey(1)


def main():
    rclpy.init()
    node = DebugViewNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()
