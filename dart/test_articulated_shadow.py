"""SN-09: the articulated self-shadow instrument (self-shadow length change vs posture)."""
import math

import pytest

from dart import articulated_shadow as AS


def test_self_shadow_longer_at_low_sun_and_downslope():
    flat_low = AS.self_shadow_length_m(0.5, sun_el_deg=3.0)
    flat_high = AS.self_shadow_length_m(0.5, sun_el_deg=30.0)
    assert flat_low > flat_high > 0                       # grazing sun -> long shadow
    downslope = AS.self_shadow_length_m(0.5, sun_el_deg=10.0, ground_slope_deg=4.0)
    assert downslope > AS.self_shadow_length_m(0.5, sun_el_deg=10.0)   # downslope lengthens it
    assert AS.self_shadow_length_m(0.5, sun_el_deg=2.0, ground_slope_deg=5.0) == math.inf  # sun below slope


def test_round_trip_sun_elevation_from_commanded_change():
    """A commanded dh + the flat dL it produces recovers the true sun elevation exactly."""
    e_true = 5.0
    dh = 0.20
    dL = AS.shadow_length_change_m(dh, sun_el_deg=e_true)
    assert AS.sun_elevation_from_articulated_change(dh, dL) == pytest.approx(e_true, abs=1e-6)


def test_articulated_differential_beats_single_static_under_unknown_casting_height():
    """SN-09 [REQ:SN-09] THE IMPROVEMENT: a single static shadow recovers e from an ASSUMED casting
    height, so an unknown true height biases it; the articulated DIFFERENTIAL cancels the baseline
    height and recovers e without that bias. We should see the error shrink."""
    e_true = 4.0
    h0_true = 0.55          # the real effective casting height (UNKNOWN to the estimator)
    h_assumed = 0.40        # the estimator's nominal casting-height guess (wrong)
    dh = 0.20               # the commanded articulated raise (known exactly)

    # single static: observe L from the true h0, estimate e from the WRONG assumed height
    L_static = AS.self_shadow_length_m(h0_true, e_true)
    e_static = math.degrees(math.atan2(h_assumed, L_static))
    err_static = abs(e_static - e_true)

    # articulated differential: observe dL from the commanded dh (baseline h0 cancels)
    dL = AS.self_shadow_length_m(h0_true + dh, e_true) - AS.self_shadow_length_m(h0_true, e_true)
    e_diff = AS.sun_elevation_from_articulated_change(dh, dL)
    err_diff = abs(e_diff - e_true)

    assert err_diff < 1e-6                                # differential is exact (immune to h0)
    assert err_static > 0.5                               # static is biased by the casting-height error
    assert err_diff < err_static                          # the improvement


def test_recovers_local_ground_slope_from_the_mismatch():
    """With a known sun, the dL mismatch vs the flat prediction recovers the local ground slope."""
    e, slope_true, dh = 10.0, 6.0, 0.25
    dL = AS.shadow_length_change_m(dh, sun_el_deg=e, ground_slope_deg=slope_true)
    assert AS.ground_slope_from_articulated_change(dh, dL, sun_el_deg=e) == pytest.approx(slope_true, abs=1e-6)


def test_dh_from_real_posture_change():
    dh = AS.dh_from_posture("TRANSIT", "COBRA")
    assert dh > 0.05                                      # COBRA raises the body/camera vs TRANSIT


def test_dh_is_reconciled_with_the_render_posture_model():
    """RECONCILE (2026-06-11): the articulation dh is render-observed, so dh_from_posture must agree
    with the Godot bridge / posture_kinematics (the sourced render FK), NOT diverge from it as the two
    posture models once did. This consistency test pins the reconciliation."""
    from dart import articulated_shadow as AS
    from stewie.godot import articulation_bridge as AB
    dh_shadow = AS.dh_from_posture("TRANSIT", "MEERKAT")
    dh_bridge = AB.parallax_capture_plan("scene", sun_az_deg=0.0, sun_el_deg=5.0)["dh_m"]
    assert abs(dh_shadow - dh_bridge) < 1e-6, f"dh must be reconciled: shadow {dh_shadow} vs bridge {dh_bridge}"
    assert dh_shadow > 0.05
