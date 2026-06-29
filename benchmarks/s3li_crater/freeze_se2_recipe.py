"""Freeze the S3LI ``s3li_crater`` FULL loop-closure ladder -- including the SE(2) (heading-optimizing)
fix -- to disk, with ZERO ground-truth access (truth firewall I3).

Four GT-free estimates, the experiment ladder that answers "what closes the VO 94 m -> paper 21 m gap":

  (a) VO                  -- registered SuperPoint+LightGlue stereo-VO ENU baseline (~93 m).
  (b) VO + LC (position)  -- the SAME visual loop closures in the POSITION-only pose graph
                             (dart.dem_height_graph); corrects translation, NOT heading -> ~51 m.
  (c) VO + LC (SE2)       -- the SAME closures (now carrying dyaw) in the SE(2) heading-optimizing pose
                             graph (dart.loop_pose_graph_se2); corrects the heading drift -> ~11 m.
  (d) VO + LC (SE2) + DEM -- (c) plus online DEM height-normal anchoring (the paper's full recipe).

GT is never touched here; loop closures come from visual matching + geometry, the DEM is sampled at the
ESTIMATED (x, y), and GT enters only downstream at scoring (run_s3li_crater_se2.py)."""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from dart.dem_height_graph import (
    DemHeightPoseGraph,
    build_between_factors,
    build_dem_anchor_factors,
)
from dart.loop_closure_visual import (
    build_loop_factors,
    build_loop_feature_cache,
    detect_loops,
    load_loop_feature_cache,
    registration_rotation,
)
from dart.loop_pose_graph_se2 import estimate_se2_loopclosure
from dart.s3li_capstone import register_cam_to_enu, write_tum, yaw_search
from dart.s3li_dem import S3liDem
from dart.s3li_reader import S3liReader
from dart.stereo_vo import StereoVOConfig

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_freeze_se2_recipe(
    stride: int, *, every: int = 6, out_dir: str = OUT_DIR,
    sigma_vo_m: float = 0.05, sigma_loop_m: float = 0.5, sigma_dem_m: float = 2.0,
    sigma_prior_m: float = 0.5, anchor_every: int = 20, se2_step: int = 20,
) -> dict:
    """Detect visual loop closures and freeze the four-rung ladder (VO / VO+LC-position / VO+LC-SE2 /
    VO+LC-SE2+DEM). No GT (invariant I3)."""
    npz_path = os.path.join(out_dir, f"vo_cam_stride{stride}.npz")
    if not os.path.isfile(npz_path):
        raise FileNotFoundError(f"frozen VO poses not found: {npz_path} (run freeze_vo.py --stride {stride})")
    d = np.load(npz_path)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    n = xyz_cam.shape[0]

    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)
    enu_vo = register_cam_to_enu(xyz_cam, yaw["yaw_rad"], z0)
    r_m = registration_rotation(yaw["yaw_rad"])
    print(f"[se2] yaw {yaw['yaw_deg']:.1f}deg (corr {yaw['peak_corr']:.3f}) z0 {z0:.2f}m", flush=True)

    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)
    cache_path = os.path.join(out_dir, f"loop_feats_stride{stride}.npz")
    if not os.path.isfile(cache_path):
        build_loop_feature_cache(stride, every, cache_path)
    keyframes = load_loop_feature_cache(cache_path)

    t0 = time.time()
    loops = detect_loops(keyframes, quat, yaw["yaw_rad"], cfg)
    acc = loops["accepted"]
    print(f"[se2] {len(acc)}/{loops['n_candidates']} loop closures in {time.time()-t0:.1f}s", flush=True)

    # (b) position-only LC (reference)
    between = build_between_factors(np.diff(enu_vo, axis=0), sigma_vo_m)
    loop_factors = build_loop_factors(acc, sigma_loop_m)
    graph = DemHeightPoseGraph(dem)
    res_pos = graph.solve(enu_vo, between + loop_factors, [], prior_idx=0,
                          prior_xyz=enu_vo[0].copy(), prior_sigma_m=sigma_prior_m)

    # (c) SE(2) heading-optimizing LC
    t1 = time.time()
    se2 = estimate_se2_loopclosure(enu_vo, quat, r_m, acc, step=se2_step)
    print(f"[se2] SE(2) solve: {se2.n_keyframes} kf, {se2.n_loops} loops, conv={se2.converged}, "
          f"{time.time()-t1:.0f}s, meanXYcorr={se2.mean_abs_horizontal_correction_m:.1f}m", flush=True)

    # (d) DEM height-normal anchoring ON TOP of the (now tight-horizontal) SE(2) estimate
    between_se2 = build_between_factors(np.diff(se2.xyz, axis=0), sigma_vo_m)
    anchor_idx = list(range(0, n, anchor_every))
    anchors = build_dem_anchor_factors(anchor_idx, sigma_dem_m)
    res_se2dem = graph.solve(se2.xyz, between_se2, anchors, prior_idx=0,
                             prior_xyz=se2.xyz[0].copy(), prior_sigma_m=sigma_prior_m)
    # (e) HEIGHT-ONLY DEM anchoring: same params, slope coupling DROPPED so the coarse 30 m normal can
    # no longer perturb the (already-tight) horizontal -- refines vertical without the horizontal penalty.
    anchors_h = build_dem_anchor_factors(anchor_idx, sigma_dem_m, height_only=True)
    res_se2demh = graph.solve(se2.xyz, between_se2, anchors_h, prior_idx=0,
                              prior_xyz=se2.xyz[0].copy(), prior_sigma_m=sigma_prior_m)

    ts_s = ts_ns / 1e9
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (ts_s.size, 1))
    paths = {
        "vo": os.path.join(out_dir, "se2_vo_enu.tum"),
        "lc_pos": os.path.join(out_dir, "se2_lc_position_enu.tum"),
        "lc_se2": os.path.join(out_dir, "se2_lc_se2_enu.tum"),
        "lc_se2_dem": os.path.join(out_dir, "se2_lc_se2_dem_enu.tum"),
        "lc_se2_dem_height_only": os.path.join(out_dir, "se2_lc_se2_dem_height_only_enu.tum"),
    }
    write_tum(paths["vo"], ts_s, enu_vo, ident)
    write_tum(paths["lc_pos"], ts_s, res_pos.xyz, ident)
    write_tum(paths["lc_se2"], ts_s, se2.xyz, ident)
    write_tum(paths["lc_se2_dem"], ts_s, res_se2dem.xyz, ident)
    write_tum(paths["lc_se2_dem_height_only"], ts_s, res_se2demh.xyz, ident)

    meta = {
        "stride": int(stride), "every": int(every), "n_frames": int(n),
        "yaw_deg": yaw["yaw_deg"], "z0_m": z0,
        "n_loop_closures": len(acc), "n_candidates": loops["n_candidates"],
        "loop_closures": [lc.to_json() for lc in acc],
        "se2": {"step": se2_step, "n_keyframes": se2.n_keyframes, "n_loops": se2.n_loops,
                "converged": se2.converged, "final_cost": se2.final_cost,
                "mean_abs_horizontal_correction_m": se2.mean_abs_horizontal_correction_m},
        "solver_params": {"sigma_vo_m": sigma_vo_m, "sigma_loop_m": sigma_loop_m,
                          "sigma_dem_m": sigma_dem_m, "sigma_prior_m": sigma_prior_m,
                          "anchor_every": anchor_every, "se2_step": se2_step},
        "tum": paths,
    }
    with open(os.path.join(out_dir, f"se2_recipe_stride{stride}_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[se2] froze 4-rung ladder -> {paths['lc_se2']}", flush=True)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--se2-step", type=int, default=20)
    args = ap.parse_args()
    run_freeze_se2_recipe(args.stride, se2_step=args.se2_step)
