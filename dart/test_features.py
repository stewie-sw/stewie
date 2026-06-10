"""TDD for solnav.perception.features: a unified CLASSICAL (cv2 ORB/SIFT) and LEARNED
(kornia DISK + LightGlue) feature front end benchmarked on the REAL rendered lunar stereo pair.

Real inputs only. The fundamental-matrix RANSAC and Sampson-distance checks recover a genuine
numeric geometric quantity (epipolar error of inlier correspondences), not a tautology. The
ground-truth clast count enters ONLY the eval-path helper, never the perception input (invariant I3).
"""
import os

import numpy as np
import pytest

from dart import features

HERE = os.path.dirname(__file__)
# REAL rendered lunar stereo pair (Godot sensor model on the crater_boulders scene).
PAIR = os.path.join(HERE, "..", "stewie", "eval", "validation", "a6_traverse", "cam", "frame_000")
_LEFT = os.path.join(PAIR, "front_left.png")
_RIGHT = os.path.join(PAIR, "front_right.png")
_pair = os.path.exists(_LEFT) and os.path.exists(_RIGHT)

# EVAL-ONLY truth source (clast positions); must never reach a perception input.
CLAST_TRUTH = "/mnt/projects/stewie/code/samples/crater_boulders/metadata.json"
_truth = os.path.exists(CLAST_TRUTH)


def _load_pair():
    from imageio.v3 import imread
    left = np.asarray(imread(_LEFT))
    right = np.asarray(imread(_RIGHT))
    return left, right


# ---- pure / numeric (no external assets) ----
def test_sampson_distance_zero_for_exact_epipolar_pair():
    """A pure horizontal shift x' = x - d, y' = y has fundamental matrix F = [[0,0,0],[0,0,1],[0,-1,0]]
    (the rectified-stereo F). Points on it satisfy x'^T F x = 0 exactly -> zero Sampson distance.
    This recovers the analytic value 0, not a tautology over the estimator output."""
    # fixed canonical image points (deterministic analytic test vectors for the formula -- no random data)
    xs = np.arange(20.0, 200.0, 18.0)   # 10 columns
    ys = np.arange(20.0, 200.0, 36.0)   # 5 rows -> 50 fixed points
    pts1 = np.array([[x, y] for x in xs for y in ys])
    disp = 7.0
    pts2 = pts1.copy()
    pts2[:, 0] -= disp  # horizontal disparity only -> y' == y
    F = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    d = features.sampson_distances(pts1, pts2, F)
    assert d.shape == (50,)
    assert float(np.median(d)) < 1e-9


def test_sampson_distance_grows_with_vertical_offset():
    """Breaking the epipolar constraint with a vertical offset must increase Sampson distance,
    monotonically -- a recovered numeric relationship, not a constant."""
    pts1 = np.array([[100.0, 80.0], [120.0, 90.0], [60.0, 150.0]])
    F = np.array([[0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    pts2_ok = pts1.copy(); pts2_ok[:, 0] -= 5.0
    pts2_bad = pts2_ok.copy(); pts2_bad[:, 1] += 3.0  # vertical violation
    d_ok = features.sampson_distances(pts1, pts2_ok, F)
    d_bad = features.sampson_distances(pts1, pts2_bad, F)
    assert np.all(d_bad > d_ok)
    # F here is rectified: vertical residual r -> Sampson |r| / sqrt(2) per the [0,0,1;0,-1,0] form.
    assert np.allclose(d_bad, 3.0 / np.sqrt(2.0), atol=1e-9)


def test_unknown_method_rejected():
    left = np.zeros((32, 32, 3), np.uint8)
    with pytest.raises(ValueError, match="method"):
        features.benchmark_method(left, left, "not_a_method")


def test_methods_registry_lists_classical_and_learned():
    names = set(features.available_methods())
    assert {"orb", "sift"} <= names          # classical
    assert {"disk_lightglue"} <= names       # learned


# ---- real rendered lunar stereo ----
@pytest.mark.skipif(not _pair, reason="rendered stereo pair not present")
@pytest.mark.parametrize("method", ["orb", "sift"])
def test_classical_method_on_real_stereo(method):
    left, right = _load_pair()
    res = features.benchmark_method(left, right, method)
    assert res.method == method
    assert res.n_keypoints_left > 0 and res.n_keypoints_right > 0
    assert res.n_raw_matches >= 8           # need >=8 for a fundamental matrix
    assert 0.0 <= res.inlier_ratio <= 1.0   # MATH: ratio in [0,1]
    assert res.runtime_s > 0.0
    # Sampson error of accepted inliers must be small (sub-pixel-to-few-pixel band).
    assert np.isfinite(res.median_sampson_px)
    assert res.median_sampson_px < 5.0


@pytest.mark.skipif(not _pair, reason="rendered stereo pair not present")
def test_learned_method_on_real_stereo():
    left, right = _load_pair()
    res = features.benchmark_method(left, right, "disk_lightglue")
    assert res.method == "disk_lightglue"
    assert res.n_keypoints_left > 0 and res.n_keypoints_right > 0
    assert res.n_raw_matches >= 8
    assert 0.0 <= res.inlier_ratio <= 1.0
    assert res.runtime_s > 0.0
    assert np.isfinite(res.median_sampson_px)
    assert res.median_sampson_px < 5.0


@pytest.mark.skipif(not _pair, reason="rendered stereo pair not present")
def test_math_check_at_least_one_method_exceeds_inlier_floor():
    """MATH: on the REAL stereo, at least one method has a fundamental-RANSAC inlier ratio in
    [0,1] AND > 0.3, with small median Sampson (epipolar) error on its inliers."""
    left, right = _load_pair()
    results = features.benchmark_all(left, right)
    assert len(results) >= 3
    good = [
        r for r in results
        if 0.0 <= r.inlier_ratio <= 1.0 and r.inlier_ratio > 0.3 and r.median_sampson_px < 3.0
    ]
    assert good, f"no method cleared the inlier/epipolar floor: {[ (r.method, r.inlier_ratio) for r in results]}"


# ---- visual artifact ----
@pytest.mark.skipif(not _pair, reason="rendered stereo pair not present")
def test_visualization_png_written(tmp_path):
    left, right = _load_pair()
    res = features.benchmark_method(left, right, "sift")
    out = tmp_path / "sift_matches.png"
    path = features.save_match_visualization(left, right, res, str(out))
    assert os.path.exists(path)
    assert os.path.getsize(path) > 1000     # a real raster, not an empty file


# ---- invariant I3: ground-truth firewall ----
@pytest.mark.skipif(not _truth, reason="crater_boulders truth metadata not present")
def test_clast_truth_is_eval_only_and_does_not_touch_matching():
    """The clast count is a real EVAL quantity (143 boulders in the scene metadata). It is read by an
    eval-path helper and is NEVER an argument to the perception API -- benchmark_method's signature
    accepts images only. This guards invariant I3 (truth firewall)."""
    import inspect
    n = features.count_clasts_in_truth(CLAST_TRUTH)
    assert n == 143
    sig = inspect.signature(features.benchmark_method)
    params = set(sig.parameters)
    for forbidden in ("clast", "truth", "metadata", "pose", "slip", "gt", "ground_truth"):
        assert not any(forbidden in p for p in params), f"perception input leaks truth via '{forbidden}'"
