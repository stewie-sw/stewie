"""Tests for dart.render_traverse: the END-TO-END adapter that turns a rendered traverse into a
scored fused SE(2) trajectory. All inputs are REAL committed renders (no synthetic pixels):

  * VO leg   -> the a6 rendered stereo traverse (stewie/eval/validation/a6_traverse, 4 frames).
  * PARALLAX -> the committed two-posture render-pair (stewie/godot/out/parallax, crater_boulders).

Truth poses are read only to score / associate, never fed to an estimator (invariant I3).
Tolerances are calibrated to the observed real-extractor outputs (VO recovers ~0.77 m vs truth
0.862 m; the parallax fix lands ~0.29 m from truth), not to fabricated values.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest
from imageio.v3 import imread

from dart import render_traverse as RT
from dart import stereo_vo

_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_A6 = os.path.join(_REPO, "stewie", "eval", "validation", "a6_traverse")
_PARALLAX = os.path.join(_REPO, "stewie", "godot", "out", "parallax")
_CRATER = os.path.join(_REPO, "samples", "crater_boulders")


def _a6_pairs_cfg():
    calib = json.load(open(os.path.join(_A6, "sequence.json")))["camera_calibration"]
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=384, height_px=288, hfov_deg=73.99,
                                            baseline_m=float(calib["baseline_m"]))
    cam = os.path.join(_A6, "cam")
    pairs = [(np.asarray(imread(os.path.join(cam, f"frame_{k:03d}", "front_left.png"))),
              np.asarray(imread(os.path.join(cam, f"frame_{k:03d}", "front_right.png")))) for k in range(4)]
    return pairs, cfg


def _a6_truth():
    poses = json.load(open(os.path.join(_A6, "truth", "truth.json")))["poses"]
    return np.array([[p["x"], p["z"]] for p in poses], float), np.array([p["yaw"] for p in poses], float)


@pytest.mark.skipif(not os.path.isdir(os.path.join(_A6, "cam", "frame_000")),
                    reason="a6 rendered stereo traverse not present")
def test_vo_world_trajectory_recovers_real_path_length():
    """REAL stereo VO over the 4 a6 frames -> world trajectory whose recovered length matches the
    eval-only truth length (0.862 m) within VO scale error, with every step solved (no fabricated)."""
    pairs, cfg = _a6_pairs_cfg()
    truth_xy, _ = _a6_truth()
    truth_len = float(np.sum(np.linalg.norm(np.diff(truth_xy, axis=0), axis=1)))
    out = RT.vo_world_trajectory(pairs, cfg, start_xy=tuple(truth_xy[0]), start_yaw=0.0)
    assert out["n_steps"] == 3 and out["n_valid"] == 3            # all three real steps solved
    assert out["xy"].shape == (4, 2) and np.all(np.isfinite(out["xy"]))
    # VO recovers the real path length within its scale error (observed ~0.77 m vs 0.862 m)
    assert abs(out["recovered_len_m"] - truth_len) / truth_len < 0.30
    # and the integrated endpoint is near the truth endpoint (short, mostly-straight real traverse)
    assert float(np.linalg.norm(out["xy"][-1] - truth_xy[-1])) < 0.5


@pytest.mark.skipif(not os.path.isdir(os.path.join(_A6, "cam", "frame_000")),
                    reason="a6 rendered stereo traverse not present")
def test_fused_traverse_on_real_vo_backbone_is_bounded():
    """Feed the REAL VO trajectory as the odometry backbone to run_integrated_slam and score ATE vs
    the a6 truth -- the render->fuse->score chain end to end on real pixels."""
    pairs, cfg = _a6_pairs_cfg()
    truth_xy, truth_yaw = _a6_truth()
    vo = RT.vo_world_trajectory(pairs, cfg, start_xy=tuple(truth_xy[0]), start_yaw=0.0)
    res = RT.fused_render_traverse(truth_xy, truth_yaw, dr_xy=vo["xy"], factors=("odom", "imu"))
    assert np.isfinite(res["ate_fused_m"]) and res["ate_fused_m"] < 0.5   # real VO over a ~0.86 m path
    assert res["n_keyframes"] == 4
    assert np.all(np.isfinite(np.asarray(res["fused_xy"])))


@pytest.mark.skipif(not os.path.exists(os.path.join(_PARALLAX, "A_sensors.json")),
                    reason="committed parallax render-pair not present")
def test_parallax_station_fixes_from_real_render_pair():
    """REAL absolute parallax fix extracted from the committed render-pair, packed for measured_fixes."""
    out = RT.parallax_station_fixes([{"k": 1, "render_dir": _PARALLAX, "scene_dir": _CRATER}])
    assert set(out["fixes"]) == {1}
    (xy, sigma) = out["fixes"][1]
    assert len(xy) == 2 and np.all(np.isfinite(xy)) and sigma > 0
    true_xy = out["truth_xy"][1]
    err = float(np.hypot(xy[0] - true_xy[0], xy[1] - true_xy[1]))
    assert err < 0.5                                              # observed ~0.29 m on the committed pair


@pytest.mark.skipif(not os.path.exists(os.path.join(_PARALLAX, "A_sensors.json")),
                    reason="committed parallax render-pair not present")
def test_real_parallax_fix_pulls_the_fused_estimate_toward_truth():
    """The fuser-glue: a REAL absolute parallax fix in measured_fixes pulls the estimate at its
    keyframe toward truth vs odometry-only drift. Endpoints are two REAL crater_boulders positions
    (the a6 start (1.0,2.56) and the parallax station (2.56,2.56)); the fix value is real-extracted."""
    out = RT.parallax_station_fixes([{"k": 1, "render_dir": _PARALLAX, "scene_dir": _CRATER}])
    fix = out["fixes"][1]
    truth_xy = np.array([[1.0, 2.56], [2.56, 2.56]], float)       # real scene positions (not fabricated path data)
    truth_yaw = np.array([0.0, 0.0], float)
    fused = RT.fused_render_traverse(truth_xy, truth_yaw, measured_fixes={"parallax": {1: fix}},
                                     factors=("odom", "imu", "parallax"), fix_interval=1,
                                     gyro_bias_rad=0.0, dr_xy=np.array([[1.0, 2.56], [3.2, 1.9]], float))
    odom = RT.fused_render_traverse(truth_xy, truth_yaw, factors=("odom", "imu"), fix_interval=1,
                                    gyro_bias_rad=0.0, dr_xy=np.array([[1.0, 2.56], [3.2, 1.9]], float))
    assert fused["n_measured"] >= 1                               # the real fix was consumed
    fused_end = np.asarray(fused["fused_xy"])[-1]
    odom_end = np.asarray(odom["fused_xy"])[-1]
    d_fused = float(np.linalg.norm(fused_end - truth_xy[-1]))
    d_odom = float(np.linalg.norm(odom_end - truth_xy[-1]))
    assert d_fused < d_odom                                       # the real fix genuinely pulls it back
