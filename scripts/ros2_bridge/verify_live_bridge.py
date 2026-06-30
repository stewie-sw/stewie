#!/usr/bin/env python3
"""Step 4 (gap W2): live ROS2 bridge verification -- command in, odom out, watchdog trip, transaction recorded.

HOST-GATED. This needs a ROS2 Jazzy host (rclpy). It is NOT runnable on a plain Debian/dev box; run it
inside the `stewie-ros2:latest` container (the same image make_ros2_node documents):

    docker run --rm -v "$PWD:/ws" -e PYTHONPATH=/ws stewie-ros2:latest \
        python3 scripts/ros2_bridge/verify_live_bridge.py

(rclpy loads via the image entrypoint sourcing /opt/ros/jazzy/setup.bash -- do NOT wrap in `bash -lc`.)

What it verifies end to end on the LIVE transport:
  1. a /cmd_vel Twist published by a peer node flows through make_ros2_node -> the SF-01 watchdog as a
     drive command (the ingress);
  2. /stewie/odom is published (the egress) so a Nav2/Autoware layer localizes off the same seam;
  3. when the cmd_vel stream STALLS past the dead-man, the SF-01 watchdog trips and auto-safes (the
     safety boundary);
  4. the session is committed to the canonical DT-01 world-state log via the SAME seam the SIM run uses
     (ros2_bridge.bridge_session_events -> WorldStateService.record_execution_event), so live telemetry
     produces world transactions exactly like every other transition.

The rclpy-free parts this relies on -- bridge_session_events, WorldStateService.record_execution_event
-- are unit-tested in stewie/bridge/test_bridge_world_log.py; only the rclpy TRANSPORT (1-3) is gated to
this container.
"""
from __future__ import annotations

import sys
import time

from stewie.bridge import rc_contract as RC
from stewie.bridge import ros2_bridge as B
from stewie.server.world_state import WorldStateService
from stewie.twin import versioned as vt


def _require_rclpy():
    try:
        import rclpy  # type: ignore[import-not-found]  # noqa: F401
        from geometry_msgs.msg import Twist  # type: ignore[import-not-found]  # noqa: F401
        from rclpy.node import Node  # type: ignore[import-not-found]  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "rclpy not installed: this LIVE verification is gated on a ROS2 Jazzy host. Run it inside the "
            "stewie-ros2:latest container (see this file's header). The rclpy-free seam it uses is unit-"
            "tested in stewie/bridge/test_bridge_world_log.py.") from e


def main(deadline_s: float = 2.0, drive_s: float = 1.5, stall_s: float = 3.0) -> int:
    _require_rclpy()
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.node import Node

    rclpy.init()
    backend = RC.RecordingBackend()                          # the watchdog target we can read after the run
    wd = RC.SafingWatchdog(backend, deadline_s=deadline_s)
    # a live sim plant so /stewie/odom actually advances under the commands (closed loop)
    bridge_node = B.make_ros2_node(wd, pose_source=B.sim_pose_source(RC.SimBackend(start_rc=(0.0, 0.0))))

    odom_seen = {"n": 0}

    class _Peer(Node):
        def __init__(self) -> None:
            super().__init__("verify_peer")
            self._pub = self.create_publisher(Twist, "/cmd_vel", 10)
            self.create_subscription(Odometry, "/stewie/odom", self._on_odom, 10)
            self._t = self.create_timer(0.1, self._tick)
            self._t0 = time.monotonic()

        def _on_odom(self, _msg) -> None:
            odom_seen["n"] += 1

        def _tick(self) -> None:
            # drive for drive_s, then stall (publish nothing) so the SF-01 dead-man trips
            if time.monotonic() - self._t0 < drive_s:
                m = Twist(); m.linear.x = 0.3
                self._pub.publish(m)

    peer = _Peer()
    exec_ = rclpy.executors.SingleThreadedExecutor()
    exec_.add_node(bridge_node)
    exec_.add_node(peer)
    t_end = time.monotonic() + drive_s + stall_s
    while time.monotonic() < t_end:
        exec_.spin_once(timeout_sec=0.1)

    tripped = any(type(c).__name__ == "Safe" for c in backend.commands)
    n_cmds = sum(1 for c in backend.commands if type(c).__name__ != "Safe")

    # commit the live session to the world-state log via the SAME seam the SIM run uses
    wss = WorldStateService(twin=_scratch_twin())
    events = B.bridge_session_events(backend.commands)
    for ev in events:
        wss.record_execution_event(provenance=f"LIVE bridge {ev.kind}: {ev.detail} [{ev.outcome}]",
                                   mission="live-teleop", site="haworth", body="moon", mission_t_s=ev.t_s)

    bridge_node.destroy_node(); peer.destroy_node(); rclpy.shutdown()

    ok = odom_seen["n"] > 0 and n_cmds > 0 and tripped and wss.transaction_count() == len(events)
    print(f"odom_msgs={odom_seen['n']} drive_cmds={n_cmds} watchdog_tripped={tripped} "
          f"world_transactions={wss.transaction_count()} chain_valid={wss.verify_chain()}")
    print("LIVE BRIDGE VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def _scratch_twin() -> vt.TwinStore:
    import numpy as np
    return vt.TwinStore(np.zeros((32, 32), dtype=float), cell_m=5.0)


if __name__ == "__main__":
    sys.exit(main())
