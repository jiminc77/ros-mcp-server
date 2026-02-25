from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_perception = LaunchConfiguration("use_perception")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_perception",
                default_value="false",
                description="Launch static bbox projection service node",
            ),
            # MAVROS for Real Hardware (Serial / UART)
            Node(
                package="mavros",
                executable="mavros_node",
                output="screen",
                parameters=[
                    # ADJUST THESE FOR REAL DRONE
                    {"fcu_url": "serial:///dev/ttyUSB0:57600"},
                    {"system_id": 1},
                    {"component_id": 1},
                ],
            ),
            # Bridge Node
            Node(
                package="drone_controller",
                executable="bridge",
                output="screen",
                parameters=[{"use_sim_time": False}],
            ),
            Node(
                package="drone_perception",
                executable="bbox_projection",
                output="screen",
                condition=IfCondition(use_perception),
                parameters=[
                    {"depth_topic": "/camera/camera/aligned_depth_to_color/image_raw"},
                    {"camera_info_topic": "/camera/camera/color/camera_info"},
                    {"map_frame": "map"},
                ],
            ),
        ]
    )
