"""Posture-tracked charge docking -- NO blind approach.

The reconfigurable rover POSTURES (mast/arm articulation + the 8-camera rig) to keep the charger AprilTag
locked and CENTERED all the way to contact -- active fiducial tracking (cf. gimbal-tracked precision drone
landing, Springer & Kyas 2022, arXiv:2206.04617). The posture forward-kinematics gives the camera pose in
the body frame (known from joint encoders + calibration); chaining it with the AprilTag (tag-in-camera)
and the charger's KNOWN world pose yields the BODY pose continuously.

Consequences (the docking question, solved):
- Docking accuracy = AprilTag error (BETTER at close range when the tag is large + centered) (+) posture-FK
  error -- mm-to-cm, MAINTAINED to dock. There is no dead-reckoning blind segment.
- It is INDEPENDENT of wheel slip / terrain deformation: the body pose is MEASURED relative to the charger
  every frame, so compacted/excavated terrain only changes how much closed-loop correction is commanded,
  not the final accuracy. The fiducial lock decouples docking from odometry.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/world/dock_pose.py, 2026-06-09 (M2)
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Pose2:
    """SE(2) rigid transform / pose: x, y (m), theta (rad)."""
    x: float
    y: float
    theta: float

    def compose(self, b: "Pose2") -> "Pose2":
        c, s = math.cos(self.theta), math.sin(self.theta)
        return Pose2(self.x + c * b.x - s * b.y, self.y + s * b.x + c * b.y, self.theta + b.theta)

    def inverse(self) -> "Pose2":
        c, s = math.cos(self.theta), math.sin(self.theta)
        return Pose2(-(c * self.x + s * self.y), -(-s * self.x + c * self.y), -self.theta)


def body_pose_from_tag(tag_in_cam: Pose2, cam_in_body: Pose2, tag_in_world: Pose2) -> Pose2:
    """Body pose in world from a tag observation -- the no-blind docking estimate.
    T_world_body = T_world_tag . inv(T_cam_tag) . inv(T_body_cam). Uses ONLY the measured tag pose + the
    posture FK + the known charger pose -- no odometry, so it is slip/terrain independent."""
    return tag_in_world.compose(tag_in_cam.inverse()).compose(cam_in_body.inverse())


def dock_error_budget(*, apriltag_sigma_xy_m: float, apriltag_sigma_theta_rad: float,
                      fk_sigma_xy_m: float, fk_sigma_theta_rad: float) -> dict:
    """First-order combined docking-pose uncertainty (independent error sources add in quadrature). The
    AprilTag term SHRINKS as the rover closes (larger, centered tag); the FK term is set by joint sensing
    + kinematic calibration. NO dead-reckoning term -- that is the point of staying locked."""
    sxy = math.hypot(apriltag_sigma_xy_m, fk_sigma_xy_m)
    sth = math.hypot(apriltag_sigma_theta_rad, fk_sigma_theta_rad)
    return {"sigma_xy_m": sxy, "sigma_theta_rad": sth, "sigma_theta_deg": math.degrees(sth)}


def fk_arm_angle_to_xy_sigma_m(arm_length_m: float, angle_sigma_deg: float) -> float:
    """Posture-FK position sigma contributed by one articulated joint: L * sin(angle_sigma)."""
    return arm_length_m * math.sin(math.radians(angle_sigma_deg))


def camera_sees_tag(tag_in_cam: Pose2, *, hfov_deg: float, max_range_m: float,
                    min_range_m: float = 0.0) -> bool:
    """Is the tag inside this camera's FOV cone + range band? (tag must be in front: +x forward.)"""
    rng = math.hypot(tag_in_cam.x, tag_in_cam.y)
    if tag_in_cam.x <= 0 or not (min_range_m <= rng <= max_range_m):
        return False
    bearing = abs(math.atan2(tag_in_cam.y, tag_in_cam.x))
    return bearing <= math.radians(hfov_deg / 2.0)


def select_tracking_camera(tag_in_body: Pose2, cameras, *, hfov_deg: float = 73.99,
                           max_range_m: float = 30.0):
    """Active-tracking handoff: of the rig's cameras (each a (name, Pose2 cam_in_body, min_range)) pick the
    one that currently has the tag in view -- so as the front stereo loses it up close, a lower / drum-arm
    camera (or a re-postured one) picks it up. Returns (name, cam_in_body, tag_in_cam) or None."""
    for name, cam_in_body, min_range in cameras:
        tag_in_cam = cam_in_body.inverse().compose(tag_in_body)
        if camera_sees_tag(tag_in_cam, hfov_deg=hfov_deg, max_range_m=max_range_m, min_range_m=min_range):
            return name, cam_in_body, tag_in_cam
    return None
