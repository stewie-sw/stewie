"""AM-03: the MEERKAT camera-vantage RAISE action.

MEERKAT lowers the arms DOWN under the chassis; the planted drums PUSH THE BODY UP, so every
chassis-mounted (perception) camera rises. This module is the AM-03 action. Given the MEERKAT arm
angle it (1) GATES the raise through the AM-01 posture machine -- a legal ``TRANSIT -> MEERKAT``
transition with an adequate load-aware stability margin, REFUSED otherwise and never forced; (2)
SPEED-LIMITS the arm motion through the VT-03 typed joint slew (``arm_joint.ArmJointState.step``,
rate-limited by ``ARM_RATE_DEG_S``); and (3) composes the VT-10 posture-dependent camera extrinsics
(``camera_extrinsics``) with the sourced chassis-lift forward kinematics
(``posture_kinematics.base_link_height_m``) to compute each camera's WORLD-frame vantage height at
MEERKAT vs the nominal drive posture. The RAISED chassis-camera vantage EXCEEDS the nominal vantage;
that height gain IS the AM-03 acceptance.

Nothing here is re-derived:
  * MEERKAT posture legality + the stability gate -- ``stewie.specs.posture_machine.can_transition``
    (AM-01/AM-02: legal transition table + the caller-supplied stability-margin guard).
  * the canonical MEERKAT arm pitch + the load-aware margin -- ``dart.posture_select`` (the SN-08
    canonical support-polygon-vs-CG model, the same margin ``meerkat_observation`` / active_perception
    gate on).
  * the speed-limited arm motion -- ``stewie.specs.arm_joint.ArmJointState.step`` (VT-03 rate-limited
    slew; a joint cannot carry a velocity above ``max_rate_deg_s`` -- enforced at construction).
  * the per-camera ``base_link`` pose -- ``stewie.specs.camera_extrinsics.camera_extrinsics`` (VT-10).
  * the chassis lift (``base_link`` height above ground) --
    ``stewie.physics.posture_kinematics.base_link_height_m``: MEERKAT plants the drums below the wheels
    at the sourced arm reach (0.388245 m) and the body rides at that reach instead of the wheel radius
    (0.1524 m), so the lift is real geometry, not a fabricated height.

World vantage of a camera = ``base_link`` height above ground + the camera's ``base_link``-frame up
offset (the VT-10 extrinsic's ``position_m`` up component). The MEERKAT stance modeled here is
SYMMETRIC (both arms at the same down angle), so it induces zero posture pitch
(``posture_kinematics.posture_pitch_rad == 0``) and the mount needs no attitude rotation -- the up
offset is exactly ``position_m[1]``. (Differential front/rear arm pose as a camera-PITCH action is the
separate AM-04 concern.)

The ARM-mounted (drum) cameras DESCEND under MEERKAT -- they are the ones planting on the ground -- so
the vantage the maneuver RAISES is the CHASSIS/perception set (and the rig's maximum camera height);
the arm-camera descent is reported honestly, not hidden. Pure + on-host; the exact flight MEERKAT
geometry stays the gated Q tier (as with the ``arm_state`` [ASSUMPTION] posture numbers it composes).
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass, field

from dart import posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.specs import posture_machine as pm
from stewie.specs.arm_joint import ARM_RATE_DEG_S, JOINT_FRONT, ArmJointState
from stewie.specs.arm_state import ArmState
from stewie.specs.camera_extrinsics import CameraExtrinsic, all_camera_extrinsics
from stewie.specs.vehicles import DEFAULT_VEHICLE

#: the nominal DRIVE-posture arm angle [deg]: arms stowed horizontal (wheels support the body).
NOMINAL_ARM_DEG: float = 0.0

#: the canonical MEERKAT arm angle [deg] -- the SN-08 canonical MEERKAT pitch (-1.0 rad) expressed in
#: the arm_state degree convention (negative = drum rotated DOWN below the pivot). One source.
MEERKAT_ARM_DEG: float = math.degrees(ps.MEERKAT_PITCH_RAD)


@dataclass(frozen=True)
class CameraVantage:
    """One camera's WORLD-frame vantage height in the nominal drive posture vs the MEERKAT raise.

    ``nominal_height_m`` / ``meerkat_height_m`` are the camera's height above local ground [m] in the
    two postures; ``gain_m`` is ``meerkat - nominal`` (positive = the raise lifts this camera).
    ``mount`` is ``"chassis"`` (rigid to the body -- raised by the whole chassis) or ``"arm"`` (rides
    the arm -- DESCENDS as the arm plants)."""
    name: str
    mount: str
    nominal_height_m: float
    meerkat_height_m: float
    gain_m: float


@dataclass(frozen=True)
class MeerkatRaise:
    """The AM-03 MEERKAT-raise result. ``feasible`` is the AM-01 posture-machine verdict (a legal +
    stable ``TRANSIT -> MEERKAT`` transition); when False ``vantages`` is empty, the gains are 0, and
    ``reason`` carries why (the raise is refused, never fabricated). When feasible: ``vantages`` is the
    per-camera height table (VT-10 x chassis-lift FK), ``chassis_vantage_gain_m`` is the common lift the
    chassis cameras gain (== ``posture_kinematics.chassis_lift_m``), ``max_vantage_gain_m`` is the rise
    of the rig's HIGHEST camera, ``raise_time_s`` / ``max_arm_speed_deg_s`` are the realized VT-03
    rate-limited slew (``max_arm_speed_deg_s <= ARM_RATE_DEG_S``), and ``speed_limited`` records that the
    motion honored the slew cap."""
    from_state: str
    to_state: str
    feasible: bool
    reason: str
    meerkat_arm_deg: float
    nominal_arm_deg: float
    stability_margin_m: float
    min_margin_m: float
    raise_time_s: float
    max_arm_speed_deg_s: float
    speed_limited: bool
    chassis_vantage_gain_m: float
    max_vantage_gain_m: float
    vantages: tuple[CameraVantage, ...] = field(default_factory=tuple)

    @property
    def chassis_vantages(self) -> tuple[CameraVantage, ...]:
        """The chassis-mounted cameras -- the perception set the raise LIFTS."""
        return tuple(v for v in self.vantages if v.mount == "chassis")

    @property
    def arm_vantages(self) -> tuple[CameraVantage, ...]:
        """The arm-mounted (drum) cameras -- these DESCEND as the arms plant under the chassis."""
        return tuple(v for v in self.vantages if v.mount == "arm")

    @property
    def raises_vantage(self) -> bool:
        """The AM-03 acceptance: a feasible raise strictly LIFTS every chassis camera AND the rig's
        highest camera (real height gain, not a fabricated number)."""
        chassis = self.chassis_vantages
        return (self.feasible and bool(chassis)
                and all(v.gain_m > 0.0 for v in chassis) and self.max_vantage_gain_m > 0.0)


def _speed_limited_slew(nominal_deg: float, meerkat_deg: float, dt: float) -> tuple[float, float, bool]:
    """Slew an arm joint from ``nominal_deg`` to ``meerkat_deg`` through the VT-03 rate-limited stepper
    (``arm_joint.ArmJointState.step``); return ``(raise_time_s, max_speed_deg_s, reached)``. Every tick's
    joint velocity is bounded by ``ARM_RATE_DEG_S`` by construction (VT-03 rejects a faster velocity at
    construction), so the modeled motion is SPEED-LIMITED -- this returns the realized slew time and the
    peak speed as evidence. Both symmetric arms slew identically, so one joint characterizes the raise."""
    if dt <= 0.0:
        raise ValueError(f"dt must be > 0 (got {dt})")
    joint = ArmJointState(joint=JOINT_FRONT, angle_deg=nominal_deg)
    max_speed = 0.0
    ticks = 0
    max_ticks = 1_000_000
    while abs(joint.angle_deg - meerkat_deg) > 1e-9 and ticks < max_ticks:
        joint = joint.step(meerkat_deg, dt)
        max_speed = max(max_speed, abs(joint.velocity_deg_s))
        ticks += 1
    reached = abs(joint.angle_deg - meerkat_deg) <= 1e-9
    return ticks * dt, max_speed, reached


def meerkat_raise(*, meerkat_arm_deg: float = MEERKAT_ARM_DEG, from_state: str = pm.TRANSIT,
                  nominal_arm_deg: float = NOMINAL_ARM_DEG, fill_front_kg: float = 0.0,
                  fill_rear_kg: float = 0.0, min_margin_m: float = 0.05, dt: float = 0.1,
                  vehicle: object = DEFAULT_VEHICLE) -> MeerkatRaise:
    """Plan a MEERKAT camera-vantage raise from a standstill in ``from_state``.

    Lowers both arms symmetrically to ``meerkat_arm_deg`` (arms-DOWN, negative), which plants the drums
    and jacks the chassis up. GATED on the AM-01 posture machine: the ``from_state -> MEERKAT`` transition
    must be LEGAL and the load-aware MEERKAT stability margin (``posture_select``) must clear
    ``min_margin_m``; otherwise the raise is REFUSED (``feasible=False``, ``vantages=()``) with the
    machine's reason -- no vantage is fabricated for a posture the rover cannot safely hold. When
    feasible, composes the VT-03 rate-limited slew (speed limit), the VT-10 per-camera extrinsics, and the
    sourced chassis-lift FK to report each camera's world vantage nominal vs MEERKAT; the chassis cameras
    rise by the chassis lift (the acceptance), the arm cameras descend.

    ``meerkat_arm_deg`` must be < 0 (MEERKAT is an arms-DOWN raise). ``fill_front_kg`` / ``fill_rear_kg``
    are the drum loads feeding the load-aware margin; an unbalanced load can drop the margin below
    ``min_margin_m`` and refuse the raise. Pure + on-host."""
    if meerkat_arm_deg >= 0.0:
        raise ValueError(f"MEERKAT is an arms-DOWN raise; meerkat_arm_deg must be < 0, got {meerkat_arm_deg}")

    meerkat_rad = math.radians(meerkat_arm_deg)

    # AM-02/AM-03 gate: the MEERKAT transition must be legal from `from_state` AND the load-aware margin at
    # the symmetric MEERKAT stance must clear the threshold (composes posture_select's support-polygon /
    # CG model with the posture_machine legality table).
    margin_m = ps._stability_margin_m(meerkat_rad, fill_front_kg, fill_rear_kg)
    ok, reason = pm.can_transition(from_state, pm.MEERKAT, stability_margin_m=margin_m,
                                   min_margin_m=min_margin_m)
    if not ok:
        return MeerkatRaise(from_state=from_state, to_state=pm.MEERKAT, feasible=False, reason=reason,
                            meerkat_arm_deg=meerkat_arm_deg, nominal_arm_deg=nominal_arm_deg,
                            stability_margin_m=margin_m, min_margin_m=min_margin_m,
                            raise_time_s=0.0, max_arm_speed_deg_s=0.0, speed_limited=False,
                            chassis_vantage_gain_m=0.0, max_vantage_gain_m=0.0, vantages=())

    # AM-03 speed limit: the arms slew from stowed to MEERKAT under the VT-03 rate-limited joint stepper.
    raise_time_s, max_speed, reached = _speed_limited_slew(nominal_arm_deg, meerkat_arm_deg, dt)
    speed_limited = reached and max_speed <= ARM_RATE_DEG_S + 1e-9

    # VT-10 x chassis-lift FK: each camera's world vantage = base_link height above ground + its base_link
    # up offset (the extrinsic's position_m up). base_link rides at the wheel radius nominally, at the arm
    # reach under MEERKAT; a symmetric stance induces no posture pitch, so no mount rotation is needed.
    nominal_ext = all_camera_extrinsics(ArmState(front_deg=nominal_arm_deg, back_deg=nominal_arm_deg), vehicle)
    meerkat_ext = all_camera_extrinsics(ArmState(front_deg=meerkat_arm_deg, back_deg=meerkat_arm_deg), vehicle)
    base_nominal_m = pk.base_link_height_m(math.radians(nominal_arm_deg), math.radians(nominal_arm_deg))
    base_meerkat_m = pk.base_link_height_m(meerkat_rad, meerkat_rad)

    vantages: list[CameraVantage] = []
    for name in sorted(meerkat_ext):
        nom_ext: CameraExtrinsic = nominal_ext[name]
        meer_ext: CameraExtrinsic = meerkat_ext[name]
        nominal_h = base_nominal_m + nom_ext.position_m[1]
        meerkat_h = base_meerkat_m + meer_ext.position_m[1]
        vantages.append(CameraVantage(name=name, mount=meer_ext.mount, nominal_height_m=nominal_h,
                                      meerkat_height_m=meerkat_h, gain_m=meerkat_h - nominal_h))

    # the chassis cameras all gain exactly the chassis lift (their up offset is arm-independent); the rig
    # max-vantage gain is the rise of the highest camera (a chassis mono under MEERKAT).
    chassis_gain_m = base_meerkat_m - base_nominal_m
    max_vantage_gain_m = (max(v.meerkat_height_m for v in vantages)
                          - max(v.nominal_height_m for v in vantages))
    return MeerkatRaise(from_state=from_state, to_state=pm.MEERKAT, feasible=True, reason="ok",
                        meerkat_arm_deg=meerkat_arm_deg, nominal_arm_deg=nominal_arm_deg,
                        stability_margin_m=margin_m, min_margin_m=min_margin_m,
                        raise_time_s=raise_time_s, max_arm_speed_deg_s=max_speed,
                        speed_limited=speed_limited, chassis_vantage_gain_m=chassis_gain_m,
                        max_vantage_gain_m=max_vantage_gain_m, vantages=tuple(vantages))
