"""[REQ:BA-07] Phase-0 running-sim smoke bringup: the AS-06 gz_sim seam (gz server + lunar world +
robot_state_publisher + spawn + gz_bridge) PLUS RViz (stewie_rviz/mission.rviz) and rosbag2 recording of the
AS-01 contract topics. The container smoke run drives a short /cmd_vel and asserts (a) the contract topics
publish (IMU, wheel odom, camera, points), (b) the rover MOVES into the recorded bag, and (c) NO ground-truth
pose leaks into an estimator input -- truth stays on its own /stewie/truth/pose channel. Truth-denial of the
bridge itself is proven host-side by [REQ:AS-06] test_gz_bridge.py; this launch is the running-sim half."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node

# the AS-01 contract topics the bag records. The ground-truth pose is recorded too, but on its OWN
# /stewie/truth/pose channel -- the estimator never subscribes to it (truth-denial, [REQ:AS-06]).
RECORD_TOPICS = [
    "/clock", "/stewie/imu", "/stewie/wheel_odom", "/joint_states",
    "/stewie/perception/points", "/stewie/camera/front_left/image",
    "/stewie/truth/pose", "/cmd_vel",
]


def generate_launch_description():
    bringup = get_package_share_directory("stewie_bringup")
    rviz_share = get_package_share_directory("stewie_rviz")
    gz_launch = os.path.join(bringup, "launch", "gz_sim.launch.py")
    rviz_cfg = os.path.join(rviz_share, "rviz", "mission.rviz")
    bag_dir = os.environ.get("STEWIE_BA07_BAG", "/tmp/stewie_ba07_bag")

    return LaunchDescription([
        IncludeLaunchDescription(PythonLaunchDescriptionSource(gz_launch)),
        Node(package="rviz2", executable="rviz2", arguments=["-d", rviz_cfg],
             parameters=[{"use_sim_time": True}], output="screen"),
        ExecuteProcess(
            cmd=["ros2", "bag", "record", "-o", bag_dir, *RECORD_TOPICS],
            output="screen"),
    ])
