from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_perception = LaunchConfiguration("use_perception")
    force_tf_send_true = TimerAction(
        period=2.0,
        actions=[
            ExecuteProcess(
                cmd=[
                    "bash",
                    "-lc",
                    "for i in {1..20}; do "
                    "ros2 param set /mavros/local_position tf.send true && exit 0; "
                    "sleep 0.5; "
                    "done; exit 1",
                ],
                output="screen",
            )
        ],
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "use_perception",
                default_value="false",
                description="Launch static bbox projection service node",
            ),
            # MAVROS for PX4 SITL
            Node(
                package="mavros",
                executable="mavros_node",
                output="screen",
                parameters=[
                    {"fcu_url": "udp://:14540@127.0.0.1:14557"},
                    {"system_id": 1},
                    {"component_id": 1},
                    {"target_system_id": 1},
                    {"target_component_id": 1},
                ],
            ),
            force_tf_send_true,
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
