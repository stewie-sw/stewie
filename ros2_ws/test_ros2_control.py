"""[REQ:BA-03] ros2_control is the single actuation authority for sim AND live: one transmission +
controller layer so Gazebo and a live robot both lower commands through the same controller_manager.
Host-side structural gate (the running controller_manager smoke is exercised in the ROS2/Gazebo container).
"""
import os

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_DESC = os.path.join(_HERE, "src", "stewie_description")
_R2C = os.path.join(_DESC, "urdf", "ros2_control.xacro")
_CTRL = os.path.join(_DESC, "config", "controllers.yaml")
_URDF = os.path.join(_DESC, "urdf", "ipex.urdf.xacro")
_GZ = os.path.join(_DESC, "urdf", "ipex.gazebo.xacro")

_ACTUATED = (
    "front_left_wheel_joint", "front_right_wheel_joint",
    "rear_left_wheel_joint", "rear_right_wheel_joint",
    "front_drum_arm_joint", "rear_drum_arm_joint",
    "front_drum_spin_joint", "rear_drum_spin_joint",
)


def test_ros2_control_declares_every_actuated_joint_with_a_command_interface():  # [REQ:BA-03]
    assert os.path.exists(_R2C), "ros2_control.xacro missing"
    t = open(_R2C).read()
    assert "<ros2_control" in t, "no <ros2_control> block"
    assert "GazeboSimSystem" in t or "gz_ros2_control" in t, "no Gazebo ros2_control hardware plugin"
    for j in _ACTUATED:
        assert f'name="{j}"' in t, f"ros2_control does not declare {j}"
    assert t.count("command_interface") >= len(_ACTUATED), "not every actuated joint has a command interface"


def test_controllers_yaml_has_manager_broadcaster_and_a_drive_controller():  # [REQ:BA-03]
    assert os.path.exists(_CTRL), "controllers.yaml missing"
    y = yaml.safe_load(open(_CTRL))
    cm = y.get("controller_manager", {}).get("ros__parameters", {})
    assert "update_rate" in cm, "controller_manager has no update_rate"
    blob = str(y)
    assert "joint_state_broadcaster" in blob, "no joint_state_broadcaster"
    assert "diff_drive_controller" in blob or "DiffDriveController" in blob, "no drive controller"
    # the drive controller drives the 4 skid-steer wheels (left pair + right pair)
    for w in ("front_left_wheel_joint", "rear_left_wheel_joint",
              "front_right_wheel_joint", "rear_right_wheel_joint"):
        assert w in blob, f"drive controller does not reference {w}"


def test_the_description_includes_ros2_control():  # [REQ:BA-03]
    combined = open(_URDF).read() + open(_GZ).read()
    assert "ros2_control.xacro" in combined, "ros2_control.xacro is not included by the URDF/gazebo xacro"
