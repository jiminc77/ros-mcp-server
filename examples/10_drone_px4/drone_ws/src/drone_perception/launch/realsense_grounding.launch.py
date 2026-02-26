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

    start_realsense_arg = DeclareLaunchArgument(
        "start_realsense",
        default_value="true",
        description="Start realsense2_camera with depth-color alignment",
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

    gemini_grounding_node = Node(
        package="drone_perception",
        executable="gemini_grounding",
        name="gemini_grounding",
        output="screen",
        parameters=[
            {"color_topic_raw": "/camera/camera/color/image_raw"},
            {"color_rotated_topic": "/drone_perception/color/image_rotated"},
            {"depth_topic": "/camera/camera/aligned_depth_to_color/image_raw"},
            {"camera_info_topic": "/camera/camera/color/camera_info"},
            {"query_topic": "/drone_perception/object_query"},
            {"overlay_topic": "/drone_perception/ui_overlay"},
            {"result_topic": "/drone_perception/object_result"},
            {"rotate_180": True},
            {"depth_history_size": 30},
            {"max_sync_gap_sec": 0.10},
            {"patch_size": 7},
            {"min_depth_m": 0.15},
            {"max_depth_m": 8.0},
            {"map_frame": "map"},
        ],
    )

    mount_tf_node = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        name="camera_mount_tf",
        output="screen",
        arguments=[
            "0.0",
            "0.0",
            "-0.10",
            "0.0",
            "0.0",
            "3.141592653589793",
            "base_link",
            "camera_link",
        ],
    )

    return LaunchDescription(
        [
            start_realsense_arg,
            realsense_launch,
            mount_tf_node,
            gemini_grounding_node,
        ]
    )
