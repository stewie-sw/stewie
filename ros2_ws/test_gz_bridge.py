"""[REQ:AS-06] host-side gz<->ROS bridge gate: contract conformance + truth-denial (§25 Phase 4).

Verifies the ros_gz_bridge config bridges the expected sensor/command/clock topics to AS-01
boundary-contract ROS names with the right types and directions, and -- the AS-06 acceptance
clause 2 -- that the Gazebo ground-truth pose reaches ONLY a TRUTH_TOPICS channel and is never
bridged into an estimator input. The running-sim topic-publish smoke is container-gated."""
import os

import yaml

from stewie.bridge import autonomy_contract as AC

_HERE = os.path.dirname(os.path.abspath(__file__))
BRIDGE = os.path.join(_HERE, "src", "stewie_bringup", "config", "gz_bridge.yaml")
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
