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

_PART = "/mnt/projects/datasets/katwijk/Part1"


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


# ---- the seam: measured fixes bound drift on the REAL Katwijk trajectory --------------------------
def _katwijk():
    from dart.integrated_slam import load_katwijk_arrays
    return load_katwijk_arrays(_PART)


@pytest.mark.skipif(not os.path.isdir(_PART), reason="Katwijk not present")
def test_measured_parallax_fixes_bound_drift_on_katwijk():
    from dart.integrated_slam import run_integrated_slam
    truth, dr, tyaw, gyro = _katwijk()
    n_kf, fix_interval = 30, 4
    idx = np.linspace(0, min(len(truth), len(dr)) - 1, n_kf).astype(int)
    T = np.asarray(truth)[idx]
    # build a MEASURED parallax fix at each parallax keyframe by running the REAL estimator on the
    # parallax geometry of the true pose (the rendered shadow-tip shifts are the gated input; here the
    # shifts are forward-modeled from the true geometry, so the estimator recovers ~the true pose).
    dh_m, fx_px = 0.174, 800.0
    measured = {"parallax": {}}
    for k in range(fix_interval, n_kf, fix_interval):
        p = T[k]
        landmarks = [(p[0] + 15.0, p[1] + 1.0), (p[0] - 2.0, p[1] + 14.0), (p[0] - 13.0, p[1] - 9.0)]
        ranges = [float(np.linalg.norm(p - np.asarray(L))) for L in landmarks]
        shifts = [fx_px * dh_m / r for r in ranges]
        fix = SEAM.parallax_position_fix((p[0] + 1.5, p[1] - 1.0), landmarks, shifts, dh_m=dh_m, fx_px=fx_px)
        measured["parallax"][k] = (fix["xy"], fix["sigma"])

    base = run_integrated_slam(truth, dr, tyaw, gyro, factors=("odom",), n_keyframes=n_kf,
                               fix_interval=fix_interval, seed=0)["abs_max_err_m"]
    fused = run_integrated_slam(truth, dr, tyaw, gyro, factors=("odom", "parallax"), n_keyframes=n_kf,
                                fix_interval=fix_interval, seed=0, measured_fixes=measured)["abs_max_err_m"]
    assert fused < base, f"measured parallax fixes did not bound drift (fused {fused} >= base {base})"


@pytest.mark.skipif(not os.path.isdir(_PART), reason="Katwijk not present")
def test_measured_fixes_none_is_byte_identical_to_the_modeled_path():
    from dart.integrated_slam import run_integrated_slam
    truth, dr, tyaw, gyro = _katwijk()
    a = run_integrated_slam(truth, dr, tyaw, gyro, seed=0)
    b = run_integrated_slam(truth, dr, tyaw, gyro, seed=0, measured_fixes=None)
    assert np.array_equal(a["est_xy"], b["est_xy"]), "measured_fixes=None perturbed the modeled path"
    assert a["abs_max_err_m"] == b["abs_max_err_m"]
