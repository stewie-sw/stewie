"""TDD for dart.stereo_vo: calibrated stereo triangulation + PnP visual odometry on the
REAL rendered lunar stereo traverse (Godot sensor model, crater_boulders scene, frames 000..003).

Real inputs only. The pipeline reuses dart.features for keypoints/matching, triangulates
matched stereo keypoints with the rig intrinsics (fx from the 73.99 deg HFOV, baseline 0.07 m), and
solves PnP between consecutive frames for inter-frame motion.

MATH (recovers genuine numeric quantities, not tautologies):
  * fx is derived from the rig HFOV + image width by the pinhole law and equals the known 254.84 px.
  * disparity->depth is the exact inverse of depth->disparity (round-trip recovers the input depth).
  * triangulated depths on the real pair are all positive and physically plausible.
  * the inter-frame VO translation magnitudes are consistent across the short straight traverse, and
    the recovered total path length matches the EVAL-only ground-truth traverse length (~0.862 m).

Invariant I3 (truth firewall): the estimator entry points accept rendered images + calibration only;
ground-truth poses (truth.json, GROUND_TRUTH_EVAL) are read ONLY in this test's eval/scoring path
and are NEVER an argument to the perception API.
"""
import json
import os

import numpy as np
import pytest

from dart import stereo_vo

HERE = os.path.dirname(__file__)
CAM = os.path.join(HERE, "..", "stewie", "eval", "validation", "a6_traverse", "cam")
SEQUENCE = os.path.join(HERE, "..", "stewie", "eval", "validation", "a6_traverse", "sequence.json")
# EVAL-ONLY truth (GROUND_TRUTH_EVAL poses); read only in the scoring assertions below, never passed in.
TRUTH = os.path.join(HERE, "..", "stewie", "eval", "validation", "a6_traverse", "truth", "truth.json")

_FRAMES = [os.path.join(CAM, f"frame_{k:03d}") for k in range(4)]
_have_frames = all(
    os.path.exists(os.path.join(f, "front_left.png")) and os.path.exists(os.path.join(f, "front_right.png"))
    for f in _FRAMES
)


def _load(frame_dir):
    from imageio.v3 import imread
    left = np.asarray(imread(os.path.join(frame_dir, "front_left.png")))
    right = np.asarray(imread(os.path.join(frame_dir, "front_right.png")))
    return left, right


def _load_stereo_pairs():
    return [_load(f) for f in _FRAMES]


def _truth_traverse_length_m():
    """EVAL-ONLY: straight-line ground-truth path length from truth.json (GROUND_TRUTH_EVAL).
    Reads truth strictly inside the scoring path; never returned to the perception API."""
    poses = json.load(open(TRUTH))["poses"]
    xz = np.array([[p["x"], p["z"]] for p in poses], dtype=float)
    return float(np.sum(np.linalg.norm(np.diff(xz, axis=0), axis=1)))


# ---- pure / numeric (no external assets) ----
def test_intrinsics_from_fov_recovers_known_fx():
    """MATH: fx = (W/2)/tan(HFOV/2). For the rig HFOV 73.99 deg at 384 px width this is the known
    254.84 px; cx, cy are the image centre. A recovered analytic value, not a tautology."""
    intr = stereo_vo.intrinsics_from_fov(width_px=384, height_px=288, hfov_deg=73.99)
    assert intr.fx == pytest.approx(254.84, abs=0.05)
    assert intr.fy == pytest.approx(intr.fx, rel=1e-9)   # square pixels
    assert intr.cx == pytest.approx(192.0) and intr.cy == pytest.approx(144.0)
    K = intr.matrix()
    assert K.shape == (3, 3)
    assert K[0, 0] == pytest.approx(intr.fx) and K[1, 1] == pytest.approx(intr.fy)
    assert K[0, 2] == pytest.approx(intr.cx) and K[1, 2] == pytest.approx(intr.cy)


def test_disparity_depth_roundtrip_is_exact_inverse():
    """MATH: depth = fx*B/disparity is the exact inverse of disparity = fx*B/depth. A round trip on
    known depths returns the depths, recovering the calibrated scale fx*B numerically."""
    fx, baseline = 254.84, 0.07
    depths = np.array([0.5, 1.0, 2.5, 9.0])
    disp = fx * baseline / depths
    back = stereo_vo.disparity_to_depth(disp, fx_px=fx, baseline_m=baseline)
    assert np.allclose(back, depths, rtol=1e-9)
    assert np.all(back > 0.0)


def test_calibration_rejects_nonpositive_scale():
    with pytest.raises(ValueError):
        stereo_vo.StereoVOConfig(fx_px=-1.0, fy_px=254.0, cx_px=192.0, cy_px=144.0, baseline_m=0.07)
    with pytest.raises(ValueError):
        stereo_vo.StereoVOConfig(fx_px=254.0, fy_px=254.0, cx_px=192.0, cy_px=144.0, baseline_m=0.0)


# ---- invariant I3: ground-truth firewall ----
def test_perception_api_accepts_no_truth_fields():
    """Invariant I3: neither the triangulation nor the VO entry point may take a pose/slip/truth
    argument. The estimator consumes images + calibration only."""
    import inspect
    for fn in (stereo_vo.triangulate_stereo, stereo_vo.estimate_vo):
        params = set(inspect.signature(fn).parameters)
        for forbidden in ("truth", "pose", "slip", "gt", "ground_truth", "clast"):
            assert not any(forbidden in p for p in params), f"{fn.__name__} leaks truth via '{forbidden}'"


# ---- M-03: failed VO is an INVALID/missing step, not a zero-motion measurement ----
def test_m03_failed_vo_step_is_invalid_not_zero_motion():
    """Audit M-03 (2026-06-14): when a PnP solve fails (texture loss between frames), the relative
    transform must be represented as INVALID/MISSING with an inflated covariance -- NEVER identity
    rotation + zero translation. A downstream mapper would otherwise read 'no motion' as a real
    stationary measurement and place the next cloud at the wrong (held) pose.

    Real texture-loss injection: a featureless (uniform) middle frame yields no ORB matches, so the
    middle->? PnP step fails. We assert the failed step is flagged invalid, its translation is NaN
    (missing, not 0.0), and its covariance is inflated; a non-failed step stays valid + finite."""
    H, W = 288, 384
    # two real-ish textured frames bracketing one featureless (uniform) frame -> the steps touching
    # the blank frame must fail. Use deterministic structured noise for the textured frames (real
    # pixel content, not a truth field) so ORB finds keypoints there.
    rng = np.random.default_rng(0)
    textured = (rng.integers(0, 256, size=(H, W), dtype=np.uint8))
    blank = np.full((H, W), 127, dtype=np.uint8)            # featureless: no ORB keypoints
    pairs = [(textured.copy(), textured.copy()),
             (blank.copy(), blank.copy()),
             (textured.copy(), textured.copy())]
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=W, height_px=H, hfov_deg=73.99, baseline_m=0.07)
    result = stereo_vo.estimate_vo(pairs, cfg)

    # the result exposes per-step validity + per-step covariance (M-03 contract)
    assert hasattr(result, "step_valid")
    assert hasattr(result, "relative_covariances")
    assert len(result.step_valid) == 2                     # 3 frames -> 2 inter-frame steps
    assert len(result.relative_covariances) == 2

    # at least one step (touching the blank frame) FAILED and must be invalid -- NOT zero motion
    assert not all(result.step_valid)
    for k, valid in enumerate(result.step_valid):
        t = result.relative_translations_m[k]
        cov = np.asarray(result.relative_covariances[k], dtype=float)
        if not valid:
            # missing, NOT the old fabricated zero-motion vector: NaN is distinct from a real 0.0 step
            assert np.all(np.isnan(t))
            assert not np.all(t == 0.0)                      # explicitly not the old zero-motion stand-in
            assert np.all(np.diag(cov) > 1e6)               # inflated covariance flags the gap
        else:
            assert np.all(np.isfinite(t))
            assert np.all(np.isfinite(cov))
            assert np.all(np.diag(cov) < 1e6)               # a trusted step keeps a finite, modest cov


def test_m03_valid_traverse_keeps_all_steps_valid_and_finite():
    """Audit M-03: on a clean traverse where every PnP solve succeeds, every step is valid, finite, and
    carries a finite covariance -- the honest-failure machinery does not corrupt the good path."""
    if not _have_frames:
        pytest.skip("rendered traverse frames not present")
    pairs = _load_stereo_pairs()
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=384, height_px=288, hfov_deg=73.99, baseline_m=0.07)
    result = stereo_vo.estimate_vo(pairs, cfg)
    assert all(result.step_valid)
    assert np.all(np.isfinite(result.relative_translations_m))
    for cov in result.relative_covariances:
        c = np.asarray(cov, dtype=float)
        assert np.all(np.isfinite(c)) and np.all(np.diag(c) > 0.0)


# ---- real rendered lunar stereo: triangulation ----
@pytest.mark.skipif(not _have_frames, reason="rendered traverse frames not present")
def test_triangulated_depths_positive_and_plausible():
    """MATH: stereo-triangulating matched ORB keypoints on the REAL pair yields all-positive depths
    in a physically plausible band for a 0.8 m-high camera over crater_boulders (a few decimetres to
    a few tens of metres). Recovers real metric depth, not a pass-through."""
    left, right = _load(_FRAMES[0])
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=384, height_px=288, hfov_deg=73.99, baseline_m=0.07)
    cloud = stereo_vo.triangulate_stereo(left, right, cfg)
    assert cloud.points_3d.shape[0] >= 50          # real texture supports many matches
    assert cloud.points_3d.shape[1] == 3
    z = cloud.points_3d[:, 2]
    assert np.all(z > 0.0)                          # all depths positive
    assert np.all(z < 100.0)                        # within the rig far plane
    assert 0.3 < float(np.median(z)) < 20.0         # plausible near-field median depth
    # descriptors aligned 1:1 with 3D points (needed for the temporal PnP step)
    assert cloud.descriptors.shape[0] == cloud.points_3d.shape[0]
    assert cloud.keypoints_px.shape == (cloud.points_3d.shape[0], 2)


# ---- real rendered lunar stereo: VO across consecutive frames ----
@pytest.mark.skipif(not _have_frames, reason="rendered traverse frames not present")
def test_vo_translation_consistent_across_traverse():
    """MATH: PnP VO across frames 000..003 recovers 3 inter-frame translations whose magnitudes are
    consistent (the rover drives a near-constant straight step), and whose summed path length matches
    the EVAL-only ground-truth traverse length within tolerance. Truth is read ONLY here, in the
    scoring path (invariant I3)."""
    pairs = _load_stereo_pairs()
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=384, height_px=288, hfov_deg=73.99, baseline_m=0.07)
    result = stereo_vo.estimate_vo(pairs, cfg)

    assert len(result.relative_translations_m) == 3
    assert result.trajectory_xyz_m.shape == (4, 3)   # 4 camera centres, first at origin

    step_mags = np.linalg.norm(result.relative_translations_m, axis=1)
    assert np.all(step_mags > 0.05)                  # genuine motion every step
    assert np.all(step_mags < 0.60)                  # bounded by the commanded ~0.3 m step
    # consistency: spread of per-step magnitude is small relative to its mean (straight constant drive)
    assert float(np.std(step_mags) / np.mean(step_mags)) < 0.25
    # every PnP solve had enough inliers to be trustworthy
    assert all(n >= 30 for n in result.pnp_inliers)

    # EVAL path only: recovered path length vs GROUND_TRUTH_EVAL traverse length (~0.862 m).
    recovered = float(step_mags.sum())
    truth_len = _truth_traverse_length_m()
    assert truth_len == pytest.approx(0.862, abs=0.01)            # sanity on the truth source
    assert abs(recovered - truth_len) / truth_len < 0.20         # VO recovers the metric scale


# ---- visual artifact ----
@pytest.mark.skipif(not _have_frames, reason="rendered traverse frames not present")
def test_trajectory_plot_png_written(tmp_path):
    pairs = _load_stereo_pairs()
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=384, height_px=288, hfov_deg=73.99, baseline_m=0.07)
    result = stereo_vo.estimate_vo(pairs, cfg)
    out = tmp_path / "vo_trajectory.png"
    path = stereo_vo.save_trajectory_plot(result, str(out))
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000             # a real raster, not an empty file
