"""G2 depth-truth: independent geometric truth vs the stereo chain (blockers 1 + 2).

Dev/held-out split uses two PHYSICAL stereo pairs from the committed capture: the FRONT pair
calibrates the disparity sigma (development evidence); the REAR pair -- different cameras,
different scene content, untouched by calibration -- checks the calibrated model. Truth is the
ray-cast of the conserved scene geometry (heightfield + clast spheres + the procedural lander)
from evaluation-channel poses; it consumes no image pixels (I3).
"""
import json
import os

import numpy as np
import pytest
from imageio.v3 import imread

from dart import stereo_depth as sd
from stewie.eval import depth_truth as dt

FIX = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "frame")
SCENE = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "crater_boulders")
NUM_DISP = 512                       # fx*b/512 ~ 0.09 m: covers this low rig's near field


def _setup(pair_key, left_name, right_name):
    truth = json.load(open(os.path.join(FIX, "evaluation_truth.json")))
    run = json.load(open(os.path.join(FIX, "runtime_sensors.json")))
    cam_t = {c["name"]: c for c in truth["camera_poses_in_world"]}
    cam_r = {c["name"]: c for c in run["cameras"]}
    cam = {**cam_r[left_name], "pose_in_world": cam_t[left_name]["pose_in_world"]}
    L = np.asarray(imread(os.path.join(FIX, cam_r[left_name]["image"])))
    R = np.asarray(imread(os.path.join(FIX, cam_r[right_name]["image"])))
    cal = sd.StereoCalibration(
        calibration_id=run["calibration_id"], reference_camera=left_name,
        match_camera=right_name, fx_px=cam["intrinsics"]["fx"],
        baseline_m=run[pair_key]["baseline_m"], disparity_sigma_px=1.0,
        covariance_calibrated=False, development_evidence=("g2_depth_truth_dev",))
    T = dt.ray_cast_depth(cam, SCENE, stride=8, lander=truth["lander"])
    D = sd.compute_depth_frame(L, R, cal, num_disparities=NUM_DISP)
    return cam, cal, T, D


def _joint_residual_disparity_px(cam, cal, T, D):
    """Measured-vs-truth residual in the DISPARITY domain on jointly valid pixels."""
    r, c = np.meshgrid(T["rows"], T["cols"], indexing="ij")
    sdep = D.depth_m[r, c]
    vm = D.valid_mask[r, c] & np.isfinite(T["depth_m"]) & np.isfinite(sdep)
    fxb = cal.fx_px * cal.baseline_m
    d_meas = fxb / sdep[vm]
    d_true = fxb / T["depth_m"][vm]
    return d_meas - d_true


def test_front_pair_truth_reconciles_dev():
    cam, cal, T, D = _setup("stereo", "front_left", "front_right")
    r, c = np.meshgrid(T["rows"], T["cols"], indexing="ij")
    vm = D.valid_mask[r, c] & np.isfinite(T["depth_m"]) & np.isfinite(D.depth_m[r, c])
    assert int(vm.sum()) >= 100, "too few jointly valid pixels to claim reconciliation"
    res = (D.depth_m[r, c] - T["depth_m"])[vm]
    assert float(np.median(np.abs(res))) < 0.05      # centimetre-level agreement (measured 0.020 m)


def test_disparity_sigma_calibrates_on_dev_and_covers_held_out_rear():
    # DEV: front pair -> robust sigma in disparity px
    cam_f, cal_f, T_f, D_f = _setup("stereo", "front_left", "front_right")
    res_f = _joint_residual_disparity_px(cam_f, cal_f, T_f, D_f)
    sigma_px = float(1.4826 * np.median(np.abs(res_f - np.median(res_f))))
    assert 0.05 < sigma_px < 5.0, f"calibrated sigma {sigma_px} px out of any plausible range"

    # HELD-OUT: rear pair, untouched by the calibration above
    cam_r_, cal_r_, T_r, D_r = _setup("stereo_rear", "rear_left", "rear_right")
    res_r = _joint_residual_disparity_px(cam_r_, cal_r_, T_r, D_r)
    if res_r.size < 30:
        pytest.skip(f"rear pair yields only {res_r.size} joint pixels -- not enough to score coverage")
    bias_r = float(np.median(res_r))
    cover3 = float(np.mean(np.abs(res_r - bias_r) <= 3.0 * sigma_px))
    assert cover3 >= 0.80, (f"held-out 3-sigma coverage {cover3:.2f} with dev sigma {sigma_px:.2f} px "
                            "-- the dev calibration does not transfer")

    # persist the calibration as a NEW dated evidence artifact (the frozen 2026-06-07 gate
    # artifact is never edited)
    out = {
        "schema_version": "solnav_stereo_sigma_calibration/1.0",
        "date": "2026-06-09",
        "method": "geometric ray-cast truth (stewie/eval/depth_truth.py) vs SGBM, disparity-domain "
                  "robust MAD sigma; dev = front pair, held-out = rear pair (different cameras)",
        "num_disparities": NUM_DISP,
        "dev": {"pair": "front", "n": int(res_f.size), "sigma_disparity_px": sigma_px,
                "bias_px": float(np.median(res_f))},
        "held_out": {"pair": "rear", "n": int(res_r.size), "bias_px": bias_r,
                     "coverage_3sigma": cover3},
    }
    path = os.path.join(os.path.dirname(__file__), "validation",
                        "stereo_sigma_calibration_2026-06-09.json")
    json.dump(out, open(path, "w"), indent=1)
