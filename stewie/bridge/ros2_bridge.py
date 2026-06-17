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

from stewie.bridge import rc_contract as RC

_EPS = 1e-3


def twist_to_command(linear_x: float, angular_z: float, *, pose: RC.Pose, horizon_s: float = 1.0,
                     cell_m: float = 1.0, leg_id: int = 0):
    """Translate a ROS2 Twist (cmd_vel: forward m/s + yaw-rate rad/s) into an RC command, given the
    current Pose. A (near-)zero twist -> Safe(operator). Otherwise project the unicycle forward by
    ``horizon_s`` to a short-horizon goal cell and drive to it at v_max=|linear_x|. (RC is goal-based,
    so a velocity command becomes the standard short-horizon-goal a goal tracker would chase; the
    SF-01 watchdog re-safes if the next twist does not arrive in time, so the horizon never runs away.)"""
    if abs(linear_x) < _EPS and abs(angular_z) < _EPS:
        return RC.Safe(reason=RC.SAFE_REASON_OPERATOR)
    yaw = float(pose.yaw_rad) + float(angular_z) * float(horizon_s)      # heading after the commanded turn
    dist_m = float(linear_x) * float(horizon_s)
    dcol = dist_m * math.cos(yaw) / float(cell_m)                        # +x == column, along the heading
    drow = dist_m * math.sin(yaw) / float(cell_m)                        # +y == row
    return RC.GoTo(leg_id=leg_id, goal_row=float(pose.row) + drow,
                   goal_col=float(pose.col) + dcol, v_max_mps=abs(float(linear_x)))


def yaw_to_quaternion(yaw: float):
    """Flat (z-up) yaw -> a unit quaternion (x, y, z, w) for geometry_msgs/Quaternion. Lunar SURFACE nav
    here is planar, so roll = pitch = 0 and only the yaw half-angle populates z/w (w=cos(y/2), z=sin(y/2));
    a consumer recovers yaw = 2*atan2(z, w)."""
    h = 0.5 * float(yaw)
    return (0.0, 0.0, math.sin(h), math.cos(h))


def pose_to_odom(pose: RC.Pose) -> dict:
    """Map an RC Pose telemetry sample to a ROS2-odometry-shaped record (the nav_msgs/Odometry fields a
    consumer needs): map-frame position (col->x, row->y), yaw + its quaternion (qz/qw, for the message's
    orientation), achieved speed, plus the STEWIE proprioception (slip/entrapment) a lunar autonomy layer
    wants alongside pose. The live node (make_ros2_node) builds the actual nav_msgs/Odometry from this."""
    _, _, qz, qw = yaw_to_quaternion(pose.yaw_rad)
    return {"frame_id": "map", "x": float(pose.col), "y": float(pose.row),
            "yaw": float(pose.yaw_rad), "qz": qz, "qw": qw, "v": float(pose.v_achieved_mps),
            "slip": float(pose.slip), "sinkage_m": float(pose.sinkage_m),
            "entrapped": bool(pose.entrapped)}


class RcBridge:
    """The rclpy-OPTIONAL bridge core (testable without ROS2). ``on_cmd_vel`` translates a Twist using
    the last-known pose and submits it through the SF-01 watchdog; ``tick`` advances the dead-man so a
    stalled cmd_vel stream auto-safes; ``update_pose`` keeps the projection anchored to live telemetry."""

    def __init__(self, watchdog: RC.SafingWatchdog, *, horizon_s: float = 1.0, cell_m: float = 1.0) -> None:
        self._wd = watchdog
        self._horizon_s = float(horizon_s)
        self._cell_m = float(cell_m)
        self._pose = RC.Pose(leg_id=0, row=0.0, col=0.0)

    def update_pose(self, pose: RC.Pose) -> None:
        self._pose = pose

    def pose_odom(self) -> dict:
        """The bridge's current pose as a ROS2-odometry-shaped record -- the egress the live node
        publishes on /stewie/odom each tick (the perceive side of the seam, for Nav2/Autoware)."""
        return pose_to_odom(self._pose)

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
                   odom_topic: str = "/stewie/odom", horizon_s: float = 1.0, cell_m: float = 1.0,
                   pose_source=None, odom_rate_hz: float = 10.0):
    """Construct the LIVE rclpy Node (subscribes cmd_vel, ticks the SF-01 dead-man on a timer, publishes
    odom). Gated: raises RuntimeError if rclpy is absent -- the live node needs a ROS2 Jazzy host; the
    translation + RcBridge above run and are tested without it. (Phase A delivers the full seam: the
    cmd_vel ingress AND the /stewie/odom egress.)

    ``pose_source`` (optional) is a callable -> RC.Pose | None, called each odom tick to refresh the
    bridge from LIVE telemetry (the drive loop / estimator); without it the node republishes the last
    pose set via ``update_pose`` -- no fabricated motion is ever invented. ``odom_rate_hz`` sets the
    /stewie/odom publish rate (nav_msgs/Odometry, frame_id=map: position col->x/row->y, yaw quaternion,
    achieved speed) so a Nav2/Autoware layer can localize off the same seam it drives through.

    RUN-VERIFIED on the `stewie-ros2:latest` ROS2 Jazzy container:
      - 2026-06-16 (ingress): a published /cmd_vel Twist (0.25 m/s, 0.1 rad/s) flows through to the SF-01
        watchdog as the expected GoTo (goal ~0.25 cells ahead = the 1 s-horizon projection).
      - 2026-06-17 (egress): with pose_source -> Pose(row=4, col=9, yaw=pi/2), a subscriber on /stewie/odom
        received nav_msgs/Odometry x=9, y=4, qz=qw=0.7071 (yaw pi/2), v=0.2, frame_id=map -- the perceive
        side of the seam (Nav2/Autoware can localize off the same bridge it drives through).
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
