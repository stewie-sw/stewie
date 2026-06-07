"""Validation tests for the audit-reassessment fixes (R2-R8)."""
import os

import numpy as np
import pytest

from solnav.eval import metrics
from solnav.geometry import height_ref as hr
from solnav.perception import camera_rig as cr
from solnav.perception import stereo_depth
from solnav.slam import posegraph as pg

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "frame")


# R2: metric domain validation
def test_metrics_reject_bad_input():
    with pytest.raises(ValueError):
        metrics.ate_rmse(np.zeros((0, 2)), np.zeros((0, 2)))
    with pytest.raises(ValueError):
        metrics.ate_rmse(np.zeros((3, 2)), np.zeros((4, 2)))
    with pytest.raises(ValueError):
        metrics.rpe_rmse(np.zeros((3, 3)), np.zeros((3, 3)), delta=0)
    with pytest.raises(ValueError):
        metrics.rpe_rmse(np.zeros((3, 3)), np.zeros((3, 3)), delta=3)


# R3: corrected vertical height-uncertainty value (named args)
def test_height_sigma_value_matches_finite_diff():
    H, D = 0.5, 8.0
    s = hr.triangulation_height_sigma_m(cam_h1_m=0.480, cam_h2_m=0.299,
                                        depression1_deg=hr.depression_to_landmark(0.480, H, D),
                                        depression2_deg=hr.depression_to_landmark(0.299, H, D),
                                        sigma_deg=0.5)
    assert 0.05 < s < 0.12          # ~0.078 m, not the bogus 0.011 m or the old 3.1 m


# R4: stereo auto-order is non-silent
@pytest.mark.skipif(not os.path.exists(FIX + "/front_left.png"), reason="stereo fixture absent")
def test_stereo_returns_order():
    from imageio.v3 import imread
    L = np.asarray(imread(FIX + "/front_left.png")); R = np.asarray(imread(FIX + "/front_right.png"))
    d, order = stereo_depth.compute_disparity(L, R, auto_order=True, return_order=True)
    assert order in ("normal", "swapped") and d.shape == L.shape[:2]
    # I2 default: production path does NOT auto-pick order
    d2 = stereo_depth.compute_disparity(L, R, return_order=True)
    assert d2[1] == "normal" if isinstance(d2, tuple) else True


# R5: default rig no longer collapses side cameras; axes consistent with yaw
def test_default_rig_side_cameras_distinct_and_axes_consistent():
    rig = cr.CameraRig()
    l = rig.camera_world_xy("left_mono", 0.0); r = rig.camera_world_xy("right_mono", 0.0)
    assert not np.allclose(l, r)                 # side cams no longer collapse
    assert rig.axis_angle_deg("front_left", "rear_left") > 150.0   # default quats from yaw, not identity


# R6: corrected requirement -- vertical and horizontal parallax constrain DIFFERENT axes,
# each tightening with its OWN baseline (not interchangeable scalars).
def test_parallax_axes_are_distinct_each_tightens_own_baseline():
    H, D = 0.5, 8.0
    # vertical (height) sigma drops as the HEIGHT baseline grows
    v_small = hr.triangulation_height_sigma_m(1.05, 1.0, hr.depression_to_landmark(1.05, H, D),
                                              hr.depression_to_landmark(1.0, H, D), 0.5)
    v_big = hr.triangulation_height_sigma_m(2.0, 1.0, hr.depression_to_landmark(2.0, H, D),
                                            hr.depression_to_landmark(1.0, H, D), 0.5)
    # horizontal (cross-range) sigma drops as the HORIZONTAL baseline grows
    h_small = cr.horizontal_triangulation_sigma_m(0.5, D, 0.5)
    h_big = cr.horizontal_triangulation_sigma_m(4.0, D, 0.5)
    assert v_big < v_small and h_big < h_small   # each constrains its own component


# R8: the robust (Huber) loss rejects a dominating outlier that least-squares cannot
def test_huber_rejects_dominating_outlier():
    # one pose, heading observed 4x at 0 deg and 1x at 40 deg (a gross outlier), equal info
    g = pg.PoseGraph(); g.add_prior(0, [0, 0, 0], info=(1e3, 1e3, 1e-3))   # weak heading prior
    for z in [0.0, 0.0, 0.0, 0.0, np.radians(40.0)]:
        g.add_heading(0, z, info=300.0)
    plain = abs(np.degrees(g.solve(np.array([[0, 0, 0.3]]))[0, 2]))
    huber = abs(np.degrees(g.solve(np.array([[0, 0, 0.3]]), huber_delta=2.0)[0, 2]))
    assert plain > 6.0 and huber < 3.0 and huber < plain   # LS pulled ~8 deg; Huber rejects -> ~2 deg
