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
    cmd = B.twist_to_command(0.3, math.pi / 2, pose=_pose(row=10, col=10, yaw=0.0), horizon_s=1.0, cell_m=1.0)
    assert isinstance(cmd, RC.GoTo)
    # +angular_z is CCW; forward after +90deg is REP-103 +y (left), which is -row in the grid (frames.py)
    assert cmd.goal_row == pytest.approx(9.7, abs=1e-6)
    assert cmd.goal_col == pytest.approx(10.0, abs=1e-6)


def test_slow_twist_on_the_production_grid_still_projects_a_reachable_carrot():  # #296
    """A realistic IPEx speed (0.3 m/s) on the production 5 m/cell grid projects only 0.06 cells ahead, so
    the FIXED 0.1-cell arrival radius swallowed it as 'already arrived' -> ZERO motion (verified: 0.2-0.4
    m/s drove 0 m at cell_m=5). The arrival radius must scale to the projection so the moving carrot is
    always genuinely ahead of the rover at any cell size + speed."""
    cmd = B.twist_to_command(0.3, 0.0, pose=_pose(row=0, col=0, yaw=0.0), horizon_s=1.0, cell_m=5.0)
    assert isinstance(cmd, RC.GoTo)
    dist_cells = math.hypot(cmd.goal_row, cmd.goal_col)
    assert dist_cells > 0.0
    assert cmd.goal_radius_cells < dist_cells, "slow twist carrot is inside the arrival radius -> swallowed (#296)"


def test_pose_to_odom_maps_fields():
    # REP-103 metres via frames.py: x=col*cell_m, y=-row*cell_m (handedness), not raw grid cells
    od = B.pose_to_odom(RC.Pose(leg_id=1, row=5.0, col=7.0, yaw_rad=0.5, v_achieved_mps=0.2, slip=0.1),
                        cell_m=1.0)
    assert od["x"] == 7.0 and od["y"] == -5.0 and od["yaw"] == 0.5 and od["v"] == 0.2


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
    bridge = B.RcBridge(RC.SafingWatchdog(RC.RecordingBackend()))      # default cell_m = DEFAULT_CELL_M (5 m)
    bridge.update_pose(RC.Pose(leg_id=0, row=4.0, col=9.0, yaw_rad=0.0))
    od = bridge.pose_odom()
    # REP-103 metres at the seam's shared 5 m/cell: x=col*5, y=-row*5 (frames.py), not raw cells
    assert od["x"] == 45.0 and od["y"] == -20.0 and od["frame_id"] == "map"


def test_pose_to_odom_round_trips_through_frames_in_metres():
    # the egress speaks frames.py REP-103 metres (x=col*cell_m, y=-row*cell_m); rep103_to_grid_pose
    # recovers the exact grid cells at the SAME cell_m -> the seam is one self-consistent contract
    from stewie.bridge import frames as FR
    pose = RC.Pose(leg_id=0, row=4.0, col=9.0, yaw_rad=math.pi / 2)
    for cell in (1.0, 5.0):
        od = B.pose_to_odom(pose, cell_m=cell)
        assert od["x"] == pytest.approx(9.0 * cell) and od["y"] == pytest.approx(-4.0 * cell)
        rp = FR.Rep103Pose(x=od["x"], y=od["y"], z=0.0, quaternion_xyzw=(0.0, 0.0, od["qz"], od["qw"]))
        (row, col), yaw = FR.rep103_to_grid_pose(rp, cell_m=cell)
        assert (row, col) == pytest.approx((4.0, 9.0)) and yaw == pytest.approx(math.pi / 2)


def test_drive_loop_seam_shares_one_cell_m_default():
    # the prior 5.0-vs-1.0 default split was a latent 5x mislocalization; both ends now default to ONE source
    import inspect
    assert RC.DEFAULT_CELL_M == 5.0
    assert inspect.signature(RC.commands_from_plan).parameters["cell_m"].default == RC.DEFAULT_CELL_M
    assert inspect.signature(B.twist_to_command).parameters["cell_m"].default == RC.DEFAULT_CELL_M
    assert inspect.signature(B.make_ros2_node).parameters["cell_m"].default == RC.DEFAULT_CELL_M


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


def test_bridge_service_entrypoint_help_and_gating():
    # the console entry parses args and, without rclpy, surfaces the same ROS2-host gate (no silent no-op)
    with pytest.raises(SystemExit) as e:
        B.main(["--help"])                                  # argparse --help exits 0
    assert e.value.code == 0
    try:
        import rclpy  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="rclpy"):
            B.main([])                                       # reaches the gated make_ros2_node


# ---- #144: the producer body pins to the cockpit /rc/ros_odom contract ------------------------

def test_ros_odom_ingest_body_matches_cockpit_contract():
    # the body the node POSTs must validate against the cockpit's RosOdomIngest, field-for-field, so the
    # producer can never drift from the consumer (a real contract pin, not a mock).
    from stewie.server.routers.rc import RosOdomIngest
    frame = {"dem": "haworth", "cell_m": 5.0, "dem_origin": [9000.0, 3600.0]}
    body = B.ros_odom_ingest_body(x_m=12.5, y_m=-4.0, yaw_rad=0.3, slip=0.1, soc=0.8, mode="cmd_vel", frame=frame)
    assert body == {"x_m": 12.5, "y_m": -4.0, "yaw_rad": 0.3, "slip": 0.1, "soc": 0.8, "mode": "cmd_vel",
                    "frame": {"dem": "haworth", "cell_m": 5.0, "dem_origin": [9000.0, 3600.0]}}
    m = RosOdomIngest(**body)                                # accepted by the cockpit contract
    assert m.x_m == 12.5 and m.mode == "cmd_vel"
    assert m.frame.dem == "haworth" and tuple(m.frame.dem_origin) == (9000.0, 3600.0)


def test_ros_odom_ingest_body_clamps_and_drops_nonfinite():
    body = B.ros_odom_ingest_body(x_m=0.0, y_m=0.0, slip=2.0, soc=float("nan"))
    assert body["slip"] == 1.0          # slip clamped into [0, 1]
    assert "soc" not in body            # a non-finite soc is dropped, never posted
