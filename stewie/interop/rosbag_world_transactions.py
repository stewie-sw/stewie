"""[REQ:BA-06] world-transaction events <-> rosbag2 interop (part of the BA-06 converter set; container-gated).

The DT-01 world log is a stream of WorldTransaction records (stewie.twin.envelope). This converts that event
stream to/from a rosbag2 bag: each transaction is serialized (its `asdict`, as JSON) into a std_msgs/String
message on a topic, and read back. The round-trip invariant is EVENT COUNT preserved: N transactions written
-> N read. The bag I/O needs rosbag2_py + rclpy (ROS), so it runs in the on-host ros2 container, not the
CPU-only CI -- its test skips cleanly there. The serialization half (WorldTransaction -> event dict -> JSON)
is pure stdlib and testable on-host.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

_TOPIC = "/world/transactions"


def world_transaction_to_event(txn: Any) -> dict:
    """A WorldTransaction (dataclass) -> a plain JSON-able event dict. Accepts an already-dict event too."""
    if is_dataclass(txn) and not isinstance(txn, type):
        return asdict(txn)
    return dict(txn)


def event_to_json(event: dict) -> str:
    return json.dumps(event, sort_keys=True)


def json_to_event(payload: str) -> dict:
    return json.loads(payload)


def write_events_to_rosbag(events: list[dict], bag_uri: str, topic: str = _TOPIC) -> int:
    """Write world-transaction events to a rosbag2 bag as std_msgs/String(JSON). Returns the count written.
    Container-gated (rosbag2_py + rclpy)."""
    import rosbag2_py
    from rclpy.serialization import serialize_message
    from std_msgs.msg import String

    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=bag_uri, storage_id="mcap"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr",
                                            output_serialization_format="cdr"))
    writer.create_topic(rosbag2_py.TopicMetadata(
        id=0, name=topic, type="std_msgs/msg/String", serialization_format="cdr"))
    n = 0
    for i, ev in enumerate(events):
        msg = String()
        msg.data = event_to_json(ev)
        writer.write(topic, serialize_message(msg), i)      # timestamp = index (monotonic ns)
        n += 1
    del writer                                              # close + flush the bag
    return n


def read_events_from_rosbag(bag_uri: str, topic: str = _TOPIC) -> list[dict]:
    """Read world-transaction events back from a rosbag2 bag. Container-gated."""
    import rosbag2_py
    from rclpy.serialization import deserialize_message
    from std_msgs.msg import String

    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=bag_uri, storage_id="mcap"),
                rosbag2_py.ConverterOptions(input_serialization_format="cdr",
                                            output_serialization_format="cdr"))
    out: list[dict] = []
    while reader.has_next():
        tp, data, _ts = reader.read_next()
        if tp == topic:
            out.append(json_to_event(deserialize_message(data, String).data))
    return out
