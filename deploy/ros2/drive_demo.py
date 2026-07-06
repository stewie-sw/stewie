#!/usr/bin/env python3
"""Operator-side one-shot: accelerate the sim and command a real nav goal so the rover DRIVES,
producing dynamic /odom + /tf + /rover/state telemetry for the RT-04 pane demo. This is a HOST-side
operator action (NOT the browser); the browser pane remains strictly read-only."""
import json
import sys
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float64


def main():
    tf = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    gr = float(sys.argv[2]) if len(sys.argv) > 2 else 92.0
    gc = float(sys.argv[3]) if len(sys.argv) > 3 else 104.0
    rclpy.init()
    n = Node("rt04_drive_demo")
    p_tf = n.create_publisher(Float64, "/sim/time_factor", 10)
    p_goal = n.create_publisher(String, "/cmd/nav_goal", 10)
    # let discovery settle so the executive node is a matched subscriber before we publish
    t0 = time.time()
    while time.time() - t0 < 2.0:
        rclpy.spin_once(n, timeout_sec=0.1)
    p_tf.publish(Float64(data=tf))
    goto = {"leg_id": 1, "goal_row": gr, "goal_col": gc, "v_max_mps": 0.3, "goal_radius_cells": 1.5}
    p_goal.publish(String(data=json.dumps(goto)))
    n.get_logger().info(f"published time_factor={tf} and GoTo {goto}")
    t0 = time.time()
    while time.time() - t0 < 1.5:
        rclpy.spin_once(n, timeout_sec=0.1)
    n.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
