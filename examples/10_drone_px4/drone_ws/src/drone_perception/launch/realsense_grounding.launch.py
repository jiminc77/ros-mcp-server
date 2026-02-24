import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    start_realsense = LaunchConfiguration("start_realsense")
    start_debug_view = LaunchConfiguration("start_debug_view")

    start_realsense_arg = DeclareLaunchArgument(
        "start_realsense",
        default_value="true",
        description="Start realsense2_camera with depth-color alignment",
    )
    start_debug_view_arg = DeclareLaunchArgument(
        "start_debug_view",
        default_value="false",
        description="Open debug visualization window",
    )

    realsense_launch = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("realsense2_camera"),
                "launch",
                "rs_launch.py",
            )
        ),
        launch_arguments={"align_depth.enable": "true"}.items(),
        condition=IfCondition(start_realsense),
    )

    grounding_node = Node(
        package="drone_perception",
        executable="pixel_projection",
        name="pixel_projection",
        output="screen",
        parameters=[
            {"depth_topic": "/camera/camera/aligned_depth_to_color/image_raw"},
            {"camera_info_topic": "/camera/camera/color/camera_info"},
            {"map_frame": "map"},
        ],
    )

    debug_view_node = Node(
        package="drone_perception",
        executable="debug_view",
        name="debug_view",
        output="screen",
        condition=IfCondition(start_debug_view),
        parameters=[{"color_topic": "/camera/camera/color/image_raw"}],
    )

    return LaunchDescription(
        [start_realsense_arg, start_debug_view_arg, realsense_launch, grounding_node, debug_view_node]
    )
