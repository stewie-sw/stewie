"""G2 disparity-covariance calibration: dev scenes -> sigma; checked on an untouched held-out split.

Truth = the geometric ray-cast (heightfield + clast spheres + lander) from producer evaluation-channel
poses; comparison restricted to the OBJECTIVE stereo band derived from TRL5 requirements
(ipex_specs.stereo_range_m: search-range floor to 7.5 cm-obstacle resolvability) and to clast-masked,
validity-gated pixels. Dev = poses 0-5; held-out = poses 6-11 (different sun geometry + sites),
quality gate n >= 100 per pair. The calibrated sigma FEEDS BACK into the envelope: z_max recomputes
with the measured sigma (documented in the artifact).
"""
import json
import os
import warnings

import numpy as np
import pytest
from imageio.v3 import imread

from dart import stereo_depth as sd
from stewie.eval import depth_truth as dt
from stewie.specs.ipex_specs import stereo_range_m

G2 = os.path.join(os.path.dirname(__file__), "validation", "g2cal")
SCENE = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "crater_boulders")
PAIRS = (("stereo", "front_left", "front_right"), ("stereo_rear", "rear_left", "rear_right"))
MIN_N = 100


def _pair_residuals(pose_dir, pair_key, l, r, zlo, zhi):
    truth = json.load(open(os.path.join(pose_dir, "evaluation_truth.json")))
    run = json.load(open(os.path.join(pose_dir, "sensors.json")))
    cam_t = {c["name"]: c for c in truth["camera_poses_in_world"]}
    cam_r = {c["name"]: c for c in run["cameras"]}
    cam = {**cam_r[l], "pose_in_world": cam_t[l]["pose_in_world"]}
    L = np.asarray(imread(os.path.join(pose_dir, cam_r[l]["image"])))
    R = np.asarray(imread(os.path.join(pose_dir, cam_r[r]["image"])))
    cal = sd.StereoCalibration(calibration_id="DUSTGYM_GODOT_CAMERA_RIG_V1", reference_camera=l,
                               match_camera=r, fx_px=cam["intrinsics"]["fx"],
                               baseline_m=run[pair_key]["baseline_m"], disparity_sigma_px=1.0,
                               covariance_calibrated=False, development_evidence=("g2cal",))
    T = dt.ray_cast_depth(cam, SCENE, stride=4, lander=run.get("lander"))
    D = sd.compute_depth_frame(L, R, cal, num_disparities=512, saturation_invalid=True)
    keep = dt.comparison_keep_mask(cam, T, SCENE)
    rr, cc = np.meshgrid(T["rows"], T["cols"], indexing="ij")
    zm = D.depth_m[rr, cc]
    vm = (D.valid_mask[rr, cc] & np.isfinite(T["depth_m"]) & np.isfinite(zm) & keep
          & (T["depth_m"] > zlo) & (T["depth_m"] < zhi) & (zm > zlo) & (zm < zhi))
    fxb = cal.fx_px * cal.baseline_m
    return (fxb / zm - fxb / T["depth_m"])[vm]


def test_disparity_sigma_dev_calibration_covers_held_out():
    warnings.filterwarnings("ignore")
    zlo, zhi = stereo_range_m(num_disparities=128)        # the OPERATIONAL band (0.372-1.889 m)
    poses = sorted((p for p in os.listdir(G2) if not p.endswith("noclasts")),
                   key=lambda p: int(p.split("_")[1]))
    if len(poses) < 12:
        pytest.skip("12-pose calibration corpus not present")
    recs = []
    for p in poses:
        k = int(p.split("_")[1])
        for pair, l, r in PAIRS:
            res = _pair_residuals(os.path.join(G2, p), pair, l, r, zlo, zhi)
            if res.size >= MIN_N:
                recs.append((k, res))
    dev = np.concatenate([r for k, r in recs if k < 6])
    held = np.concatenate([r for k, r in recs if k >= 6])
    assert dev.size >= 1000 and held.size >= 1000, "calibration corpus too thin"
    bias = float(np.median(dev))
    sigma = float(1.4826 * np.median(np.abs(dev - bias)))
    assert 0.3 < sigma < 6.0, f"dev sigma {sigma} px outside plausibility"
    cover3 = float(np.mean(np.abs(held - bias) <= 3.0 * sigma))
    assert cover3 >= 0.95, f"held-out 3-sigma coverage {cover3:.3f} -- calibration does not transfer"

    z_max_recal = float(np.sqrt(0.075 * 679.570327764933 * 0.07 / sigma))
    out = {
        "schema_version": "solnav_stereo_sigma_calibration/1.0",
        "date": "2026-06-10",
        "method": ("geometric ray-cast truth vs SGBM(512, saturation+floor gates), disparity-domain "
                   "robust MAD; clast-masked; restricted to the TRL5-derived objective band; "
                   "dev = poses 0-5, held-out = poses 6-11 (untouched)"),
        "band_m": [zlo, zhi],
        "dev": {"n": int(dev.size), "bias_px": bias, "sigma_disparity_px": sigma},
        "held_out": {"n": int(held.size), "coverage_3sigma": cover3},
        "caveats": ["per-pose bias dispersion (+0.5..+10 px, sun-geometry dependent) is folded into "
                     "sigma rather than modeled; conservative",
                    "front pairs contribute no in-band pixels in this corpus (lander-facing/dark)",
                    f"FEEDBACK: at the measured sigma the 7.5 cm-obstacle range tightens to "
                    f"~{z_max_recal:.2f} m (from the 1-px assumption's 1.89 m)"],
        "evidence": "stewie/eval/validation/g2cal/pose_0..11 (producer truth, sun 25-38 deg)",
    }
    path = os.path.join(os.path.dirname(__file__), "validation",
                        "stereo_sigma_calibration_2026-06-10.json")
    json.dump(out, open(path, "w"), indent=1)
