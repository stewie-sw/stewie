"""SLAM-01 (truth-leak): the true rover pose must NOT ride the canonical SLAM `/tf` channel.

Audit SLAM-01 (Critical): bag_writer wrote the simulator's TRUE `map -> base_link` onto `/tf` -- the
exact topic a SLAM / Nav2 node reads for its OWN live estimate. A consumer reading `/tf` was handed
the answer, and an evaluator comparing the estimate to truth was comparing truth to truth. The fix
routes the true rover pose (and the computed AprilTag truth) to an EVALUATOR-ONLY namespace
(`/truth/...`), optionally in a SEPARATE bag, leaving the perception (SLAM-input) bag free of any
truth pose. These tests are the release gate.

The rosbags MCAP Writer is container-only (not in the repo venv), so the writer + typestore are
faked HERE to exercise OUR connection-routing + per-frame write-routing logic on the REAL fixture
capture (fixtures/000). The faking is of the serialization seam only; the inputs (sensors.json +
PNGs) are the real frozen fixture, and the routing decisions under test are entirely our code.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bag_writer  # noqa: E402

_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "000")

_TYPE_NAMES = [
    "builtin_interfaces/msg/Time", "std_msgs/msg/Header", "sensor_msgs/msg/Image",
    "sensor_msgs/msg/CameraInfo", "sensor_msgs/msg/RegionOfInterest", "tf2_msgs/msg/TFMessage",
    "geometry_msgs/msg/TransformStamped", "geometry_msgs/msg/Transform", "geometry_msgs/msg/Vector3",
    "geometry_msgs/msg/Quaternion", "geometry_msgs/msg/PoseStamped", "geometry_msgs/msg/Pose",
    "geometry_msgs/msg/Point",
]


class _FakeType:
    def __init__(self, name):
        self.__msgtype__ = name

    def __call__(self, **kw):
        return {"__type__": self.__msgtype__, **kw}


class _FakeTS:
    """Permissive typestore: types[name] builds a tagged dict; serialize_cdr returns bytes."""

    def __init__(self):
        self.types = {n: _FakeType(n) for n in _TYPE_NAMES}

    def serialize_cdr(self, msg, msgtype):
        return b"\x00"


class _FakeWriter:
    def __init__(self):
        self.topics: list[str] = []
        self.written: list[str] = []

    def add_connection(self, topic, msgtype, typestore=None):
        self.topics.append(topic)
        return ("conn", id(self), topic)

    def write(self, conn, t_ns, data):
        self.written.append(conn[2])


def _load():
    sensors = bag_writer._load_sensors(_FIX)
    left, right, baseline = bag_writer._resolve_stereo(sensors)
    return sensors, left, right, baseline


def test_forbidden_truth_topics_flags_evaluator_topics_in_perception_bag():
    # the gate names the evaluator-only truth topics; a perception bag carrying any of them fails
    assert bag_writer.forbidden_truth_topics(["/front_left/image_raw", "/tf", "/tf_static"]) == []
    leaky = bag_writer.forbidden_truth_topics(
        ["/front_left/image_raw", "/tf", bag_writer.TRUTH_POSE_TOPIC])
    assert leaky == [bag_writer.TRUTH_POSE_TOPIC]
    # the canonical estimate channel is /tf; the true rover pose must not be one of its messages
    assert "/tf" not in bag_writer.EVALUATOR_ONLY_TOPICS
    assert bag_writer.TRUTH_POSE_TOPIC in bag_writer.EVALUATOR_ONLY_TOPICS


def test_register_connections_two_bag_split_keeps_truth_out_of_perception():
    ts = _FakeTS()
    _sensors, left, right, _baseline = _load()
    perc, truth = _FakeWriter(), _FakeWriter()
    conns, truth_conns = bag_writer.register_connections(perc, ts, left, right, truth_writer=truth)
    # perception bag: sensors + the legitimate rig/landmark statics, NO truth pose
    assert "/front_left/image_raw" in perc.topics and "/front_left/camera_info" in perc.topics
    assert "/tf" in perc.topics and "/tf_static" in perc.topics
    assert bag_writer.forbidden_truth_topics(perc.topics) == [], \
        f"perception bag leaks truth topics: {bag_writer.forbidden_truth_topics(perc.topics)}"
    # evaluator bag: the true rover pose + the apriltag truth, on the /truth namespace
    assert bag_writer.TRUTH_POSE_TOPIC in truth.topics
    assert bag_writer.APRILTAG_TRUTH_TOPIC in truth.topics
    assert bag_writer.TRUTH_POSE_TOPIC in truth_conns


def test_write_frame_routes_true_rover_pose_to_evaluator_bag_not_tf():
    ts = _FakeTS()
    sensors, left, right, baseline = _load()
    perc, truth = _FakeWriter(), _FakeWriter()
    conns, truth_conns = bag_writer.register_connections(perc, ts, left, right, truth_writer=truth)
    bag_writer.write_frame(perc, ts, conns, _FIX, sensors, left, right, baseline,
                           0, 0, 0, truth_writer=truth, truth_conns=truth_conns)
    # the SLAM-input bag carries the images + statics but NEVER the truth pose
    assert "/front_left/image_raw" in perc.written and "/tf_static" in perc.written
    assert bag_writer.TRUTH_POSE_TOPIC not in perc.written
    assert bag_writer.APRILTAG_TRUTH_TOPIC not in perc.written
    # the true map->base_link rover pose is written ONLY to the evaluator bag's /truth channel
    assert bag_writer.TRUTH_POSE_TOPIC in truth.written
    assert bag_writer.APRILTAG_TRUTH_TOPIC in truth.written


def test_single_bag_mode_still_routes_truth_off_the_tf_channel():
    # back-compat: with no separate truth writer, truth still lands on /truth/* (never /tf), so a
    # SLAM node reading /tf is not handed the answer; the release gate still flags the shared bag.
    ts = _FakeTS()
    sensors, left, right, baseline = _load()
    w = _FakeWriter()
    conns, truth_conns = bag_writer.register_connections(w, ts, left, right)
    bag_writer.write_frame(w, ts, conns, _FIX, sensors, left, right, baseline,
                           0, 0, 0, truth_conns=truth_conns)
    # /tf carried no truth rover pose (it is the canonical estimate channel)
    assert bag_writer.TRUTH_POSE_TOPIC in w.written      # present, but on /truth/* not /tf
    assert bag_writer.TRUTH_POSE_TOPIC != "/tf"
    # the gate correctly flags a single shared bag for release (must use the 2-bag split)
    assert bag_writer.forbidden_truth_topics(w.topics) != []


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("ALL PASS")
