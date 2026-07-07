#!/usr/bin/env python3
"""STEWIE read-only ROS2 telemetry feeder (RT-04 engine pane).

Runs in the host-net ros2 container (sees the rover's DDS graph directly). SUBSCRIBES to the
read-only telemetry topics and PUSHES each message as newline-delimited JSON to the bridge-side
collector's ingest port at 127.0.0.1:9091 (the collector publishes that port on the host loopback;
host-net container -> 127.0.0.1 -> published port always works, unlike container->host on the
bridge gateway which this host firewalls).

READ-ONLY BY CONSTRUCTION: this node creates ZERO publishers. It can only observe. There is no code
path from here (or from the browser it ultimately feeds) to /cmd_vel, /cmd/nav_goal, /cmd/safe or
any service, so the rover cannot be commanded through the RT-04 pane.
"""
import json
import socket
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from rosidl_runtime_py import message_to_ordereddict

from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu, JointState
from std_msgs.msg import String
from tf2_msgs.msg import TFMessage

INGEST_HOST = "127.0.0.1"
INGEST_PORT = 9091

# (topic, msg_type, ros_type_string) -- ALL read-only telemetry; NONE of the /cmd* command topics.
# /joint_states + /stewie/imu are the URDF-declared proprioception the MissionHUD renders as a faithful
# EZ-RASSOR/IPEx instrument (8 actuated joints + IMU attitude); joints/imu are CPU physics so they flow
# headless with NO GPU render. The 8 camera image channels + /stewie/perception/points are DEFERRED here:
# they are render-gated (GL/GPU) and the "Gazebo View" pane relays them through its OWN gzcam feeder
# (deploy/ros2/camera_feeder.py) -- not this telemetry feeder.
TOPICS = [
    ("/odom", Odometry, "nav_msgs/msg/Odometry"),
    ("/rover/state", String, "std_msgs/msg/String"),
    ("/rover/leg", String, "std_msgs/msg/String"),
    ("/tf", TFMessage, "tf2_msgs/msg/TFMessage"),
    ("/joint_states", JointState, "sensor_msgs/msg/JointState"),
    ("/stewie/imu", Imu, "sensor_msgs/msg/Imu"),
]

# Per-topic relay-rate cap (Hz). The gz JointStatePublisher runs at the physics step (~390 Hz) and the
# IMU at 50 Hz -- far faster than a HUD needs, and an uncapped relay would thrash the browser's per-frame
# React redraw. Cap the two proprioception streams at 20 Hz (plenty for an instrument readout); the
# original four topics stay UNCAPPED (unchanged behavior).
THROTTLE_HZ = {
    "/joint_states": 20.0,
    "/stewie/imu": 20.0,
}


class Feeder(Node):
    def __init__(self) -> None:
        super().__init__("rt04_telemetry_feeder")
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._last_sent: dict[str, float] = {}   # topic -> monotonic ts of last relayed frame (throttle)
        self._connect()
        # best-effort, keep-last sub so a reliable OR best-effort publisher both match
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=10)
        for name, mtype, tystr in TOPICS:
            self.create_subscription(mtype, name,
                                     lambda msg, n=name, t=tystr: self._on(n, t, msg), qos)
        self.get_logger().info("rt04 feeder up: read-only sub -> %s" % ", ".join(t for t, _, _ in TOPICS))

    def _connect(self) -> None:
        try:
            s = socket.create_connection((INGEST_HOST, INGEST_PORT), timeout=3)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = s
            self.get_logger().info("connected to collector ingest %s:%d" % (INGEST_HOST, INGEST_PORT))
        except OSError as e:
            self._sock = None
            self.get_logger().warn("ingest connect failed (%s); will retry" % e)

    def _on(self, topic: str, tystr: str, msg) -> None:
        cap = THROTTLE_HZ.get(topic)
        if cap:                                   # drop frames arriving faster than the per-topic cap
            now = time.monotonic()
            last = self._last_sent.get(topic, 0.0)
            if now - last < 1.0 / cap:
                return
            self._last_sent[topic] = now
        try:
            d = message_to_ordereddict(msg)
        except Exception as e:
            self.get_logger().warn("serialize %s failed: %s" % (topic, e))
            return
        line = (json.dumps({"topic": topic, "type": tystr, "msg": d}) + "\n").encode("utf-8")
        with self._lock:
            if self._sock is None:
                self._connect()
            if self._sock is None:
                return
            try:
                self._sock.sendall(line)
            except OSError:
                try:
                    self._sock.close()
                except OSError:
                    pass
                self._sock = None  # reconnect on next message


def main() -> None:
    rclpy.init()
    node = Feeder()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
