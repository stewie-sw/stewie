"""Phase A (PRD §16.7 / P20): the ROS2 autonomy seam. A geometry_msgs/Twist on /cmd_vel is translated
into the RC command contract and routed THROUGH the SF-01 SafingWatchdog -- so a ROS2 autonomy layer
(Nav2/Autoware-style) can drive the STEWIE rover, and a stalled cmd_vel stream trips the dead-man and
safes the rover. The translation + the watchdog-routed ingress are tested here without rclpy (rclpy is
optional, the codebase's gated-dependency pattern); the live node is gated on a ROS2 Jazzy host.

Run: <venv>/bin/python -m pytest stewie/bridge/test_ros2_bridge.py -q
"""
import math

import pytest

from stewie.bridge import rc_contract as RC
from stewie.bridge import ros2_bridge as B


def _pose(row=10.0, col=10.0, yaw=0.0):
    return RC.Pose(leg_id=0, row=row, col=col, yaw_rad=yaw)


# ---- pure translation -------------------------------------------------------------------------

def test_zero_twist_translates_to_safe():
    cmd = B.twist_to_command(0.0, 0.0, pose=_pose())
    assert isinstance(cmd, RC.Safe) and cmd.reason == RC.SAFE_REASON_OPERATOR


def test_forward_twist_drives_ahead_along_heading():
    cmd = B.twist_to_command(0.3, 0.0, pose=_pose(row=10, col=10, yaw=0.0), horizon_s=1.0, cell_m=1.0)
    assert isinstance(cmd, RC.GoTo)
    assert cmd.goal_col == pytest.approx(10.3) and cmd.goal_row == pytest.approx(10.0)  # +x along yaw=0
    assert cmd.v_max_mps == pytest.approx(0.3)


def test_cmd_vel_goal_radius_is_tighter_than_the_projection_so_the_rover_moves():
    # regression: a 1 m/s x 1 s projection is 1 cell ahead; the GoTo radius must be < that, else the
    # SimBackend reports "already arrived" and the rover never drives (caught on the live closed loop)
    cmd = B.twist_to_command(1.0, 0.0, pose=_pose(row=0, col=0, yaw=0.0), horizon_s=1.0, cell_m=1.0)
    assert isinstance(cmd, RC.GoTo)
    dist_cells = math.hypot(cmd.goal_row, cmd.goal_col)
    assert cmd.goal_radius_cells < dist_cells               # the carrot is genuinely ahead of the radius


def test_turn_rate_rotates_the_short_horizon_goal():
    cmd = B.twist_to_command(0.3, math.pi / 2, pose=_pose(row=10, col=10, yaw=0.0), horizon_s=1.0)
    assert isinstance(cmd, RC.GoTo)
    assert cmd.goal_row == pytest.approx(10.3, abs=1e-6)             # turned +90deg -> drives +y
    assert cmd.goal_col == pytest.approx(10.0, abs=1e-6)


def test_pose_to_odom_maps_fields():
    od = B.pose_to_odom(RC.Pose(leg_id=1, row=5.0, col=7.0, yaw_rad=0.5, v_achieved_mps=0.2, slip=0.1))
    assert od["x"] == 7.0 and od["y"] == 5.0 and od["yaw"] == 0.5 and od["v"] == 0.2


# ---- odom EGRESS (the perceive side of the seam: nav_msgs/Odometry for Nav2/Autoware) -----------

def test_yaw_to_quaternion_is_a_flat_yaw_only_rotation():
    assert B.yaw_to_quaternion(0.0) == pytest.approx((0.0, 0.0, 0.0, 1.0))
    qx, qy, qz, qw = B.yaw_to_quaternion(math.pi / 2)
    assert (qx, qy) == pytest.approx((0.0, 0.0))                          # planar: no roll/pitch
    assert qz == pytest.approx(math.sin(math.pi / 4)) and qw == pytest.approx(math.cos(math.pi / 4))
    for y in (-1.2, 0.0, 0.7, 3.0):                                       # round-trip: yaw = 2*atan2(qz, qw)
        _, _, qz, qw = B.yaw_to_quaternion(y)
        assert 2.0 * math.atan2(qz, qw) == pytest.approx(y, abs=1e-9)


def test_pose_to_odom_carries_quaternion_for_nav_msgs():
    od = B.pose_to_odom(RC.Pose(leg_id=0, row=1.0, col=2.0, yaw_rad=0.5))
    assert od["qz"] == pytest.approx(math.sin(0.25)) and od["qw"] == pytest.approx(math.cos(0.25))


def test_rcbridge_exposes_current_pose_odom_for_publishing():
    bridge = B.RcBridge(RC.SafingWatchdog(RC.RecordingBackend()))
    bridge.update_pose(RC.Pose(leg_id=0, row=4.0, col=9.0, yaw_rad=0.0))
    od = bridge.pose_odom()
    assert od["x"] == 9.0 and od["y"] == 4.0 and od["frame_id"] == "map"


def test_sim_pose_source_closes_cmd_vel_to_odom_loop():
    # the egress pose_source that drains a SimBackend: a GoTo advances the sim, odom follows it
    be = RC.SimBackend(start_rc=(0.0, 0.0), cell_m=1.0, dt_s=1.0)
    src = B.sim_pose_source(be)
    assert src() is None                                       # no telemetry before any command
    be.submit(RC.GoTo(leg_id=0, goal_row=0.0, goal_col=10.0, v_max_mps=1.0))
    p1 = src()
    assert p1 is not None and p1.col > 0.0                     # stepped toward the goal
    p2 = src()
    assert p2.col > p1.col                                     # keeps advancing along the live sim


# ---- the SF-01-routed cmd_vel ingress (the safety property over ROS2) --------------------------

def test_cmd_vel_reaches_the_backend_through_the_watchdog():
    be = RC.RecordingBackend()
    bridge = B.RcBridge(RC.SafingWatchdog(be, deadline_s=5.0))
    bridge.on_cmd_vel(0.3, 0.0, now=0.0)
    assert len(be.commands) == 1 and isinstance(be.commands[0], RC.GoTo)


def test_stalled_cmd_vel_stream_safes_the_rover():
    # SF-01 over the ROS2 path: feed once, then let the stream stall past the deadline -> auto-SAFE.
    be = RC.RecordingBackend()
    wd = RC.SafingWatchdog(be, deadline_s=5.0)
    bridge = B.RcBridge(wd)
    bridge.on_cmd_vel(0.3, 0.0, now=0.0)
    assert bridge.tick(now=2.0) is False                # within deadline -> still driving
    assert bridge.tick(now=10.0) is True                # stalled past 5 s -> tripped
    assert isinstance(be.commands[-1], RC.Safe) and be.commands[-1].reason == RC.SAFE_REASON_WATCHDOG


def test_live_node_is_gated_without_rclpy():
    # the translation/ingress run without ROS2; the LIVE node requires a ROS2 Jazzy host
    pytest.importorskip  # marker: rclpy intentionally optional
    try:
        import rclpy  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="rclpy"):
            B.make_ros2_node(RC.SafingWatchdog(RC.RecordingBackend()))
