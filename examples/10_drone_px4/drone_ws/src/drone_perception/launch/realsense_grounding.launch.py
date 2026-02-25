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

    grounding_node = Node(
        package="drone_perception",
        executable="bbox_projection",
        name="bbox_projection",
        output="screen",
        parameters=[
            {"depth_topic": "/camera/camera/aligned_depth_to_color/image_raw"},
            {"camera_info_topic": "/camera/camera/color/camera_info"},
            {"map_frame": "map"},
            {"max_sync_gap_sec": 0.20},
            {"allow_stale_depth_fallback": True},
            {"bbox_input_rotated_180": True},
        ],
    )

    image_rotator_node = Node(
        package="drone_perception",
        executable="image_rotator",
        name="image_rotator",
        output="screen",
        parameters=[
            {"input_topic": "/camera/camera/color/image_raw"},
            {"output_topic": "/drone_perception/color/image_rotated"},
            {"rotate_180": True},
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
            image_rotator_node,
            grounding_node,
        ]
    )
