import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class ImageRotatorNode(Node):
    def __init__(self):
        super().__init__("image_rotator")

        self.declare_parameter("input_topic", "/camera/camera/color/image_raw")
        self.declare_parameter("output_topic", "/drone_perception/color/image_rotated")
        self.declare_parameter("rotate_180", True)

        input_topic = self.get_parameter("input_topic").get_parameter_value().string_value
        output_topic = self.get_parameter("output_topic").get_parameter_value().string_value
        self._rotate_180 = bool(self.get_parameter("rotate_180").value)

        self._bridge = CvBridge()
        self._pub = self.create_publisher(Image, output_topic, qos_profile_sensor_data)
        self.create_subscription(Image, input_topic, self._image_cb, qos_profile_sensor_data)

        self.get_logger().info(f"Image rotator ready: {input_topic} -> {output_topic}")

    def _image_cb(self, msg: Image) -> None:
        try:
            image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            if self._rotate_180:
                image = cv2.rotate(image, cv2.ROTATE_180)
            rotated = self._bridge.cv2_to_imgmsg(image, encoding=msg.encoding)
            rotated.header = msg.header
            self._pub.publish(rotated)
        except Exception as exc:
            self.get_logger().warn(f"Failed to rotate/publish image: {exc}")


def main():
    rclpy.init()
    node = ImageRotatorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
