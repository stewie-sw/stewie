"""PM-13: stereo-perception MEASUREMENT producer (Convergence Phase B, rec #6).

Turns the tested G2 stereo pipeline into a reusable PRODUCER that reports the DENSE DEPTH RMSE of the
SGBM-observed depth vs the geometric ray-cast truth, over a real rendered stereo pair -- the dense
reconstruction metric `map_channel` flags as the gated tier (`dense_rmse_available`). It reuses, verbatim,
the same building blocks the G2 calibration test is built on (`dart.stereo_depth` SGBM +
`stewie.eval.depth_truth` ray-cast truth + clast masking + the TRL5-derived objective band from
`ipex_specs.stereo_range_m`), so correctness is inherited from that tested path.

Honesty: REAL rendered frames + geometric truth only -- no synthetic input. The metric is restricted to
validity-gated, clast-masked pixels inside the objective stereo band (so it measures what the rig can
actually resolve, not saturated sky or out-of-range floor). A pose with too few in-band pixels returns
n_valid below the caller's threshold rather than a fabricated number.
"""
from __future__ import annotations

import json
import os

import numpy as np
from imageio.v3 import imread

from dart import stereo_depth as sd
from stewie.eval import depth_truth as dt
from stewie.specs.ipex_specs import stereo_range_m


def measure_pair(pose_dir: str, scene_dir: str, *, pair_key: str = "stereo_rear",
                 left: str = "rear_left", right: str = "rear_right",
                 num_disparities: int = 128, stride: int = 4) -> dict:
    """Dense depth measurement for ONE rendered stereo pair at `pose_dir` against the conserved scene at
    `scene_dir`. Returns the observed-vs-truth depth RMSE (m), mean abs error, the in-band valid-pixel
    count + fraction, and the objective band used. Reuses the tested ray-cast truth + SGBM + clast mask.
    Raises FileNotFoundError if the pose dir lacks the rendered run / truth (the caller decides to skip)."""
    run = json.load(open(os.path.join(pose_dir, "sensors.json")))
    truth = json.load(open(os.path.join(pose_dir, "evaluation_truth.json")))
    cam_t = {c["name"]: c for c in truth["camera_poses_in_world"]}
    cam_r = {c["name"]: c for c in run["cameras"]}
    cam = {**cam_r[left], "pose_in_world": cam_t[left]["pose_in_world"]}
    L = np.asarray(imread(os.path.join(pose_dir, cam_r[left]["image"])))
    R = np.asarray(imread(os.path.join(pose_dir, cam_r[right]["image"])))
    intr = cam["intrinsics"]
    cal = sd.StereoCalibration(calibration_id="STEWIE_GODOT_CAMERA_RIG_V1", reference_camera=left,
                               match_camera=right, fx_px=intr["fx"], baseline_m=run[pair_key]["baseline_m"],
                               disparity_sigma_px=1.0, covariance_calibrated=False,
                               development_evidence=("g2cal",))
    zlo, zhi = stereo_range_m(num_disparities=num_disparities)            # the TRL5-derived objective band
    T = dt.ray_cast_depth(cam, scene_dir, stride=stride, lander=run.get("lander"))
    D = sd.compute_depth_frame(L, R, cal, num_disparities=512, saturation_invalid=True)
    keep = dt.comparison_keep_mask(cam, T, scene_dir)                     # clast/lander masking
    rr, cc = np.meshgrid(T["rows"], T["cols"], indexing="ij")
    zm, zt = D.depth_m[rr, cc], T["depth_m"]
    vm = (D.valid_mask[rr, cc] & np.isfinite(zt) & np.isfinite(zm) & keep
          & (zt > zlo) & (zt < zhi) & (zm > zlo) & (zm < zhi))
    err = (zm - zt)[vm]
    n = int(vm.sum())
    return {
        "n_valid": n,
        "valid_frac": float(np.mean(vm)) if vm.size else 0.0,
        "depth_rmse_m": float(np.sqrt(np.mean(err ** 2))) if n else float("nan"),
        "depth_mean_abs_err_m": float(np.mean(np.abs(err))) if n else float("nan"),
        "depth_bias_m": float(np.median(err)) if n else float("nan"),
        "band_m": [float(zlo), float(zhi)],
    }


def measure_corpus(corpus_dir: str, scene_dir: str, *, pairs=(("stereo_rear", "rear_left", "rear_right"),
                                                               ("stereo", "front_left", "front_right")),
                   min_n: int = 50, num_disparities: int = 128) -> dict:
    """Aggregate the dense depth RMSE over every `pose_*` dir in `corpus_dir` (each pair with >= min_n
    in-band valid pixels contributes). Returns the pooled RMSE / mean-abs-error / bias, the total valid
    pixel count, and the per-pose-pair breakdown. The dense reconstruction RMSE `map_channel` calls the
    gated tier -- now a real, measured number from real rendered frames."""
    poses = sorted((p for p in os.listdir(corpus_dir) if p.startswith("pose_") and not p.endswith("noclasts")),
                   key=lambda p: int(p.split("_")[1]))
    errs, rows = [], []
    for p in poses:
        pose_dir = os.path.join(corpus_dir, p)
        for pair_key, l, r in pairs:
            try:
                m = measure_pair(pose_dir, scene_dir, pair_key=pair_key, left=l, right=r,
                                 num_disparities=num_disparities)
            except (FileNotFoundError, KeyError):
                continue
            if m["n_valid"] >= min_n and np.isfinite(m["depth_rmse_m"]):
                # re-derive the squared errors for an exact pool (rmse^2 * n)
                errs.append((m["n_valid"], m["depth_rmse_m"], m["depth_mean_abs_err_m"]))
                rows.append({"pose": p, "pair": pair_key, **m})
    n_tot = sum(n for n, _, _ in errs)
    pooled_rmse = (float(np.sqrt(sum(n * (rmse ** 2) for n, rmse, _ in errs) / n_tot)) if n_tot else float("nan"))
    pooled_mae = (float(sum(n * mae for n, _, mae in errs) / n_tot) if n_tot else float("nan"))
    return {"dense_depth_rmse_m": pooled_rmse, "dense_depth_mae_m": pooled_mae,
            "n_valid_total": int(n_tot), "n_pairs": len(rows), "per_pair": rows}
