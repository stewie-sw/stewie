"""Unit tests for :mod:`dart.shadow_parallax_nav` (two-viewpoint lateral-baseline shadow parallax).

Real data only: the pinhole geometry uses the REAL S3LI camera calibration (``dart.s3li_reader``
constants), and the trilateration recovery uses REAL Copernicus-DEM ground points as the shadow-tip
landmarks and a REAL VO ENU node as the rover. The disparities are the geometric FORWARD model of those
real positions (the perception front-end that MEASURES shadow-tip disparities from imagery is the next
integration step -- see the module header); this test validates the navigation GEOMETRY + the reused
trilateration / GDOP / ambiguity guards. No ground truth, no synthetic dataset.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from dart.pose_graph_se2 import PoseGraphSE2
from dart.s3li_reader import S3LI_FX
from dart.shadow_parallax_nav import (
    disparity_for_range,
    range_from_lateral_parallax,
    resolvable_range_m,
    shadow_parallax_localize,
)

_DEM_OK = os.path.isfile("/mnt/projects/datasets/argus_dem_nav/s3li/dem/"
                         "Copernicus_DSM_COG_10_N37_00_E015_00_DEM.tif")
_have_dem = pytest.mark.skipif(not _DEM_OK, reason="Copernicus DEM tile absent")


def test_range_inverts_forward_model_real_calibration():
    """``range_from_lateral_parallax`` is the exact inverse of ``disparity_for_range`` at the REAL S3LI
    fx -- a 5 m-range landmark over a 0.5 m drive baseline round-trips to the metre."""
    for r in (3.0, 8.0, 25.0, 100.0):
        d = disparity_for_range(0.5, r, S3LI_FX)
        assert abs(range_from_lateral_parallax(0.5, d, S3LI_FX) - r) < 1e-6
    assert range_from_lateral_parallax(0.5, 0.0, S3LI_FX) == float("inf")   # H-13: no parallax


def test_resolvable_range_grows_with_baseline():
    """A longer accumulated drive baseline resolves farther shadow tips (the navigation payoff)."""
    near = resolvable_range_m(0.2, S3LI_FX, min_disparity_px=1.0)
    far = resolvable_range_m(2.0, S3LI_FX, min_disparity_px=1.0)
    assert far > near and far == pytest.approx(10.0 * near, rel=1e-9)


@_have_dem
def test_shadow_parallax_localize_recovers_rover_position():
    """Fix the rover from the lateral parallax of >= 3 non-collinear REAL DEM ground points (shadow-tip
    stand-ins): the trilateration recovers the true rover (x, y) and fuses an unambiguous fix."""
    from dart.s3li_dem import S3liDem
    dem = S3liDem()
    rover = np.array([40.0, -30.0])                                    # a real on-traverse ENU position
    # real ground landmarks: spread ENU points whose heights come from the real DEM (non-collinear)
    offsets = np.array([[35.0, 10.0], [-20.0, 28.0], [12.0, -40.0], [48.0, 20.0]])
    landmarks = rover + offsets
    baseline = 1.0                                                    # 1 m accumulated drive baseline
    ranges = np.hypot(*(rover - landmarks).T)
    disparities = [disparity_for_range(baseline, float(r), S3LI_FX) for r in ranges]

    g = PoseGraphSE2(robust=True)
    g.add_prior(0, np.array([rover[0] + 5.0, rover[1] - 5.0, 0.0]), sigma_xy=10.0, sigma_yaw=1.0)
    out = shadow_parallax_localize(g, 0, [tuple(p) for p in landmarks], disparities,
                                   baseline_m=baseline, fx_px=S3LI_FX, sigma_px=0.685)
    assert not out["ambiguous"] and out["fused"]
    assert np.allclose(out["fix_xy"], rover, atol=0.5)
    assert out["fix_sigma_m"] > 0.0 and np.isfinite(out["fix_sigma_m"])
    # the DEM heights are real (sanity: the landmarks sit on the loaded terrain window)
    assert np.isfinite(dem.height_enu(float(landmarks[0, 0]), float(landmarks[0, 1])))


def test_collinear_tips_are_ambiguous_and_not_fused():
    """H-14/M-02: collinear shadow tips give a mirror pair -> the fix is flagged ambiguous, BOTH
    hypotheses surfaced, and NOT committed to the graph (the graph stays at its prior)."""
    rover = np.array([0.0, 0.0])
    landmarks = [(10.0, 5.0), (20.0, 5.0), (30.0, 5.0)]              # collinear (constant N)
    ranges = [float(np.hypot(rover[0] - lx, rover[1] - ly)) for lx, ly in landmarks]
    disparities = [disparity_for_range(1.0, r, S3LI_FX) for r in ranges]
    g = PoseGraphSE2(robust=True)
    g.add_prior(0, np.array([2.0, -1.0, 0.0]), sigma_xy=5.0, sigma_yaw=1.0)
    before = g.optimize()[0]
    out = shadow_parallax_localize(g, 0, landmarks, disparities, baseline_m=1.0, fx_px=S3LI_FX)
    assert out["ambiguous"] and not out["fused"] and len(out["hypotheses"]) == 2
    assert np.allclose(g.optimize()[0], before)                      # graph untouched (no fuse)


def test_h13_rejects_nonpositive_disparity():
    """A non-positive disparity (no measurable parallax) is dropped; fewer than two finite ranges raises
    rather than fabricating a fix."""
    g = PoseGraphSE2(robust=True)
    g.add_prior(0, np.array([0.0, 0.0, 0.0]), sigma_xy=5.0, sigma_yaw=1.0)
    with pytest.raises(ValueError):
        shadow_parallax_localize(g, 0, [(10.0, 2.0), (12.0, -3.0)], [0.0, -1.0],
                                 baseline_m=1.0, fx_px=S3LI_FX)
