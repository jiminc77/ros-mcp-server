import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_perception = LaunchConfiguration("use_perception")
    fcu_url = LaunchConfiguration("fcu_url")
    mavros_px4_launch = os.path.join(get_package_share_directory("mavros"), "launch", "px4.launch")

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_perception",
                default_value="false",
                description="Launch static bbox projection service node",
            ),
            DeclareLaunchArgument(
                "fcu_url",
                default_value="udp://:14540@127.0.0.1:14557",
                description="MAVROS FCU connection URL",
            ),
            IncludeLaunchDescription(
                AnyLaunchDescriptionSource(mavros_px4_launch),
                launch_arguments={"fcu_url": fcu_url}.items(),
            ),
            # Bridge Node
            Node(
                package="drone_controller",
                executable="bridge",
                output="screen",
                parameters=[{"use_sim_time": True}],
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
