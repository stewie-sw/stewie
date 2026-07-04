"""AM-04: a controlled camera-PITCH from a DIFFERENTIAL front/rear arm pose.

A four-wheel rover on its wheels cannot pitch its cameras -- the wheel contacts fix the chassis plane.
But when the RDS arms are planted below the wheels (the MEERKAT / DRUM_WALK family of postures), the two
arm ends BECOME the fore/aft support and the chassis rides on them: rotating the FRONT arm deeper than
the REAR (a *differential* arm angle) plants the front support higher than the back, and the body pitches
NOSE-UP by a controlled amount -- which pitches every body-fixed camera with it. This is the AM-04
maneuver: articulate the differential to AIM the cameras in elevation without driving.

Nothing here is a new physical model. The chassis tilt is the SOURCED forward kinematics
``posture_kinematics.posture_pitch_rad`` (``atan2(front_support - back_support, arm_pivot_span)`` -- the
same engine ``posture_select`` / ``meerkat_observation`` already lift and tilt the body with), driven by
the two VT-03 ``ArmJointState`` joint angles (their construction is the *kinematic validation* AM-04 asks
for -- an out-of-travel arm is rejected, not silently used). The *resulting camera pitch* is derived by
composing VT-10 ``camera_extrinsics``: each camera's optical-forward in ``base_link`` is rotated by the
induced body pitch about the lateral axis, and the change in its optical elevation IS the camera pitch.

Two consequences fall straight out of the geometry, and are the AM-04 acceptance:

  * ZERO at equal angles -- ``front_deg == rear_deg`` gives ``front_support == back_support`` so the
    chassis pitch (and hence every camera's induced pitch) is exactly 0; no differential, no tilt.
  * MONOTONIC -- planting the front arm progressively deeper than the rear raises the front support
    monotonically (``sin`` of the below-horizontal angle), so both the chassis pitch and a
    forward-looking camera's pitch increase strictly monotonically. A forward chassis camera pitches by
    EXACTLY the chassis pitch; a rear-looking camera by its negative (its axis dips as the nose rises);
    a side-looking camera (optical axis ON the lateral pitch axis) does not pitch at all -- the honest
    VT-10 composition, not a blanket "camera pitch == body pitch".

The maneuver is a controlled ACTION only after BOTH validations the PRD requires: the kinematic one
(VT-03 arm-travel limits, enforced at ``ArmJointState`` construction) and the STABILITY one -- the
load-aware support-polygon margin (``posture_select._stability_margin_asym_m``, the same margin the
Meerkat gate uses; the asymmetric form, because a differential pose is asymmetric). If the margin is
below the guard the action is refused (``feasible=False``, with the reason); the induced geometry is
still reported (it is a deterministic consequence of the valid arm angles, not a fabricated measurement),
but a planner must see ``feasible`` before committing the pitch.

Provenance note (honest, not reconciled here): the chassis-tilt geometry uses
``posture_kinematics.ARM_LENGTH_M`` (0.388245 m, SOURCED from the sidecar mesh) and the arm-pivot span
(0.40 m, ``ARM_SPAN_M`` == ``|ARM_ORIGIN_FRONT - ARM_ORIGIN_BACK|``); the VT-10 arm-camera optical axis
uses ``arm_state``'s ``ARM_LENGTH_M`` (0.28 m, [ASSUMPTION]). These two arm-length numbers live in their
two canonical modules and are each used only within their own domain; the DEFAULT camera here is a
forward CHASSIS camera whose induced pitch equals the chassis pitch and depends on the posture-kinematics
number alone, so the load-bearing AM-04 property does not straddle the discrepancy.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass

from dart import posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.specs.arm_joint import JOINT_FRONT, JOINT_REAR, ArmJointState
from stewie.specs.camera_extrinsics import CAMERAS, camera_extrinsics
from stewie.specs.vehicles import DEFAULT_VEHICLE

Vec3 = tuple[float, float, float]

#: the camera the differential pitch is read on by default: a forward-looking CHASSIS camera whose
#: optical axis lies in the fore/aft-vertical plane, so its induced pitch equals the chassis pitch
#: exactly (the clean monotonic + zero-at-equal quantity). One of VT-10's eight rig cameras (`CAMERAS`).
DEFAULT_PITCH_CAMERA = "front_left"

#: default load-aware stability-margin guard [m] -- the same 0.05 m the Meerkat / posture gate uses.
DEFAULT_MIN_MARGIN_M = 0.05

_EPS = 1e-12


def chassis_pitch_from_differential(front_deg: float, rear_deg: float) -> float:
    """The body PITCH [rad] a differential front/rear arm pose induces (nose-up positive).

    Composes ``posture_kinematics.posture_pitch_rad`` (the sourced forward kinematics: the fore/aft
    support-height difference over the arm-pivot span), driven by the two arm angles. Sign/limit
    convention is the shared one: ``angle_deg`` is the arm pitch with 0 = stowed horizontal and NEGATIVE
    = drum rotated DOWN below the pivot, so a more-negative front than rear plants the front deeper,
    lifts the front support, and pitches the nose UP (> 0). Exactly 0 when ``front_deg == rear_deg``;
    strictly monotonic as the front arm plants progressively deeper than a fixed planted rear.
    """
    return pk.posture_pitch_rad(math.radians(float(front_deg)), math.radians(float(rear_deg)))


def _optical_elevation_rad(forward: Vec3) -> float:
    """Elevation of a ``base_link`` optical-forward vector above the fore/aft-lateral plane (+up = +Y).
    This is the camera's pitch: 0 for a level look, +pi/2 looking straight up."""
    n = math.sqrt(forward[0] * forward[0] + forward[1] * forward[1] + forward[2] * forward[2])
    if n < _EPS:
        raise ValueError(f"cannot take the elevation of a near-zero optical-forward vector {forward}")
    return math.asin(max(-1.0, min(1.0, forward[1] / n)))


def _pitch_about_lateral(forward: Vec3, pitch_rad: float) -> Vec3:
    """Rotate a ``base_link`` vector by a body PITCH about the lateral (+Z) axis. +pitch is nose-up:
    it carries forward ``+X`` toward up ``+Y`` -- the same fwd<->up mixing ``posture_kinematics``'s
    ``_mount_world_up`` applies (``fwd*sin(pitch) + up*cos(pitch)``)."""
    x, y, z = forward
    c, s = math.cos(pitch_rad), math.sin(pitch_rad)
    return (x * c - y * s, x * s + y * c, z)


@dataclass(frozen=True)
class DifferentialCameraPitch:
    """The AM-04 result: the camera pitch a differential arm pose commands, plus the two validations.

    ``chassis_pitch_rad`` is the body tilt the differential induces (the mechanism). ``camera_pitch_rad``
    is the resulting change in the named camera's optical elevation (the controlled amount) -- for a
    forward chassis camera it equals ``chassis_pitch_rad``; for a rear camera its negative; ~0 for a
    side camera. ``differential_deg`` is ``front_deg - rear_deg``. ``stability_margin_m`` is the
    load-aware support-polygon margin at this posture; ``feasible`` is True only when it clears the
    guard AND the arm angles were kinematically valid (the latter raises at construction, so an
    infeasible result here is always a stability refusal), with ``reason`` carrying why. The geometry
    fields are reported even when infeasible (they are a deterministic consequence of the valid arm
    angles, not a measurement), but a planner must gate on ``feasible`` before committing the pitch.
    """

    front_deg: float
    rear_deg: float
    differential_deg: float
    camera: str
    mount: str
    chassis_pitch_rad: float
    camera_pitch_rad: float
    stability_margin_m: float
    feasible: bool
    reason: str

    @property
    def chassis_pitch_deg(self) -> float:
        return math.degrees(self.chassis_pitch_rad)

    @property
    def camera_pitch_deg(self) -> float:
        return math.degrees(self.camera_pitch_rad)


def camera_pitch_from_differential(front_deg: float, rear_deg: float, *,
                                   camera: str = DEFAULT_PITCH_CAMERA,
                                   fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                                   min_margin_m: float = DEFAULT_MIN_MARGIN_M,
                                   vehicle: object = DEFAULT_VEHICLE) -> DifferentialCameraPitch:
    """Map a differential front/rear arm pose to the camera pitch it commands, gated on both validations.

    ``front_deg`` / ``rear_deg`` are the two arm angles (VT-03 convention: 0 = stowed horizontal,
    NEGATIVE = drum planted below the pivot). ``camera`` is one of the eight VT-10 rig cameras
    (``CAMERAS``); the default is a forward chassis camera. ``fill_front_kg`` / ``fill_rear_kg`` are the
    per-arm drum loads the stability margin is computed under. ``min_margin_m`` is the support-polygon
    guard.

    KINEMATIC validation: the angles are built into VT-03 ``ArmJointState`` records, which reject an
    out-of-travel arm with ``ValueError`` (the pose is not realizable -- a hard reject, not a soft flag).
    The chassis tilt is then ``chassis_pitch_from_differential`` (sourced posture kinematics), and the
    camera pitch is derived by composing VT-10 ``camera_extrinsics``: the named camera's optical-forward
    is rotated by the chassis pitch about the lateral axis, and the change in its elevation is the pitch.
    STABILITY validation: the load-aware asymmetric support-polygon margin
    (``posture_select._stability_margin_asym_m``); ``feasible`` is True only when it clears ``min_margin_m``.
    """
    # --- KINEMATIC validation (VT-03): arm-travel limits are enforced at construction (raises) ---------
    front = ArmJointState(joint=JOINT_FRONT, angle_deg=float(front_deg))
    rear = ArmJointState(joint=JOINT_REAR, angle_deg=float(rear_deg))

    # --- the mechanism: differential arm pose -> chassis tilt (sourced posture kinematics) ------------
    chassis_pitch = chassis_pitch_from_differential(front.angle_deg, rear.angle_deg)

    # --- the resulting camera pitch: COMPOSE VT-10 extrinsics + the chassis-pitch rotation ------------
    ext = camera_extrinsics(camera, (front, rear), vehicle)     # raises KeyError on an unknown camera
    tilted_forward = _pitch_about_lateral(ext.optical_forward, chassis_pitch)
    camera_pitch = _optical_elevation_rad(tilted_forward) - _optical_elevation_rad(ext.optical_forward)

    # --- STABILITY validation: the load-aware asymmetric support-polygon margin -----------------------
    margin_m = ps._stability_margin_asym_m(math.radians(front.angle_deg), math.radians(rear.angle_deg),
                                           fill_front_kg, fill_rear_kg)
    feasible = margin_m >= min_margin_m
    reason = "ok" if feasible else (f"stability margin {margin_m:.4f} m < guard {min_margin_m:.4f} m "
                                    f"(AM-04 refuses an unstable differential-pitch pose)")

    return DifferentialCameraPitch(
        front_deg=float(front.angle_deg), rear_deg=float(rear.angle_deg),
        differential_deg=float(front.angle_deg) - float(rear.angle_deg),
        camera=ext.name, mount=ext.mount,
        chassis_pitch_rad=chassis_pitch, camera_pitch_rad=camera_pitch,
        stability_margin_m=margin_m, feasible=feasible, reason=reason,
    )


__all__ = [
    "CAMERAS",
    "DEFAULT_PITCH_CAMERA",
    "DifferentialCameraPitch",
    "camera_pitch_from_differential",
    "chassis_pitch_from_differential",
]
