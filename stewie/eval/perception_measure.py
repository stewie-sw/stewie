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
    # PM-15 (map-frame reconstruction): back-project the OBSERVED depth to world points and compare their
    # HEIGHT to the true terrain height at their footprint. Reuses the tested camera->world transform from
    # ray_cast_depth (Godot Y-up; optical +Z fwd / +Y down -> Godot-node (x,-y,-z); d_w = d_cam @ R^T) and
    # the tested bilinear truth heightfield. This is the dense reconstruction error in the MAP frame --
    # what map_channel's gated dense tier means -- vs the depth RMSE above (camera frame).
    geo = dt.load_scene_geometry(scene_dir)
    R = dt._quat_to_R(cam["pose_in_world"]["quaternion_xyzw"])
    posw = np.array(cam["pose_in_world"]["position_m"], float)
    uu, vv = np.meshgrid(T["cols"], T["rows"])                            # (h', w'), aligned with rr/cc
    fxp, fyp = float(intr["fx"]), float(intr.get("fy", intr["fx"]))
    d_opt = np.stack([(uu - intr["cx"]) / fxp, (vv - intr["cy"]) / fyp, np.ones_like(uu, float)], axis=-1)
    d_opt /= np.linalg.norm(d_opt, axis=-1, keepdims=True)
    d_cam = np.stack([d_opt[..., 0], -d_opt[..., 1], -d_opt[..., 2]], axis=-1)
    d_w = d_cam @ R.T
    with np.errstate(divide="ignore", invalid="ignore"):
        t_obs = zm / d_opt[..., 2]                                        # range along the ray to the obs surface
    Pw = posw[None, None, :] + d_w * t_obs[..., None]
    with np.errstate(invalid="ignore"):                                  # NaN footprints (invalid depth) -> masked below
        truth_h = dt._terrain_height(geo, Pw[..., 0], Pw[..., 2])
    hmask = vm & np.isfinite(truth_h) & np.isfinite(Pw[..., 1])
    herr = (Pw[..., 1] - truth_h)[hmask]
    hn = int(herr.size)
    # PM-14: the observed point cloud is the set of back-projected valid world points; report its size
    # + ground (x, z) extent in metres -- the dense stereo reconstruction's spatial footprint.
    pc = Pw[vm & np.isfinite(Pw).all(axis=-1)]
    extent = [float(np.ptp(pc[:, 0])), float(np.ptp(pc[:, 2]))] if pc.shape[0] else [0.0, 0.0]
    return {
        "n_valid": n,
        "valid_frac": float(np.mean(vm)) if vm.size else 0.0,
        "depth_rmse_m": float(np.sqrt(np.mean(err ** 2))) if n else float("nan"),
        "depth_mean_abs_err_m": float(np.mean(np.abs(err))) if n else float("nan"),
        "depth_bias_m": float(np.median(err)) if n else float("nan"),
        "height_rmse_m": float(np.sqrt(np.mean(herr ** 2))) if hn else float("nan"),
        "height_mean_abs_err_m": float(np.mean(np.abs(herr))) if hn else float("nan"),
        "n_height": hn,
        "n_points": int(pc.shape[0]),
        "pointcloud_extent_xz_m": extent,
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
    errs, herrs, rows = [], [], []
    for p in poses:
        pose_dir = os.path.join(corpus_dir, p)
        for pair_key, l, r in pairs:
            try:
                m = measure_pair(pose_dir, scene_dir, pair_key=pair_key, left=l, right=r,
                                 num_disparities=num_disparities)
            except (FileNotFoundError, KeyError):
                continue
            if m["n_valid"] >= min_n and np.isfinite(m["depth_rmse_m"]):
                # pool exactly: rmse^2 * n per pair, summed / total n
                errs.append((m["n_valid"], m["depth_rmse_m"], m["depth_mean_abs_err_m"]))
                if m["n_height"] and np.isfinite(m["height_rmse_m"]):
                    herrs.append((m["n_height"], m["height_rmse_m"]))
                rows.append({"pose": p, "pair": pair_key, **m})
    n_tot = sum(n for n, _, _ in errs)
    hn_tot = sum(n for n, _ in herrs)
    pooled_rmse = (float(np.sqrt(sum(n * (rmse ** 2) for n, rmse, _ in errs) / n_tot)) if n_tot else float("nan"))
    pooled_mae = (float(sum(n * mae for n, _, mae in errs) / n_tot) if n_tot else float("nan"))
    pooled_hrmse = (float(np.sqrt(sum(n * (r ** 2) for n, r in herrs) / hn_tot)) if hn_tot else float("nan"))
    return {"dense_depth_rmse_m": pooled_rmse, "dense_depth_mae_m": pooled_mae,
            "dense_height_rmse_m": pooled_hrmse,
            "n_valid_total": int(n_tot), "n_height_total": int(hn_tot),
            "n_pairs": len(rows), "per_pair": rows}


if __name__ == "__main__":              # diagnostic: python -m stewie.eval.perception_measure [corpus] [scene]
    import sys

    corpus = sys.argv[1] if len(sys.argv) > 1 else os.path.join("stewie", "eval", "validation", "g2cal")
    scene = sys.argv[2] if len(sys.argv) > 2 else os.path.join("samples", "crater_boulders")
    out = measure_corpus(corpus, scene)
    print(json.dumps({k: v for k, v in out.items() if k != "per_pair"}, indent=1))
    print(f"pairs measured: {out['n_pairs']}  (dense depth RMSE {out['dense_depth_rmse_m']*100:.1f} cm, "
          f"height RMSE {out['dense_height_rmse_m']*100:.1f} cm)")
