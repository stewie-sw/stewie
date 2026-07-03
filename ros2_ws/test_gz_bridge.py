"""[REQ:AS-06] host-side gz<->ROS bridge gate: contract conformance + truth-denial (§25 Phase 4).

Verifies the ros_gz_bridge config bridges the expected sensor/command/clock topics to AS-01
boundary-contract ROS names with the right types and directions, and -- the AS-06 acceptance
clause 2 -- that the Gazebo ground-truth pose reaches ONLY a TRUTH_TOPICS channel and is never
bridged into an estimator input. The running-sim topic-publish smoke is container-gated."""
import os
import re

import yaml

from stewie.bridge import autonomy_contract as AC

_HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(_HERE, "src", "stewie_bringup", "config", "gz_bridge.yaml")
_DESC = os.path.join(_HERE, "src", "stewie_description")
_XACRO = os.path.join(_DESC, "urdf", "ipex.gazebo.xacro")
_WORLD = os.path.join(_DESC, "worlds", "stewie_lunar.sdf")
# gz source substrings that denote evaluation TRUTH (the simulator's exact state), not a sensor
_TRUTH_GZ_MARKERS = ("dynamic_pose", "/pose/info", "/pose_static")


def _bridge():
    with open(BRIDGE) as f:
        return yaml.safe_load(f)


def _norm(t):
    return t.replace("/msg/", "/")


def test_required_topics_bridged_to_contract_names():
    by_ros = {e["ros_topic_name"]: e for e in _bridge()}
    expected = {  # ros topic -> (direction, contract-or-special)
        "/cmd_vel": "ROS_TO_GZ",
        "/clock": "GZ_TO_ROS",
        "/joint_states": "GZ_TO_ROS",
        "/stewie/imu": "GZ_TO_ROS",
        "/stewie/wheel_odom": "GZ_TO_ROS",
        "/stewie/contact": "GZ_TO_ROS",
        "/tf": "GZ_TO_ROS",
        "/stewie/camera/front_left/image": "GZ_TO_ROS",
        "/stewie/camera/front_right/image": "GZ_TO_ROS",
        "/stewie/perception/points": "GZ_TO_ROS",
    }
    for topic, direction in expected.items():
        assert topic in by_ros, f"bridge missing {topic}"
        assert by_ros[topic]["direction"] == direction, f"{topic} wrong direction"
        assert topic in AC.TOPICS, f"{topic} is not an AS-01 contract topic"


def test_bridged_types_match_the_contract():
    for e in _bridge():
        rt = e["ros_topic_name"]
        if rt in AC.TOPICS:
            assert _norm(e["ros_type_name"]) == AC.TOPICS[rt].msg, \
                f"{rt}: bridge type {e['ros_type_name']} != contract {AC.TOPICS[rt].msg}"


def test_truth_pose_goes_only_to_a_truth_channel():
    for e in _bridge():
        gz = e["gz_topic_name"]
        if any(m in gz for m in _TRUTH_GZ_MARKERS):
            # a gz TRUTH source may bridge ONLY to an autonomy_contract TRUTH_TOPICS channel
            assert e["ros_topic_name"] in AC.TRUTH_TOPICS, \
                f"gz truth source {gz} bridged to non-truth ROS topic {e['ros_topic_name']}"


def test_no_estimator_input_is_sourced_from_gz_truth():
    # every topic any estimator-role node subscribes, that the sim provides, must NOT come from truth
    estimator_inputs = set()
    for n in AC.NODES.values():
        if n.role in AC.ESTIMATOR_ROLES:
            estimator_inputs.update(n.subscribes)
    for e in _bridge():
        if e["ros_topic_name"] in estimator_inputs:
            gz = e["gz_topic_name"]
            assert not any(m in gz for m in _TRUTH_GZ_MARKERS), \
                f"estimator input {e['ros_topic_name']} is sourced from gz truth {gz}"


def test_sim_does_not_bridge_to_the_localization_output_odom():
    # /stewie/odom is the localization ESTIMATE (produced by the node), never injected from the sim
    assert "/stewie/odom" not in {e["ros_topic_name"] for e in _bridge()}


def test_truth_channel_present_for_offline_scoring():
    # the truth pose IS bridged (to the truth channel) so the offline scorer has ground truth
    truth = [e for e in _bridge() if e["ros_topic_name"] in AC.TRUTH_TOPICS]
    assert truth and all(e["direction"] == "GZ_TO_ROS" for e in truth)


def _sim_side_topics():
    """Every Gazebo-side topic the sim publishes OR subscribes, per gz-transport conventions -- so a
    bridged `gz_topic_name` can be checked against a real endpoint:
    - every sensor/plugin `<topic>` / `<odom_topic>` / `<tf_topic>` value (verbatim -- these cover the
      diff-drive cmd_vel SUBSCRIBE + odom/tf, the imu/contact/camera sensors, and the lidar base),
    - a `gpu_lidar` sensor ALSO publishes its PointCloudPacked on `<topic>/points` (this is the key
      convention: gz_bridge sourcing `/model/ipex/perception/points` from a lidar whose `<topic>` is
      `/model/ipex/perception` is CORRECT, not a mismatch),
    - the Physics / JointStatePublisher / PosePublisher system plugins publish `/clock`,
      `/world/<world>/model/<model>/joint_state`, and `/world/<world>/pose/info`.
    """
    xac = open(_XACRO, encoding="utf-8").read()
    topics = set(re.findall(r"<(?:topic|odom_topic|tf_topic)>([^<]+)</", xac))
    for m in re.finditer(r'<sensor[^>]*type="gpu_lidar"[^>]*>(.*?)</sensor>', xac, re.S):
        t = re.search(r"<topic>([^<]+)</", m.group(1))
        if t:
            topics.add(t.group(1).strip() + "/points")
    wm = re.search(r'<world\s+name="([^"]+)"', open(_WORLD, encoding="utf-8").read())
    world = wm.group(1) if wm else "stewie_lunar"
    model = "ipex"
    topics.update({"/clock",
                   f"/world/{world}/model/{model}/joint_state",
                   f"/world/{world}/pose/info"})
    return topics


def test_every_bridged_gz_topic_has_a_sim_endpoint():  # [REQ:BA-01]
    # BA-01: the audit flagged gz_bridge sourcing `/model/ipex/perception/points` while the xacro lidar
    # sets `<topic>/model/ipex/perception` as a possible mismatch. It is NOT: a gpu_lidar publishes its
    # cloud on `<topic>/points`. This gate encodes that convention and FAILS on a real orphan -- a
    # bridged gz topic with no sensor/plugin/system endpoint.
    endpoints = _sim_side_topics()
    for e in _bridge():
        gz = e["gz_topic_name"]
        assert gz in endpoints, (
            f"gz_bridge sources {gz!r} but no sensor/plugin/system publisher or subscriber emits it "
            f"(gpu_lidar clouds are on <topic>/points; check ipex.gazebo.xacro / stewie_lunar.sdf)")
