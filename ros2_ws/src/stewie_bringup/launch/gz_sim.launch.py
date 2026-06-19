"""[REQ:AS-06] Bring up the Gazebo IPEx sim seam: gz server (headless) + the lunar world, robot_state_
publisher from the gz overlay URDF, spawn from /robot_description, and the ros_gz bridge (gz_bridge.yaml).
Drives the AS-01 contract topics; the estimator sees only sensor topics (truth pose -> /stewie/truth/pose)."""
import os

import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node


def generate_launch_description():
    desc = get_package_share_directory("stewie_description")
    bringup = get_package_share_directory("stewie_bringup")
    world = os.path.join(desc, "worlds", "stewie_lunar.sdf")
    robot_description = xacro.process_file(
        os.path.join(desc, "urdf", "ipex.gazebo.xacro")).toxml()
    bridge_cfg = os.path.join(bringup, "config", "gz_bridge.yaml")

    return LaunchDescription([
        # gz server, headless (server-only -s, run -r, headless GL for camera sensors)
        ExecuteProcess(
            cmd=["gz", "sim", "-s", "-r", "--headless-rendering", "-v", "2", world],
            output="screen"),
        Node(package="robot_state_publisher", executable="robot_state_publisher",
             parameters=[{"robot_description": robot_description, "use_sim_time": True}],
             output="screen"),
        Node(package="ros_gz_sim", executable="create",
             arguments=["-topic", "robot_description", "-z", "0.30", "-name", "ipex"],
             output="screen"),
        Node(package="ros_gz_bridge", executable="parameter_bridge",
             parameters=[{"config_file": bridge_cfg, "use_sim_time": True}],
             output="screen"),
    ])
