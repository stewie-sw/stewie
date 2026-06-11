"""SN-08: active-morphology posture selection for camera viewpoint.

The dissertation's lead idea: the rover RECONFIGURES (arm angles) to improve its own observation
geometry. A static rover gets one fixed viewpoint and ZERO vertical parallax; raising the drums
lifts the camera (more horizon/shadow visible) AND, paired with a low posture, yields a vertical
parallax baseline for depth -- but raising shrinks the support polygon, so there is a stability
ceiling. This selector returns the HIGHEST FEASIBLE posture (max camera lift subject to the mech
limit + a stability margin under the current drum load), and the viewpoint gain vs a fixed
TRANSIT baseline. Built on the conserved posture kinematics (posture_a3); no fabricated geometry.
"""
from __future__ import annotations

from stewie.physics import posture_a3 as P


def select_viewpoint_posture(*, fill_front_kg: float = 0.0, fill_rear_kg: float = 0.0,
                             min_margin_m: float = 0.05, arm_max_deg: float = 90.0,
                             step_deg: float = 1.0):
    """The highest symmetric arm posture that stays FEASIBLE (within mech limit + stability margin)
    under the current drum load -- the best stable viewpoint. Returns the PostureState."""
    best = P.forward_kinematics(0.0, 0.0, "TRANSIT")       # always feasible fallback
    a = 0.0
    while a <= arm_max_deg + 1e-9:
        ps = P.forward_kinematics(a, a, f"arm{a:.0f}")
        if ps.within_mech_limit and P.stability_margin_m(ps, fill_front_kg, fill_rear_kg) >= min_margin_m:
            if ps.chassis_lift_m >= best.chassis_lift_m:
                best = ps
        a += step_deg
    return best


def viewpoint_gain(active, *, baseline: str = "TRANSIT", base_cam_height_m: float = 0.40) -> dict:
    """Active-morphology gain vs a fixed posture: the vertical parallax baseline (a two-posture
    maneuver -- impossible from one static view) and the camera-height gain (horizon/shadow reach)."""
    base = P.posture(baseline)
    parallax = P.parallax_baseline_m(base, active)
    h_active, _ = P.camera_height_pitch(base_cam_height_m, 0.0, active)
    h_base, _ = P.camera_height_pitch(base_cam_height_m, 0.0, base)
    return {"parallax_baseline_m": round(parallax, 4),
            "camera_height_gain_m": round(h_active - h_base, 4),
            "active_lift_m": round(active.chassis_lift_m, 4),
            "active_arm_deg": round(active.arm_front_deg, 1),
            "stable": P.is_feasible(active)}
