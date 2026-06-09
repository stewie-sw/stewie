"""Posture forward kinematics: arm slider angles -> chassis height -> camera vantage.

Wires HEIGHT ESTIMATION via pose + drum-arm angles (the dissertation P2 posture-dependent camera
extrinsics). The chassis lift is NO LONGER a magic per-posture constant: it is COMPUTED from the arm
pitch so the sim angle faithfully drives the rendered height AND the estimator can recover camera
vantage from measured joint angles (proprioception -> extrinsics).

Geometry (SOURCED): arm length = |DRUM_FRONT_REL| = 0.388245 m (sidecar mesh, pivot->drum center);
wheel radius = 0.1524 m (ipex_specs WHEEL_RADIUS_M); arm pivot on base_link, base_link rides at the
wheel radius above ground in the nominal (wheel-supported) stance. Strut model is first-order; the
absolute magnitude (drum-contact radius) is [CALIB] to reconcile against the rendered sim, but the
FUNCTIONAL relationship (monotonic in arm-down angle; TRANSIT ~0; MEERKAT > 0) is faithful.

Convention (matches ipex_postures.json): a NEGATIVE arm pitch rotates the drum DOWN below the pivot;
the angle below horizontal is theta_down = max(0, -pitch). The arm that reaches furthest down supports
the chassis. When neither arm reaches below the wheels, the wheels support and the lift is 0.
"""
from __future__ import annotations

import math

ARM_LENGTH_M = 0.388245      # SOURCED: |DRUM_FRONT_REL| (sidecar.gd), pivot -> drum center
WHEEL_RADIUS_M = 0.1524      # SOURCED: ipex_specs WHEEL_RADIUS_M (flight IPEx)
ARM_SPAN_M = 0.40            # SOURCED: arm pivots at +-0.20 m (sidecar ARM_FRONT/BACK_ORIGIN)


def _support_heights(arm_front_pitch_rad, arm_back_pitch_rad, arm_length_m, wheel_radius_m):
    """Fore and aft support heights of base_link: each end rides on the HIGHER of its arm reach (if the
    arm is planted below the wheels) or the wheel radius (wheels support)."""
    front = max(arm_drop_below_pivot_m(arm_front_pitch_rad, arm_length_m), wheel_radius_m)
    back = max(arm_drop_below_pivot_m(arm_back_pitch_rad, arm_length_m), wheel_radius_m)
    return front, back


def posture_pitch_rad(arm_front_pitch_rad: float, arm_back_pitch_rad: float, arm_span_m: float = ARM_SPAN_M,
                      arm_length_m: float = ARM_LENGTH_M, wheel_radius_m: float = WHEEL_RADIUS_M) -> float:
    """Body pitch induced by ASYMMETRIC arm reach (front higher than back -> nose up). This is how COBRA
    rears and DRUM_WALK tilts -- the body attitude changes from posture alone, before any terrain slope."""
    front, back = _support_heights(arm_front_pitch_rad, arm_back_pitch_rad, arm_length_m, wheel_radius_m)
    return math.atan2(front - back, arm_span_m)


def arm_drop_below_pivot_m(arm_pitch_rad: float, arm_length_m: float = ARM_LENGTH_M) -> float:
    """Vertical distance the drum drops below its arm pivot for a given pitch (0 if the arm is at or
    above horizontal). theta_down = max(0, -pitch); drop = L*sin(theta_down)."""
    theta_down = max(0.0, -float(arm_pitch_rad))
    return arm_length_m * math.sin(theta_down)


def base_link_height_m(arm_front_pitch_rad: float, arm_back_pitch_rad: float,
                       arm_length_m: float = ARM_LENGTH_M, wheel_radius_m: float = WHEEL_RADIUS_M) -> float:
    """Height of base_link CENTER above ground = mean of the fore/aft support heights (so asymmetric
    arms both lift and pitch the body). Wheels support at wheel_radius unless an arm plants lower."""
    front, back = _support_heights(arm_front_pitch_rad, arm_back_pitch_rad, arm_length_m, wheel_radius_m)
    return 0.5 * (front + back)


def chassis_lift_m(arm_front_pitch_rad: float, arm_back_pitch_rad: float,
                   arm_length_m: float = ARM_LENGTH_M, wheel_radius_m: float = WHEEL_RADIUS_M) -> float:
    """Chassis lift above the nominal wheel-supported stance, computed from the arm angles."""
    return base_link_height_m(arm_front_pitch_rad, arm_back_pitch_rad, arm_length_m, wheel_radius_m) - wheel_radius_m


def camera_vantage_m(arm_front_pitch_rad: float, arm_back_pitch_rad: float, cam_vert_offset_m: float = 0.0,
                     arm_length_m: float = ARM_LENGTH_M, wheel_radius_m: float = WHEEL_RADIUS_M) -> float:
    """Estimated camera height above ground from pose + arm angles + the camera's mount offset.
    This is the height-estimation the estimator computes from measured joint angles (proprioception)."""
    return base_link_height_m(arm_front_pitch_rad, arm_back_pitch_rad, arm_length_m, wheel_radius_m) + cam_vert_offset_m


# The 8 LAC camera mounts in the rover/base_link body frame (fwd +X, up +Y, lat +Z), SOURCED from
# godot_sidecar/camera_rig.gd. Each camera's world height differs by its mount AND by the body attitude
# the terrain slope imposes (a front camera and a rear camera on a pitched body are NOT the same height).
CAMERA_MOUNTS = {
    "front_left":  (0.30, -0.10, 0.035),
    "front_right": (0.30, -0.10, -0.035),
    "rear_left":   (-0.30, -0.10, 0.035),
    "rear_right":  (-0.30, -0.10, -0.035),
    "left_mono":   (0.0, -0.05, 0.285),
    "right_mono":  (0.0, -0.05, -0.285),
    "drum_front_cam": (0.10, 0.18, 0.0),
    "drum_back_cam":  (-0.10, 0.18, 0.0),
}


def _mount_world_up(mount, pitch_rad: float, roll_rad: float) -> float:
    """World-up (vertical) component of a body-frame mount (fwd, up, lat) after the body is pitched
    (about the lateral axis; +pitch = nose up) and rolled (about the fwd axis). This is why fore/aft
    cameras change height on a slope: the fwd term is +fwd*sin(pitch)."""
    fwd, up, lat = mount
    return fwd * math.sin(pitch_rad) + (up * math.cos(roll_rad) - lat * math.sin(roll_rad)) * math.cos(pitch_rad)


def camera_heights_m(arm_front_pitch_rad: float, arm_back_pitch_rad: float,
                     slope_along_rad: float = 0.0, slope_cross_rad: float = 0.0,
                     terrain_height_m: float = 0.0, sinkage_m: float = 0.0, mounts: dict = CAMERA_MOUNTS,
                     arm_length_m: float = ARM_LENGTH_M, wheel_radius_m: float = WHEEL_RADIUS_M) -> dict:
    """Per-camera world height above the datum, from pose + arm angles + terrain SLOPE + sinkage.

    Each of the 8 cameras gets its OWN height = terrain + base_link(arms) - sinkage + (attitude-rotated
    mount).up. The total body attitude is terrain slope (slope_along = pitch, +nose up; slope_cross =
    roll, from the local DEM gradient along/across heading) PLUS the posture pitch from asymmetric arms.
    Wheel sinkage (slip.py) drops the whole body. This is the estimator's height-from-proprioception."""
    total_pitch = slope_along_rad + posture_pitch_rad(arm_front_pitch_rad, arm_back_pitch_rad,
                                                      arm_length_m=arm_length_m, wheel_radius_m=wheel_radius_m)
    base = (terrain_height_m
            + base_link_height_m(arm_front_pitch_rad, arm_back_pitch_rad, arm_length_m, wheel_radius_m)
            - sinkage_m)
    return {name: base + _mount_world_up(m, total_pitch, slope_cross_rad) for name, m in mounts.items()}
