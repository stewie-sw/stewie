"""[REQ:AS-06] host-side gz sim-artifact gate: the world/model-overlay/launch are well-formed and the
model's declared gz topics match the bridge (§25 Phase 4). The running-sim publish smoke is the
container-gated half (deploy/ros2/Dockerfile.gazebo); this asserts the artifacts are consistent first."""
import os
import re

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(_HERE, "src")
WORLD = os.path.join(SRC, "stewie_description", "worlds", "stewie_lunar.sdf")
OVERLAY = os.path.join(SRC, "stewie_description", "urdf", "ipex.gazebo.xacro")
LAUNCH = os.path.join(SRC, "stewie_bringup", "launch", "gz_sim.launch.py")
BRIDGE = os.path.join(SRC, "stewie_bringup", "config", "gz_bridge.yaml")


def _read(p):
    with open(p) as f:
        return f.read()


def test_world_has_lunar_gravity_and_required_systems():
    w = _read(WORLD)
    assert "<gravity>0 0 -1.62</gravity>" in w, "world gravity must be lunar 1.62 m/s^2"
    for sysname in ("Physics", "SceneBroadcaster", "Sensors", "Imu"):
        assert sysname in w, f"world missing gz system {sysname}"


def test_overlay_includes_the_single_source_urdf():
    o = _read(OVERLAY)
    assert "ipex.urdf.xacro" in o and "xacro:include" in o


def test_diffdrive_groups_the_four_urdf_wheel_joints():
    o = _read(OVERLAY)
    joints = set(re.findall(r"<(?:left|right)_joint>(\w+)</(?:left|right)_joint>", o))
    assert joints == {"front_left_wheel_joint", "rear_left_wheel_joint",
                      "front_right_wheel_joint", "rear_right_wheel_joint"}, joints


def test_overlay_has_imu_and_front_stereo_cameras():
    o = _read(OVERLAY)
    assert 'type="imu"' in o
    assert o.count('type="camera"') == 2


def test_overlay_gz_topics_match_the_bridge():
    o = _read(OVERLAY)
    bridge = {e["gz_topic_name"] for e in yaml.safe_load(_read(BRIDGE))}
    # every absolute gz topic the model declares must be a bridge gz endpoint
    declared = set(re.findall(r"<(?:topic|odom_topic|tf_topic)>(/[\w/]+)</", o))
    missing = declared - bridge
    assert not missing, f"model declares gz topics not in the bridge: {missing}"
    # the command + key sensor topics specifically
    for t in ("/model/ipex/cmd_vel", "/model/ipex/odometry", "/model/ipex/tf", "/model/ipex/imu",
              "/model/ipex/camera/front_left/image", "/model/ipex/camera/front_right/image"):
        assert t in declared and t in bridge, f"{t} not consistently declared+bridged"


def test_launch_wires_world_spawn_and_bridge():
    lx = _read(LAUNCH)
    assert "stewie_lunar.sdf" in lx
    assert "ipex.gazebo.xacro" in lx
    assert "robot_state_publisher" in lx
    assert "ros_gz_sim" in lx and "create" in lx          # spawn from /robot_description
    assert "ros_gz_bridge" in lx and "gz_bridge.yaml" in lx
    assert "robot_description" in lx
