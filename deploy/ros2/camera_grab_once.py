#!/usr/bin/env python3
"""One-shot Gazebo camera frame grab (render-verification helper, READ-ONLY).

Subscribes to a single sensor_msgs/msg/Image camera topic, waits for ONE real frame, and writes it
as a binary PPM (P6) to the given path. Zero publishers -> observe-only. Stdlib + rclpy only (no
cv_bridge/PIL): a raw rgb8 image is width*height*3 bytes, which PPM stores verbatim.
"""
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image


def main() -> int:
    topic = sys.argv[1] if len(sys.argv) > 1 else "/stewie/camera/front_left/image"
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/cam_frame.ppm"
    rclpy.init()
    node = Node("camera_grab_once")
    got = {}
    qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                     durability=DurabilityPolicy.VOLATILE,
                     history=HistoryPolicy.KEEP_LAST, depth=1)

    def cb(msg: Image) -> None:
        if "m" not in got:
            got["m"] = msg

    node.create_subscription(Image, topic, cb, qos)
    # spin up to ~20 s for a frame
    end = node.get_clock().now().nanoseconds + 20 * 10**9
    while rclpy.ok() and "m" not in got and node.get_clock().now().nanoseconds < end:
        rclpy.spin_once(node, timeout_sec=0.5)
    node.destroy_node()
    rclpy.shutdown()
    if "m" not in got:
        print(f"NO FRAME on {topic}", flush=True)
        return 2
    msg = got["m"]
    enc = msg.encoding
    data = bytes(msg.data)
    print(f"FRAME {msg.width}x{msg.height} enc={enc} step={msg.step} bytes={len(data)}", flush=True)
    # rgb8 -> PPM verbatim; bgr8 -> swap; else bail honestly.
    px = data
    if enc == "bgr8":
        ba = bytearray(data)
        ba[0::3], ba[2::3] = data[2::3], data[0::3]
        px = bytes(ba)
    elif enc not in ("rgb8",):
        print(f"UNSUPPORTED encoding {enc}", flush=True)
        return 3
    with open(out, "wb") as f:
        f.write(f"P6\n{msg.width} {msg.height}\n255\n".encode())
        f.write(px)
    print(f"WROTE {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
