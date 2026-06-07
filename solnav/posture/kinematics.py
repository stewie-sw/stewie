"""Posture kinematics (algorithm A3): arm angles -> chassis lift/pitch -> camera
extrinsics, with a stability gate. Grounded in the IPEx TRL-5 paper (Schuler et
al. 2024): arms stay <=55 deg in nominal ops, "iron cross" = arms parallel (90
deg), one arm under the body raises the chassis ~45 deg; the regolith-delivery
arms can lift the whole chassis ("extreme mobility modes"). The body/limb
DIMENSIONS (arm length, pivot height, wheelbase, track) are not published
numerically, so they are [CONFIRM] estimates scaled 0.7x from RASSOR 2; the
RELATIVE behavior (raising lifts cameras and widens parallax) and the ANGLE
LIMITS are real [SPEC]. Outputs that depend on [CONFIRM] dims are flagged.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# [CONFIRM] geometry, scaled ~0.7x from RASSOR 2 (Schuler 2024 scale factor).
ARM_LENGTH_M = 0.35
PIVOT_HEIGHT_M = 0.25
WHEEL_RADIUS_M = 0.15
WHEELBASE_M = 0.60
TRACK_M = 0.50
GROUND_GAP_M = PIVOT_HEIGHT_M - WHEEL_RADIUS_M   # drum must reach ground before it lifts
# masses [CONFIRM] (30 kg class): chassis + 4 drums
CHASSIS_MASS_KG = 22.0
DRUM_MASS_KG = 2.0

# Posture library: (arm_front_deg, arm_rear_deg). Angles are [SPEC] from the paper.
POSTURES = {
    "TRANSIT":    (0.0, 0.0),     # arms neutral, low CG, full wheelbase
    "COBRA":      (55.0, 0.0),    # front raised/pitched (nominal max 55 deg)
    "MEERKAT":    (70.0, 70.0),   # both arms below chassis -> raised lookout (extreme mode)
    "IRON_CROSS": (90.0, 90.0),   # arms parallel to ground -> max chassis raise
}
ARM_NOMINAL_MAX_DEG = 55.0
ARM_MECH_MAX_DEG = 135.0          # ~2.36 rad absolute mechanical limit


@dataclass
class PostureState:
    name: str
    arm_front_deg: float
    arm_rear_deg: float
    chassis_lift_m: float          # [CONFIRM dims] height gained above wheel plane
    pitch_deg: float               # [CONFIRM dims] nose-up positive
    within_nominal: bool           # arms <= 55 deg
    within_mech_limit: bool        # arms <= 135 deg


def _arm_drop(angle_deg: float) -> float:
    """How far a drum reaches below its pivot at this arm angle (m)."""
    return ARM_LENGTH_M * np.sin(np.radians(angle_deg))


def forward_kinematics(arm_front_deg: float, arm_rear_deg: float, name: str = "") -> PostureState:
    """Map arm angles to chassis lift and pitch. lift = how far each end's drum
    pushes the body up once it reaches the ground; pitch from front/rear asymmetry."""
    lift_f = max(0.0, _arm_drop(arm_front_deg) - GROUND_GAP_M)
    lift_r = max(0.0, _arm_drop(arm_rear_deg) - GROUND_GAP_M)
    chassis_lift = 0.5 * (lift_f + lift_r)
    pitch = np.degrees(np.arctan2(lift_f - lift_r, WHEELBASE_M))
    amax = max(arm_front_deg, arm_rear_deg)
    return PostureState(name or "custom", arm_front_deg, arm_rear_deg,
                        chassis_lift, float(pitch),
                        amax <= ARM_NOMINAL_MAX_DEG, amax <= ARM_MECH_MAX_DEG)


def posture(name: str) -> PostureState:
    af, ar = POSTURES[name]
    return forward_kinematics(af, ar, name)


def camera_height_pitch(base_cam_height_m: float, base_cam_pitch_deg: float,
                        ps: PostureState):
    """Body-mounted camera height/pitch under a posture (extrinsics shift with the
    chassis). Returns (height_m, pitch_deg). [CONFIRM dims]."""
    return base_cam_height_m + ps.chassis_lift_m, base_cam_pitch_deg + ps.pitch_deg


def stability_margin_m(ps: PostureState, fill_front_kg: float = 0.0,
                       fill_rear_kg: float = 0.0) -> float:
    """Horizontal margin from the CG ground-projection to the support-polygon edge.

    On wheels the polygon half-extent is WHEELBASE/2; raised on drums it shrinks
    toward the drum contact line. Positive = stable; smaller when raised (the
    paper's 'slow motion only' regime). [CONFIRM dims + masses]."""
    # CG fore/aft offset from drum/arm fill and arm extension (loaded end pulls CG)
    arm_reach_f = ARM_LENGTH_M * np.cos(np.radians(ps.arm_front_deg))
    arm_reach_r = ARM_LENGTH_M * np.cos(np.radians(ps.arm_rear_deg))
    m_f = 2 * DRUM_MASS_KG + fill_front_kg
    m_r = 2 * DRUM_MASS_KG + fill_rear_kg
    total = CHASSIS_MASS_KG + m_f + m_r
    cg_x = (m_f * arm_reach_f - m_r * arm_reach_r) / total   # +fore
    # support polygon half-length: full wheelbase on wheels, shrinks as we lift
    raised_frac = min(1.0, ps.chassis_lift_m / max(1e-6, ARM_LENGTH_M))
    half_poly = (WHEELBASE_M / 2.0) * (1.0 - 0.7 * raised_frac)
    return float(half_poly - abs(cg_x))


def is_feasible(ps: PostureState, fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                min_margin_m: float = 0.05) -> bool:
    """Posture is feasible if within the mechanical limit and stable with margin."""
    return ps.within_mech_limit and stability_margin_m(ps, fill_front_kg, fill_rear_kg) > min_margin_m


def parallax_baseline_m(p_low: PostureState, p_high: PostureState) -> float:
    """Vertical parallax gained between two postures (camera height difference)."""
    return abs(p_high.chassis_lift_m - p_low.chassis_lift_m)
