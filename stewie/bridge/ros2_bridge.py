"""ROS2 autonomy seam (Phase A, PRD §16.7 / P20): the bridge where a ROS2 autonomy layer
(Nav2/Autoware-style) drives the STEWIE rover. A geometry_msgs/Twist on ``/cmd_vel`` is translated
into the RC command contract (rc_contract.GoTo/Safe) and submitted THROUGH the SF-01 SafingWatchdog,
so a cmd_vel stream that stalls trips the dead-man and safes the rover -- the audit's safety boundary
holds over the ROS2 path too. Telemetry (rc_contract.Pose) maps back to a ROS2 odometry-shaped record.

rclpy is OPTIONAL -- the codebase's gymnasium-/PyChrono-optional pattern. The pure translation
(``twist_to_command``/``pose_to_odom``) and the watchdog-routed ingress (``RcBridge``) are import-free
and fully tested without ROS2; the live ``rclpy`` Node (``make_ros2_node``) activates only on a ROS2
Jazzy host. Topic/message conventions follow Nav2/Autoware so the autonomy layer is swappable: subscribe
``/cmd_vel`` (geometry_msgs/Twist), publish ``/stewie/odom`` (nav_msgs/Odometry-shaped)."""
from __future__ import annotations

import math

from stewie.bridge import frames as FR
from stewie.bridge import rc_contract as RC

_EPS = 1e-3
# The cmd_vel carrot is a MOVING short-horizon goal re-projected each twist, not a discrete waypoint:
# the default 1-cell GoTo arrival radius would SWALLOW a typical projection (e.g. 1 m/s x 1 s = 1 cell)
# so the rover would register "already arrived" and never move. A tight radius keeps the carrot ahead.
_GOAL_RADIUS_CELLS = 0.1


def twist_to_command(linear_x: float, angular_z: float, *, pose: RC.Pose, horizon_s: float = 1.0,
                     cell_m: float = RC.DEFAULT_CELL_M, leg_id: int = 0):
    """Translate a ROS2 Twist (cmd_vel: forward m/s + yaw-rate rad/s) into an RC command, given the
    current Pose. A (near-)zero twist -> Safe(operator). Otherwise project the unicycle forward by
    ``horizon_s`` to a short-horizon goal cell and drive to it at v_max=|linear_x|. (RC is goal-based,
    so a velocity command becomes the standard short-horizon-goal a goal tracker would chase; the
    SF-01 watchdog re-safes if the next twist does not arrive in time, so the horizon never runs away.)"""
    if abs(linear_x) < _EPS and abs(angular_z) < _EPS:
        return RC.Safe(reason=RC.SAFE_REASON_OPERATOR)
    yaw = float(pose.yaw_rad) + float(angular_z) * float(horizon_s)      # heading after the commanded turn
    dist_m = float(linear_x) * float(horizon_s)
    dcol = dist_m * math.cos(yaw) / float(cell_m)                        # REP-103 +x -> +col (frames.py)
    drow = -dist_m * math.sin(yaw) / float(cell_m)                       # REP-103 +y (left) -> -row (frames.py)
    return RC.GoTo(leg_id=leg_id, goal_row=float(pose.row) + drow,
                   goal_col=float(pose.col) + dcol, v_max_mps=abs(float(linear_x)),
                   goal_radius_cells=_GOAL_RADIUS_CELLS)


def yaw_to_quaternion(yaw: float):
    """Flat (z-up) yaw -> a unit quaternion (x, y, z, w) for geometry_msgs/Quaternion. Lunar SURFACE nav
    here is planar, so roll = pitch = 0 and only the yaw half-angle populates z/w (w=cos(y/2), z=sin(y/2));
    a consumer recovers yaw = 2*atan2(z, w)."""
    h = 0.5 * float(yaw)
    return (0.0, 0.0, math.sin(h), math.cos(h))


def pose_to_odom(pose: RC.Pose, *, cell_m: float = RC.DEFAULT_CELL_M) -> dict:
    """Map an RC Pose telemetry sample to a ROS2-odometry-shaped record (nav_msgs/Odometry fields), in
    REP-103 METRES via frames.py -- THE single conversion site. Position is x = col*cell_m and
    y = -row*cell_m (sim +row is the rover's right; REP-103 +y is left), so a Nav2/Autoware consumer reads
    real metres in the map frame, not raw grid cells (the prior col->x / row->y shortcut published cells
    under a metric frame with a flipped y -- a scale + handedness defect). Carries yaw's quaternion + the
    STEWIE proprioception (slip/sinkage/entrapment). make_ros2_node builds the actual Odometry from this."""
    rp = FR.grid_pose_to_rep103((pose.row, pose.col), float(pose.yaw_rad), cell_m=float(cell_m))
    return {"frame_id": "map", "x": rp.x, "y": rp.y,
            "yaw": float(pose.yaw_rad), "qz": rp.quaternion_xyzw[2], "qw": rp.quaternion_xyzw[3],
            "v": float(pose.v_achieved_mps), "slip": float(pose.slip),
            "sinkage_m": float(pose.sinkage_m), "entrapped": bool(pose.entrapped)}


def ros_odom_ingest_body(*, x_m: float, y_m: float, yaw_rad: float = 0.0,
                         slip: float | None = None, soc: float | None = None,
                         mode: str | None = None, frame: dict | None = None) -> dict:
    """#144 (producer side): the /rc/ros_odom body the rover node POSTs so the cockpit live drive-map
    can render the ROS rover. REP-103 metres (already the cockpit frame). Matches the cockpit's
    RosOdomIngest contract field-for-field (a test pins that), so the producer cannot drift from the
    consumer. slip/soc are clamped to [0, 1]; only finite values are included. mode (tier-2) is the
    rover's control mode (idle|cmd_vel|goal|safe), so the console shows when it is under autonomy."""
    body: dict = {"x_m": float(x_m), "y_m": float(y_m), "yaw_rad": float(yaw_rad)}
    if slip is not None and math.isfinite(slip):
        body["slip"] = max(0.0, min(1.0, float(slip)))
    if soc is not None and math.isfinite(soc):
        body["soc"] = max(0.0, min(1.0, float(soc)))
    if mode is not None:
        body["mode"] = str(mode)[:16]
    if frame is not None and isinstance(frame.get("dem"), str) and "dem_origin" in frame:
        body["frame"] = {"dem": str(frame["dem"])[:32], "cell_m": float(frame["cell_m"]),
                         "dem_origin": [float(frame["dem_origin"][0]), float(frame["dem_origin"][1])]}
    return body


def post_odom_to_cockpit(base_url: str, body: dict, *, api_key: str | None = None,
                         timeout_s: float = 0.5) -> int:
    """#144 (producer side): POST one /rc/ros_odom frame to the cockpit ingest. stdlib urllib only -- the
    ROS2 container need not carry `requests`. Returns the HTTP status; raises urllib.error.URLError on a
    network failure so the caller can swallow it (a telemetry-mirror outage must never disrupt control)."""
    import json as _json
    import urllib.request
    data = _json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key
    req = urllib.request.Request(base_url.rstrip("/") + "/rc/ros_odom", data=data,
                                 method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:   # noqa: S310 (fixed scheme, our URL)
        return int(resp.status)


def sim_pose_source(backend):
    """A ``pose_source`` for make_ros2_node that DRAINS a polling RCBackend (e.g. rc_contract.SimBackend)
    each odom tick and returns its latest Pose -- so a /cmd_vel goal actually advances the conserved sim
    and the resulting motion publishes on /stewie/odom (the closed cmd_vel -> sim -> /stewie/odom loop).
    Returns None until the first Pose. No fabricated motion: the Pose is whatever the backend produced
    from the commands the SF-01 watchdog forwarded to it. Pass the SAME backend instance the watchdog
    targets, so commands and telemetry share one sim."""
    state = {"last": None}

    def _src():
        for t in backend.poll():
            if getattr(t, "kind", None) == "pose":
                state["last"] = t
        return state["last"]

    return _src


class RcBridge:
    """The rclpy-OPTIONAL bridge core (testable without ROS2). ``on_cmd_vel`` translates a Twist using
    the last-known pose and submits it through the SF-01 watchdog; ``tick`` advances the dead-man so a
    stalled cmd_vel stream auto-safes; ``update_pose`` keeps the projection anchored to live telemetry."""

    def __init__(self, watchdog: RC.SafingWatchdog, *, horizon_s: float = 1.0,
                 cell_m: float = RC.DEFAULT_CELL_M) -> None:
        self._wd = watchdog
        self._horizon_s = float(horizon_s)
        self._cell_m = float(cell_m)
        self._pose = RC.Pose(leg_id=0, row=0.0, col=0.0)

    def update_pose(self, pose: RC.Pose) -> None:
        self._pose = pose

    def pose_odom(self) -> dict:
        """The bridge's current pose as a ROS2-odometry-shaped record -- the egress the live node
        publishes on /stewie/odom each tick (the perceive side of the seam, for Nav2/Autoware)."""
        return pose_to_odom(self._pose, cell_m=self._cell_m)

    def on_cmd_vel(self, linear_x: float, angular_z: float, *, now: float):
        """Translate one /cmd_vel Twist and submit it through the SF-01 watchdog (which feeds the
        dead-man). Returns the RC command submitted."""
        cmd = twist_to_command(linear_x, angular_z, pose=self._pose,
                               horizon_s=self._horizon_s, cell_m=self._cell_m)
        self._wd.submit(cmd, now=now)
        return cmd

    def tick(self, *, now: float) -> bool:
        """SF-01: advance the dead-man. Returns True (and auto-SAFEs the backend once) if the cmd_vel
        stream has stalled past the watchdog deadline."""
        return self._wd.tick(now=now)


def make_ros2_node(watchdog: RC.SafingWatchdog, *, cmd_vel_topic: str = "/cmd_vel",
                   odom_topic: str = "/stewie/odom", horizon_s: float = 1.0,
                   cell_m: float = RC.DEFAULT_CELL_M, pose_source=None, odom_rate_hz: float = 10.0):
    """Construct the LIVE rclpy Node (subscribes cmd_vel, ticks the SF-01 dead-man on a timer, publishes
    odom). Gated: raises RuntimeError if rclpy is absent -- the live node needs a ROS2 Jazzy host; the
    translation + RcBridge above run and are tested without it. (Phase A delivers the full seam: the
    cmd_vel ingress AND the /stewie/odom egress.)

    ``pose_source`` (optional) is a callable -> RC.Pose | None, called each odom tick to refresh the
    bridge from LIVE telemetry (the drive loop / estimator); without it the node republishes the last
    pose set via ``update_pose`` -- no fabricated motion is ever invented. ``odom_rate_hz`` sets the
    /stewie/odom publish rate (nav_msgs/Odometry, frame_id=map: REP-103 metres x=col*cell_m, y=-row*cell_m
    via frames.py, yaw quaternion, achieved speed) so a Nav2/Autoware layer localizes off the same seam.

    RUN-VERIFIED on the `stewie-ros2:latest` ROS2 Jazzy container:
      - 2026-06-16 (ingress): a published /cmd_vel Twist (0.25 m/s, 0.1 rad/s) flows through to the SF-01
        watchdog as the expected GoTo (goal ~0.25 cells ahead = the 1 s-horizon projection).
      - 2026-06-17 (egress, SUPERSEDED 2026-06-24): the original run published x=9, y=4 for
        Pose(row=4, col=9) -- raw grid cells under a metric frame with a flipped y, the scale+handedness
        defect this seam now fixes. The corrected contract (frames.py REP-103 metres) publishes
        x=col*cell_m, y=-row*cell_m; RE-VERIFY on the stewie-ros2:latest container after this change.
      - 2026-06-17 (CLOSED LOOP): watchdog target = SimBackend, pose_source = sim_pose_source(backend);
        a sustained /cmd_vel (1 m/s) drove the sim forward on /stewie/odom x 0.10 -> 2.40 cells over 2.6 s
        -- cmd_vel -> SF-01 -> sim -> /stewie/odom closes end to end on live ROS2.
    Reproduce (ingress):
        docker run --rm -v "$PWD:/ws" -e PYTHONPATH=/ws stewie-ros2:latest python3 -c \\
          "from stewie.bridge import ros2_bridge as B, rc_contract as RC; \\
           B.make_ros2_node(RC.SafingWatchdog(RC.RecordingBackend()))"
    (rclpy loads via the image entrypoint sourcing /opt/ros/jazzy/setup.bash -- do NOT `bash -lc`.)"""
    try:
        import rclpy  # type: ignore[import-not-found]
        from geometry_msgs.msg import Twist  # type: ignore[import-not-found]
        from nav_msgs.msg import Odometry  # type: ignore[import-not-found]
        from rclpy.node import Node  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "rclpy not installed: the live ROS2 node is gated on a ROS2 Jazzy host. The pure translation "
            "(twist_to_command/pose_to_odom) and the SF-01-routed ingress (RcBridge) run without it.") from e

    bridge = RcBridge(watchdog, horizon_s=horizon_s, cell_m=cell_m)

    class _StewieRcNode(Node):
        def __init__(self) -> None:
            super().__init__("stewie_rc_bridge")
            self._bridge = bridge
            self.create_subscription(Twist, cmd_vel_topic, self._on_twist, 10)
            self._odom_pub = self.create_publisher(Odometry, odom_topic, 10)
            self.create_timer(0.1, self._on_tick)                       # SF-01 dead-man cadence
            self.create_timer(1.0 / float(odom_rate_hz), self._on_odom)  # /stewie/odom egress

        def _now(self) -> float:
            return self.get_clock().now().nanoseconds * 1e-9

        def _on_twist(self, msg) -> None:
            self._bridge.on_cmd_vel(msg.linear.x, msg.angular.z, now=self._now())

        def _on_tick(self) -> None:
            self._bridge.tick(now=self._now())

        def _on_odom(self) -> None:
            if pose_source is not None:                                 # refresh from LIVE telemetry (no fabricated motion)
                p = pose_source()
                if p is not None:
                    self._bridge.update_pose(p)
            od = self._bridge.pose_odom()
            msg = Odometry()
            msg.header.frame_id = od["frame_id"]
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.pose.pose.position.x = od["x"]
            msg.pose.pose.position.y = od["y"]
            msg.pose.pose.orientation.z = od["qz"]
            msg.pose.pose.orientation.w = od["qw"]
            msg.twist.twist.linear.x = od["v"]                          # achieved forward speed (map frame)
            self._odom_pub.publish(msg)

    if not rclpy.ok():
        rclpy.init()
    return _StewieRcNode()


def main(argv=None) -> int:
    """Console entry ``stewie-ros2-bridge``: LAUNCH the live autonomy-seam node and spin it as a service.
    Subscribes /cmd_vel, ticks the SF-01 dead-man, publishes /stewie/odom from the conserved SimBackend
    (a real terramechanics backend swaps in via the RCBackend seam without touching this). Gated: needs a
    ROS2 Jazzy host (make_ros2_node raises RuntimeError otherwise). RUN-VERIFIED as a background process on
    stewie-ros2:latest (2026-06-17): a probe published /cmd_vel and read the rover driving on /stewie/odom."""
    import argparse

    from stewie.bridge import rc_contract as RC

    ap = argparse.ArgumentParser(prog="stewie-ros2-bridge",
                                 description="STEWIE ROS2 autonomy-seam bridge (cmd_vel <-> /stewie/odom, SF-01).")
    ap.add_argument("--cmd-vel-topic", default="/cmd_vel")
    ap.add_argument("--odom-topic", default="/stewie/odom")
    ap.add_argument("--deadline-s", type=float, default=5.0, help="SF-01 dead-man timeout")
    ap.add_argument("--horizon-s", type=float, default=1.0, help="cmd_vel short-horizon projection")
    ap.add_argument("--cell-m", type=float, default=RC.DEFAULT_CELL_M,
                    help="grid resolution shared across the seam (default = the Moon LOLA DEM cell)")
    ap.add_argument("--odom-rate-hz", type=float, default=10.0)
    args = ap.parse_args(argv)

    be = RC.SimBackend(start_rc=(0.0, 0.0), cell_m=args.cell_m, dt_s=1.0 / args.odom_rate_hz)
    wd = RC.SafingWatchdog(be, deadline_s=args.deadline_s)
    node = make_ros2_node(wd, cmd_vel_topic=args.cmd_vel_topic, odom_topic=args.odom_topic,
                          horizon_s=args.horizon_s, cell_m=args.cell_m,
                          pose_source=sim_pose_source(be), odom_rate_hz=args.odom_rate_hz)
    import rclpy  # present: make_ros2_node above already gated on it
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
