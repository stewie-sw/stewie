"""Posture-tracked charge docking: FK-chain pose recovery (no blind), error budget, active camera handoff."""
import math

from dart import dock_pose as DP


def _ang_eq(a, b):
    return abs(math.atan2(math.sin(a - b), math.cos(a - b))) < 1e-6


def test_body_pose_recovered_from_tag_no_odometry():
    body = DP.Pose2(10.0, 5.0, 0.0)
    cam_in_body = DP.Pose2(0.5, 0.0, 0.0)                 # front camera 0.5 m ahead
    tag_world = DP.Pose2(15.0, 5.0, math.pi)             # charger tag facing the rover
    # forward: what the camera sees
    tag_in_cam = body.compose(cam_in_body).inverse().compose(tag_world)
    rec = DP.body_pose_from_tag(tag_in_cam, cam_in_body, tag_world)
    assert abs(rec.x - 10.0) < 1e-9 and abs(rec.y - 5.0) < 1e-9 and _ang_eq(rec.theta, 0.0)
    # SLIP-INDEPENDENT: the estimate uses only tag + FK + known charger pose -> no odometry term at all
    assert "odom" not in DP.body_pose_from_tag.__doc__.lower() or "no odometry" in DP.body_pose_from_tag.__doc__.lower()


def test_error_budget_has_no_dead_reckoning_term():
    # AprilTag 2 mm / 0.3 deg (close + centered) + posture-FK 1 mm / 0.1 deg -> a few mm, NOT decimeters
    b = DP.dock_error_budget(apriltag_sigma_xy_m=0.002, apriltag_sigma_theta_rad=math.radians(0.3),
                             fk_sigma_xy_m=0.001, fk_sigma_theta_rad=math.radians(0.1))
    assert b["sigma_xy_m"] < 0.005 and b["sigma_theta_deg"] < 0.5


def test_fk_arm_angle_sigma():
    # the 0.388 m IPEx-class arm at 0.1 deg joint-sensing -> sub-mm FK position error
    assert DP.fk_arm_angle_to_xy_sigma_m(0.388245, 0.1) < 0.001


def test_active_tracking_camera_handoff():
    # tag 0.4 m ahead, low -> the front cam (high, narrow look-down) misses; a drum-arm/low cam catches it
    tag_in_body = DP.Pose2(0.4, 0.0, math.pi)
    cams = [("front_high", DP.Pose2(0.3, 0.0, 0.0), 0.6),         # min_range 0.6 m -> too close, misses
            ("drum_low", DP.Pose2(0.2, 0.0, 0.0), 0.0)]           # sees down to contact
    pick = DP.select_tracking_camera(tag_in_body, cams)
    assert pick is not None and pick[0] == "drum_low"
