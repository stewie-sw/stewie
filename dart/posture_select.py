"""SN-08: active-morphology posture selection for camera viewpoint (canonical kinematics).

The dissertation's lead idea: the rover RECONFIGURES (arm angles) to improve its own observation
geometry. A static rover gets one fixed viewpoint and ZERO vertical parallax; rotating the drums
down plants them and PUSHES THE BODY UP, lifting the camera (more horizon/shadow visible) and
yielding a vertical parallax baseline for depth, but raising shrinks the support polygon, so there
is a stability ceiling. This selector returns the most arms-down symmetric posture that stays
FEASIBLE (within the arm travel + a stability margin under the current drum load), and the viewpoint
gain versus a fixed TRANSIT baseline.

Grounded in the CANONICAL forward kinematics (posture_kinematics + ipex_postures.json), not the
stale posture_a3 module: the arm-pitch convention is radians with negative = drum rotated below the
wheels, and the maximum statically-modelable lift is the MEERKAT stance at arm pitch -1.0 rad
(camera/parallax baseline 0.174 m). No fabricated geometry.
"""
from __future__ import annotations

import math

from stewie.physics import posture_kinematics as pk

# Symmetric arms-down travel, from horizontal-ish (0) to the MEERKAT planted stance (-1.0 rad).
# MEERKAT is the deepest statically-modelable canonical posture; deeper pitches are recovery
# maneuvers (SELF_RIGHT) that are not statically modelable.
MEERKAT_PITCH_RAD = -1.00
CHASSIS_MASS_KG = 22.0
DRUM_MASS_KG = 2.0


def _lift(arm_pitch_rad: float) -> float:
    """Canonical chassis lift for a SYMMETRIC arms-down posture at this pitch."""
    return pk.chassis_lift_m(arm_pitch_rad, arm_pitch_rad)


def _stability_margin_m(arm_pitch_rad: float, fill_front_kg: float = 0.0,
                        fill_rear_kg: float = 0.0) -> float:
    """Horizontal margin from the centre-of-gravity ground projection to the support-polygon edge.
    On wheels the polygon half-extent is the arm span; planted on the drums it shrinks toward the
    drum contact line as the body lifts; an unbalanced drum load pulls the CG off centre."""
    lift = _lift(arm_pitch_rad)
    raised_frac = min(1.0, lift / pk.ARM_LENGTH_M)
    half_poly = (pk.ARM_SPAN_M / 2.0) * (1.0 - 0.7 * raised_frac)
    reach = pk.ARM_LENGTH_M * math.cos(arm_pitch_rad)            # symmetric drum reach fore/aft
    m_f = 2 * DRUM_MASS_KG + fill_front_kg
    m_r = 2 * DRUM_MASS_KG + fill_rear_kg
    total = CHASSIS_MASS_KG + m_f + m_r
    cg_x = (m_f * reach - m_r * reach) / total                  # fore/aft pull from unbalanced fill
    return half_poly - abs(cg_x)


def select_viewpoint_posture(*, fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                             min_margin_m: float = 0.05, step_rad: float = 0.02) -> float:
    """The most arms-down symmetric posture (lowest, most-negative pitch) that stays feasible under
    the current drum load, i.e. the best stable viewpoint. Returns the arm pitch in radians (<= 0)."""
    best = 0.0                                                   # TRANSIT-level, always feasible
    a = 0.0
    while a >= MEERKAT_PITCH_RAD - 1e-9:
        if _stability_margin_m(a, fill_front_kg, fill_rear_kg) >= min_margin_m:
            if _lift(a) >= _lift(best):
                best = a
        a -= step_rad
    return best


def viewpoint_gain(arm_pitch_rad: float, *, base_cam_height_m: float = 0.40) -> dict:
    """Active-morphology gain versus a fixed TRANSIT posture: the vertical parallax baseline (a
    two-posture maneuver, impossible from one static view) and the camera-height gain."""
    parallax = _lift(arm_pitch_rad) - _lift(0.0)
    return {"parallax_baseline_m": round(parallax, 4),
            "camera_height_gain_m": round(parallax, 4),
            "active_lift_m": round(_lift(arm_pitch_rad), 4),
            "active_arm_deg": round(math.degrees(arm_pitch_rad), 1),
            "stable": _stability_margin_m(arm_pitch_rad) > 0.0}
