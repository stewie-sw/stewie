"""SLAM-seam: the rendered-sensor estimators (DEM overlay, articulation parallax, stereo VO) become
the MEASURED fixes that run_integrated_slam fuses, replacing the modeled (truth + calibrated-sigma)
fix at a keyframe. The producers are exercised on REAL data (the real Haworth DEM, real parallax
geometry, the real a6 rendered stereo traverse). With measured_fixes=None the modeled path stays
byte-identical (the honest default). The end-to-end run driving ALL three off a real rendered
lunar-shadow sequence with pose truth is GATED on such a dataset.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from dart import slam_seam as SEAM


# ---- producer 1: register_to_dem -> absolute world position fix (REAL Haworth DEM) ----------------
def _textured_cell(Z, half):
    H, W = Z.shape
    sub = Z[half + 5:H - half - 5, half + 5:W - half - 5]
    rr, cc = np.unravel_index(int(np.argmax(np.abs(np.gradient(sub)[0]))), sub.shape)
    return (rr + half + 5, cc + half + 5)


def test_dem_position_fix_recovers_world_pose_on_real_haworth():
    from dart import localization as LOC
    from lode import mission_planner as MP
    dem = MP.load_haworth_dem()
    Z, cell = dem
    half = 6
    true_rc = _textured_cell(Z, half)
    observed = LOC.patch_at(Z, true_rc, half)               # rover senses the true terrain
    guess_rc = (true_rc[0] + 3, true_rc[1] - 2)             # belief has drifted
    fix = SEAM.dem_position_fix(observed, dem, guess_rc, base_sigma_m=2.0)
    assert fix is not None
    # the corrected cell -> world (x,y) must match the TRUE cell's world coords (exact integer recovery)
    assert fix["xy"][0] == pytest.approx(true_rc[1] * cell)
    assert fix["xy"][1] == pytest.approx(true_rc[0] * cell)
    assert fix["confidence"] > 0.5 and fix["residual_rmse_m"] < 1e-6
    assert fix["sigma"] > 0.0


def test_dem_position_fix_returns_none_on_ambiguous_flat_terrain():
    Z = np.zeros((40, 40), dtype=float)                     # featureless -> ambiguous (confidence 0)
    observed = Z[14:25, 14:25].copy()
    fix = SEAM.dem_position_fix(observed, (Z, 5.0), (20, 20))
    assert fix is None                                      # refuse to fabricate a fix from a flat map


# ---- producer 2: articulation_localize -> absolute position fix (REAL parallax geometry) ----------
def test_parallax_position_fix_recovers_true_xy_from_geometry():
    true_xy = np.array([10.0, 5.0])
    landmarks = [(0.0, 0.0), (20.0, 0.0), (10.0, 20.0)]     # 3 non-collinear -> unambiguous fix
    dh_m, fx_px = 0.174, 800.0                              # MEERKAT lift, a real fx
    ranges = [float(np.linalg.norm(true_xy - np.asarray(L))) for L in landmarks]
    shifts = [fx_px * dh_m / r for r in ranges]             # exact pinhole forward projection
    fix = SEAM.parallax_position_fix((8.0, 3.0), landmarks, shifts, dh_m=dh_m, fx_px=fx_px)
    assert not fix["ambiguous"] and fix["fused"]
    assert fix["xy"][0] == pytest.approx(10.0, abs=0.25)
    assert fix["xy"][1] == pytest.approx(5.0, abs=0.25)
    assert fix["sigma"] > 0.0


# ---- producer 3: estimate_vo -> ground-plane SE(2) relative factors (REAL rendered traverse) ------
_CAM = os.path.join(os.path.dirname(__file__), "..", "stewie", "eval", "validation", "a6_traverse", "cam")
_FRAMES = [os.path.join(_CAM, f"frame_{k:03d}") for k in range(4)]
_have_frames = all(os.path.exists(os.path.join(f, "front_left.png")) for f in _FRAMES)


@pytest.mark.skipif(not _have_frames, reason="rendered a6 stereo traverse not present")
def test_vo_relative_factors_on_real_rendered_traverse():
    from imageio.v3 import imread

    from dart import stereo_vo
    pairs = [(np.asarray(imread(os.path.join(f, "front_left.png"))),
              np.asarray(imread(os.path.join(f, "front_right.png")))) for f in _FRAMES]
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=pairs[0][0].shape[1], height_px=pairs[0][0].shape[0],
                                            hfov_deg=73.99, baseline_m=0.07)
    vo = stereo_vo.estimate_vo(pairs, cfg)
    factors = SEAM.vo_relative_factors(vo)
    assert len(factors) == len(pairs) - 1                   # F-1 inter-frame steps
    for f in factors:
        if f["valid"]:
            assert np.all(np.isfinite(f["dxy"])) and np.isfinite(f["dyaw"])
        else:
            assert f["dxy"] is None                         # M-03: never a fabricated zero-motion factor


# ---- the lunar est-vs-truth: REAL DEM fixes bound drift on a REAL Haworth traverse, scored vs truth -
def test_dem_fixed_traverse_beats_odometry_on_real_haworth():
    """#148: score the fused trajectory against the DEM's OWN truth (not a modeled cue). The rover
    drives a real-terrain path; odometry drifts under a gyro bias; the REAL register_to_dem fix on the
    real Haworth terrain corrects it. The fused ATE must beat odometry-only -- a real lunar est-vs-truth,
    no modeled truth+sigma cue."""
    from lode import mission_planner as MP
    dem = MP.load_haworth_dem()
    Z, _cell = dem
    r0, c0 = _textured_cell(Z, 6)                              # start in textured terrain (real relief)
    path = [(r0 + 2 * k, c0 + k) for k in range(16)]          # a real diagonal traverse over the DEM
    out = SEAM.dem_fixed_traverse(dem, path, patch_half=6, gyro_bias_rad=0.01, fix_interval=2)
    assert out["n_dem_fix"] >= 2, f"too few real DEM fixes landed: {out}"
    assert out["measured"] == out["n_dem_fix"]                 # every fused fix is a MEASURED one
    assert out["ate_fused_m"] < out["ate_odom_m"], (
        f"real DEM fixes did not beat odometry (fused {out['ate_fused_m']} >= odom {out['ate_odom_m']})")
    # the headline: odometry drifts unboundedly; the real terrain fixes BOUND the absolute drift (>5x)
    assert out["abs_max_fused_m"] < 0.2 * out["abs_max_odom_m"], (
        f"real DEM fixes did not bound the drift (fused {out['abs_max_fused_m']} vs odom {out['abs_max_odom_m']})")


