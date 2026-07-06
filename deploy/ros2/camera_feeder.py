#!/usr/bin/env python3
"""STEWIE read-only Gazebo CAMERA feeder (RT-03 Gazebo view pane).

Runs alongside the headless gz-sim render (SAME container / SAME ROS graph). SUBSCRIBES to ONE
rendered camera image topic (a sensor_msgs/msg/Image from the ros_gz bridge), downscales +
JPEG-encodes each frame, and PUSHES it as newline-delimited JSON (base64 JPEG) to the RT-04
collector's ingest port at 127.0.0.1:9091 -- the exact same durable relay the RT-04 telemetry pane
uses. The collector re-broadcasts it over the read-only rosbridge WS as a synthetic image topic that
the browser Gazebo pane renders into an <img>. nginx / collector are unchanged.

READ-ONLY BY CONSTRUCTION: this node creates ZERO publishers and holds ZERO ROS publishers -- it can
only observe the rendered image. There is no code path from here (or the browser it feeds) to
/cmd_vel, /cmd/nav_goal, /cmd/safe, or any service, so the rover cannot be commanded through the
RT-03 pane. It is a one-way image relay: pixels out, nothing in. Sole-egress / no-command-authority
preserved, identical to the RT-04 telemetry feeder.
"""
import base64
import io
import json
import os
import socket
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image
from PIL import Image as PILImage

INGEST_HOST = os.environ.get("STEWIE_INGEST_HOST", "127.0.0.1")
INGEST_PORT = int(os.environ.get("STEWIE_INGEST_PORT", "9091"))
IN_TOPIC = os.environ.get("STEWIE_CAM_TOPIC", "/stewie/camera/front_left/image")
OUT_TOPIC = os.environ.get("STEWIE_CAM_OUT_TOPIC", "/stewie/camera/front_left/jpeg")
OUT_WIDTH = int(os.environ.get("STEWIE_CAM_WIDTH", "512"))   # downscale target width (px)
JPEG_Q = int(os.environ.get("STEWIE_CAM_JPEG_Q", "55"))
PUSH_HZ = float(os.environ.get("STEWIE_CAM_HZ", "2.0"))       # throttle: frames pushed per second
OUT_TYPE = "stewie/CameraFrameJPEG"


class CameraFeeder(Node):
    def __init__(self) -> None:
        super().__init__("rt03_camera_feeder")
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._latest: Image | None = None
        self._latest_lock = threading.Lock()
        self._connect()
        # best-effort keep-last so a reliable OR best-effort image publisher both match
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         durability=DurabilityPolicy.VOLATILE,
                         history=HistoryPolicy.KEEP_LAST, depth=1)
        self.create_subscription(Image, IN_TOPIC, self._on_image, qos)
        self.create_timer(1.0 / max(PUSH_HZ, 0.1), self._tick)   # throttle push rate
        self.get_logger().info(
            "rt03 camera feeder up: read-only sub %s -> jpeg %s @ %.1f Hz (w=%d q=%d)"
            % (IN_TOPIC, OUT_TOPIC, PUSH_HZ, OUT_WIDTH, JPEG_Q))

    def _connect(self) -> None:
        try:
            s = socket.create_connection((INGEST_HOST, INGEST_PORT), timeout=3)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._sock = s
            self.get_logger().info("connected to collector ingest %s:%d" % (INGEST_HOST, INGEST_PORT))
        except OSError as e:
            self._sock = None
            self.get_logger().warn("ingest connect failed (%s); will retry" % e)

    def _on_image(self, msg: Image) -> None:
        with self._latest_lock:
            self._latest = msg

    def _tick(self) -> None:
        with self._latest_lock:
            msg = self._latest
            self._latest = None
        if msg is None:
            return
        try:
            frame = self._encode(msg)
        except Exception as e:  # a malformed frame must never take the feeder down
            self.get_logger().warn("encode failed: %s" % e)
            return
        line = (json.dumps({"topic": OUT_TOPIC, "type": OUT_TYPE, "msg": frame}) + "\n").encode("utf-8")
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
                self._sock = None

    def _encode(self, msg: Image) -> dict:
        enc = msg.encoding
        raw = bytes(msg.data)
        if enc == "rgb8":
            im = PILImage.frombytes("RGB", (msg.width, msg.height), raw)
        elif enc == "bgr8":
            im = PILImage.frombytes("RGB", (msg.width, msg.height), raw)
            b, g, r = im.split()
            im = PILImage.merge("RGB", (r, g, b))
        elif enc in ("mono8", "8UC1"):
            im = PILImage.frombytes("L", (msg.width, msg.height), raw).convert("RGB")
        else:
            raise ValueError("unsupported encoding %s" % enc)
        if OUT_WIDTH and im.width > OUT_WIDTH:
            h = max(1, round(im.height * OUT_WIDTH / im.width))
            im = im.resize((OUT_WIDTH, h))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=JPEG_Q)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        return {"format": "jpeg", "data": b64, "width": im.width, "height": im.height,
                "src_topic": IN_TOPIC, "src_w": msg.width, "src_h": msg.height, "stamp": stamp}


def main() -> None:
    rclpy.init()
    node = CameraFeeder()
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
