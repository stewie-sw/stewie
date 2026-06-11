"""SN-09: the articulated self-shadow instrument (the ARGUS-title idea).

Not the ambient terrain shadow (azimuth -> heading, SN-02/03), but the rover's OWN self-shadow,
whose LENGTH changes by a KNOWN amount when the rover commands an articulated posture change. A
feature at height h casts a self-shadow of length L = h / (tan e - tan slope) on ground sloped by
``slope`` along the anti-solar direction (downslope positive), at sun elevation e.

The ARGUS insight: the rover commands a PRECISE height change dh (forward kinematics, known to mm),
and the unknown effective casting-height baseline h0 CANCELS in the differential

    dL = L(h0 + dh) - L(h0) = dh / (tan e - tan slope).

So the sun elevation recovered from (dh, dL) is IMMUNE to the unknown casting height that biases a
single static shadow reading. The same differential, with a known sun, recovers the local ground
slope under the shadow. Articulated geometry turns the self-shadow into an active, self-calibrating
instrument. Pure geometry on the conserved posture kinematics; no fabricated measurement.
"""
from __future__ import annotations

import math



def self_shadow_length_m(feature_height_m: float, sun_el_deg: float, ground_slope_deg: float = 0.0) -> float:
    """Length of the self-shadow cast by a feature at ``feature_height_m`` (anti-solar, on ground
    sloped ``ground_slope_deg`` downslope-positive). Infinite/clipped if the sun does not clear the
    slope (tan e <= tan slope)."""
    denom = math.tan(math.radians(sun_el_deg)) - math.tan(math.radians(ground_slope_deg))
    if denom <= 1e-9:
        return math.inf                                  # sun grazes below the slope -> no finite shadow tip
    return float(feature_height_m) / denom


def shadow_length_change_m(dh_m: float, sun_el_deg: float, ground_slope_deg: float = 0.0) -> float:
    """The self-shadow length change for a commanded articulated height change ``dh_m`` (independent
    of the unknown baseline casting height -- that is the whole point)."""
    denom = math.tan(math.radians(sun_el_deg)) - math.tan(math.radians(ground_slope_deg))
    if denom <= 1e-9:
        return math.inf
    return float(dh_m) / denom


def sun_elevation_from_articulated_change(dh_m: float, dL_m: float) -> float:
    """Recover sun elevation [deg] from a commanded height change + observed self-shadow-length
    change, assuming locally flat ground: e = atan(dh / dL). Immune to the unknown casting height."""
    if dL_m <= 0.0:
        raise ValueError("dL_m must be > 0 (a positive shadow lengthening for a raise)")
    return math.degrees(math.atan2(float(dh_m), float(dL_m)))


def ground_slope_from_articulated_change(dh_m: float, dL_observed_m: float, sun_el_deg: float) -> float:
    """With a known sun elevation, the mismatch between the observed dL and the flat prediction
    recovers the local ground slope [deg]: tan slope = tan e - dh / dL_observed."""
    if dL_observed_m <= 0.0:
        raise ValueError("dL_observed_m must be > 0")
    tan_slope = math.tan(math.radians(sun_el_deg)) - float(dh_m) / float(dL_observed_m)
    return math.degrees(math.atan(tan_slope))


def dh_from_posture(p_low_name: str, p_high_name: str, base_cam_height_m: float = 0.40) -> float:
    """The known camera-height change between two named postures. RECONCILED (2026-06-11) to source
    from posture_kinematics -- the render-grounded, sourced FK (ARM_LENGTH 0.388 m from the sidecar,
    wheel radius from ipex_specs) that the Godot render and the parallax bridge use -- so the
    commanded dh the instrument relies on is exactly what the camera renders. (dart.posture_a3 is the
    estimator-side posture + stability model with a different arm-angle convention and arm length; it
    is NOT the parallax-baseline source.)"""
    from stewie.physics import posture_kinematics as pk
    from stewie.physics.postures import get_posture
    lo, hi = get_posture(p_low_name), get_posture(p_high_name)
    h_lo = pk.chassis_lift_m(lo.arm_front_pitch_rad, lo.arm_back_pitch_rad)
    h_hi = pk.chassis_lift_m(hi.arm_front_pitch_rad, hi.arm_back_pitch_rad)
    return float(h_hi - h_lo)
