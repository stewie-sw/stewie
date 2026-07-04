"""SN-11: the Meerkat observation ACTION -- a multi-height parallax + shadow-disambiguation maneuver.

The lead idea (composes SN-08 posture selection + AM-03 MEERKAT + the AM-01 posture FSM): a stopped
rover RAISES to the MEERKAT stance (arms rotated DOWN under the chassis, which plants the drums and
PUSHES THE BODY UP) and captures the SAME world feature from a SET of camera heights on the way up.
A static rover sees a feature from one vantage with ZERO vertical parallax; sweeping the chassis from
the TRANSIT floor to MEERKAT buys a real vertical baseline (dh up to the canonical MEERKAT lift) and a
changing self-shadow geometry, which is exactly what disambiguates a shallow rock from its shadow and
feeds the SN-10 depression-angle range / SN-15 low-vs-high feature association.

This module DEFINES the observation (the posture schedule + the camera extrinsic at each height, all
pointed at one associated feature) and NOTHING MORE: it fabricates no parallax measurement. The actual
pixel-shift / shadow-tip / range readout is the GATED perception fill (SN-15 / dart.articulated_parallax
SN-10), which consumes these extrinsics. The maneuver is GATED on a legal, stable MEERKAT transition
through the AM-01 posture machine -- an illegal from-state or an inadequate load-aware stability margin
refuses the action outright (no samples), it is never forced.

Geometry is composed, not invented:
  * chassis lift per arm pitch      -- dart.posture_select._lift (== stewie.physics.posture_kinematics
                                       chassis_lift_m; the SN-08 canonical forward kinematics).
  * load-aware stability margin      -- dart.posture_select._stability_margin_m (the SN-08 support-polygon
                                       vs CG model; the same margin active_perception gates on).
  * MEERKAT posture legality + gate  -- stewie.specs.posture_machine.can_transition (AM-01/AM-02/AM-03).
  * camera extrinsic per height      -- VT-10 (posture-dependent extrinsics) is NOT built yet, so per the
                                       SN-11 acceptance the extrinsic is derived from the arm/posture
                                       state here: the standstill (x, y) is fixed, the height rises with
                                       the chassis lift, and the rotation reduces to a look-at toward the
                                       one associated feature. When VT-10 lands, swap `_extrinsic_at` for it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from dart import posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.specs import posture_machine as pm

#: the TRANSIT-stance camera height above local ground [m]; the parallax baseline adds on top of this.
#: The SAME assumption dart.posture_select.viewpoint_gain uses (base_cam_height_m=0.40) -- one source.
BASE_CAM_HEIGHT_M = 0.40


def _pitch_for_lift(lift_m: float) -> float:
    """Symmetric arms-down arm pitch [rad, <= 0] whose canonical chassis lift equals ``lift_m`` -- the
    inverse of posture_kinematics.chassis_lift_m for a planted symmetric stance (lift = L*sin(theta_down)
    - wheel_radius, so theta_down = asin((lift + wheel_radius)/L)). A non-positive lift is the wheel-
    supported TRANSIT floor (pitch 0, the wheels carry the body and the arms reach nothing lower)."""
    if lift_m <= 0.0:
        return 0.0
    ratio = (lift_m + pk.WHEEL_RADIUS_M) / pk.ARM_LENGTH_M
    if ratio > 1.0:
        raise ValueError(f"lift {lift_m:.4f} m exceeds the max symmetric arm reach "
                         f"{pk.ARM_LENGTH_M - pk.WHEEL_RADIUS_M:.4f} m")
    return -math.asin(ratio)


def _look_at_unit(cam_xyz: tuple[float, float, float],
                  feature_xyz: tuple[float, float, float]) -> tuple[float, float, float]:
    """Unit pointing vector from a camera position toward the associated feature -- the extrinsic
    rotation reduces to this look-at (every height observes the SAME feature). A degenerate
    (coincident) pair returns a nadir look (0, 0, -1) rather than a fabricated direction."""
    dx = feature_xyz[0] - cam_xyz[0]
    dy = feature_xyz[1] - cam_xyz[1]
    dz = feature_xyz[2] - cam_xyz[2]
    n = math.sqrt(dx * dx + dy * dy + dz * dz)
    if n < 1e-9:
        return (0.0, 0.0, -1.0)
    return (dx / n, dy / n, dz / n)


@dataclass(frozen=True)
class CameraExtrinsic:
    """The camera pose for ONE height of the Meerkat sweep, derived from the arm/posture state (VT-10
    surrogate). `camera_height_m` is above the local datum (terrain + BASE_CAM_HEIGHT_M + chassis lift);
    `camera_xyz` is the standstill camera position (x, y fixed, z = height); `look_at_unit` is the
    pointing toward the shared feature; `stability_margin_m` is the load-aware margin at this pitch."""
    arm_pitch_rad: float
    chassis_lift_m: float
    camera_height_m: float
    camera_xyz: tuple[float, float, float]
    look_at_unit: tuple[float, float, float]
    stability_margin_m: float


@dataclass(frozen=True)
class MeerkatObservation:
    """The SN-11 action/contract: a gated multi-height observation of ONE world feature from the MEERKAT
    raise. `feasible` is the AM-01 posture-machine verdict (a legal + stable MEERKAT transition); when
    False `samples` is empty and `reason` carries why (the maneuver is refused, never fabricated). Every
    sample observes the same `feature_id`/`target_xyz` -- the association SN-15 needs. `parallax_baseline_m`
    is the vertical baseline the sweep buys (highest minus lowest camera height); it is a pure kinematic
    property of the maneuver, not a measurement."""
    feature_id: str
    target_xyz: tuple[float, float, float]
    rover_xy: tuple[float, float]
    from_state: str
    to_state: str
    feasible: bool
    reason: str
    meerkat_margin_m: float
    parallax_baseline_m: float
    samples: tuple[CameraExtrinsic, ...] = field(default_factory=tuple)

    @property
    def n_heights(self) -> int:
        return len(self.samples)

    @property
    def heights_m(self) -> tuple[float, ...]:
        """The camera heights (low -> high) the sweep captures the feature from."""
        return tuple(s.camera_height_m for s in self.samples)


def meerkat_observation(*, feature_id: str, target_xy: tuple[float, float],
                        rover_xy: tuple[float, float], from_state: str = pm.TRANSIT,
                        target_pitch_rad: float = ps.MEERKAT_PITCH_RAD, n_heights: int = 3,
                        fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                        base_cam_height_m: float = BASE_CAM_HEIGHT_M, terrain_z_m: float = 0.0,
                        target_z_m: float = 0.0, min_margin_m: float = 0.05) -> MeerkatObservation:
    """Plan a Meerkat observation of ``feature_id`` at ``target_xy`` from a standstill at ``rover_xy``.

    Raises to the MEERKAT stance (``target_pitch_rad``, arms-down) and schedules ``n_heights`` camera
    captures at evenly-spaced heights from the TRANSIT floor up to MEERKAT, each pose pointed at the one
    feature (feeds SN-15's low-vs-high association). GATED on the AM-01 posture machine: the transition
    ``from_state -> MEERKAT`` must be LEGAL and the load-aware MEERKAT stability margin must clear
    ``min_margin_m``; otherwise the action is REFUSED (``feasible=False``, ``samples=()``) with the
    machine's reason -- no observation is fabricated for a posture the rover cannot safely hold.

    Pure + on-host: composes posture_select (lift + margin) and posture_kinematics (extrinsic height);
    the actual parallax/shadow readout from these extrinsics is the gated perception fill, not this action.
    """
    if n_heights < 2:
        raise ValueError(f"a parallax sweep needs >= 2 heights, got {n_heights}")
    if target_pitch_rad > 0.0:
        raise ValueError(f"MEERKAT is an arms-DOWN raise; target_pitch_rad must be <= 0, got {target_pitch_rad}")

    target_xyz = (float(target_xy[0]), float(target_xy[1]), float(target_z_m))
    rover_xy = (float(rover_xy[0]), float(rover_xy[1]))

    # AM-01/AM-02/AM-03 gate: the MEERKAT transition must be legal from `from_state` AND the load-aware
    # margin at the MEERKAT target must clear the threshold (MEERKAT is the deepest, least-stable pose --
    # the binding constraint; every shallower sample has a larger support polygon, hence a larger margin).
    meerkat_margin_m = ps._stability_margin_m(target_pitch_rad, fill_front_kg, fill_rear_kg)
    ok, reason = pm.can_transition(from_state, pm.MEERKAT, stability_margin_m=meerkat_margin_m,
                                   min_margin_m=min_margin_m)
    if not ok:
        return MeerkatObservation(feature_id=feature_id, target_xyz=target_xyz, rover_xy=rover_xy,
                                  from_state=from_state, to_state=pm.MEERKAT, feasible=False,
                                  reason=reason, meerkat_margin_m=meerkat_margin_m,
                                  parallax_baseline_m=0.0, samples=())

    target_lift_m = ps._lift(target_pitch_rad)          # the MEERKAT chassis lift (SN-08 canonical FK)
    samples: list[CameraExtrinsic] = []
    for i in range(n_heights):
        lift_m = target_lift_m * (i / (n_heights - 1))  # even heights: TRANSIT floor (0) .. MEERKAT
        pitch_rad = _pitch_for_lift(lift_m)
        height_m = terrain_z_m + base_cam_height_m + lift_m
        cam_xyz = (rover_xy[0], rover_xy[1], height_m)
        samples.append(CameraExtrinsic(
            arm_pitch_rad=pitch_rad, chassis_lift_m=lift_m, camera_height_m=height_m,
            camera_xyz=cam_xyz, look_at_unit=_look_at_unit(cam_xyz, target_xyz),
            stability_margin_m=ps._stability_margin_m(pitch_rad, fill_front_kg, fill_rear_kg)))

    parallax_baseline_m = samples[-1].camera_height_m - samples[0].camera_height_m
    return MeerkatObservation(feature_id=feature_id, target_xyz=target_xyz, rover_xy=rover_xy,
                              from_state=from_state, to_state=pm.MEERKAT, feasible=True, reason="ok",
                              meerkat_margin_m=meerkat_margin_m,
                              parallax_baseline_m=parallax_baseline_m, samples=tuple(samples))