"""Freeze the S3LI ``s3li_crater`` stereo-VO + LOOP-CLOSURE + ONLINE-DEM-anchored trajectories to disk,
with ZERO ground-truth access (truth firewall I3) -- the paper-recipe leg of arXiv:2603.17229.

This reproduces the recipe that takes the paper from VO 94.01 m to 21.43 m on this exact sequence:
stereo VO + visual loop closure + online (tightly-coupled) DEM height-normal anchoring, all fused in ONE
joint pose graph. Three estimates are frozen, each GT-free:

  (a) VO only        -- the registered SuperPoint+LightGlue stereo-VO ENU trajectory (the ~93 m baseline).
  (b) VO + LC        -- (a) plus visual loop-closure between-factors in the pose graph (no DEM).
  (c) VO + LC + DEM  -- (b) plus DEM height-normal anchors inserted every ``anchor_every`` poses, jointly
                        optimised (the paper's full recipe).

The loop closures come from VISUAL place recognition + geometric verification on the frozen keyframe
features (dart.loop_closure_visual), NEVER from GT proximity. The DEM is sampled at the ESTIMATED (x, y).
GT is never touched here; it enters only downstream at scoring (run_s3li_crater_loopclosure.py)."""
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
)
from dart.s3li_capstone import register_cam_to_enu, write_tum, yaw_search
from dart.s3li_dem import S3liDem
from dart.s3li_reader import S3liReader
from dart.stereo_vo import StereoVOConfig

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_freeze_loopclosure(
    stride: int, *, every: int = 6, out_dir: str = OUT_DIR,
    sigma_vo_m: float = 0.05, sigma_loop_m: float = 0.5, sigma_dem_m: float = 2.0,
    sigma_prior_m: float = 0.5, anchor_every: int = 20,
    min_index_gap: int = 1500, sim_min: float = 0.80, min_inliers: int = 15,
    max_translation_m: float = 25.0, max_candidates: int = 4000,
) -> dict:
    """Re-derive the registered VO ENU trajectory, detect visual loop closures over the frozen keyframe
    features, and freeze the three estimates (VO / VO+LC / VO+LC+DEM). No GT (invariant I3)."""
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
    print(f"[lc] yaw {yaw['yaw_deg']:.1f}deg (VO-vs-DEM corr {yaw['peak_corr']:.3f}) z0 {z0:.2f}m", flush=True)

    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)

    cache_path = os.path.join(out_dir, f"loop_feats_stride{stride}.npz")
    if not os.path.isfile(cache_path):
        build_loop_feature_cache(stride, every, cache_path)
    keyframes = load_loop_feature_cache(cache_path)
    print(f"[lc] {len(keyframes)} loop keyframes (every {every})", flush=True)

    t0 = time.time()
    loops = detect_loops(keyframes, quat, yaw["yaw_rad"], cfg, min_index_gap=min_index_gap,
                         sim_min=sim_min, min_inliers=min_inliers, max_translation_m=max_translation_m,
                         max_candidates=max_candidates)
    acc = loops["accepted"]
    reject_hist: dict[str, int] = {}
    for lc in loops["attempts"]:
        if not lc.accepted:
            reject_hist[lc.reject_reason] = reject_hist.get(lc.reject_reason, 0) + 1
    print(f"[lc] detected {len(acc)}/{loops['n_candidates']} loop closures in {time.time()-t0:.1f}s; "
          f"rejects {reject_hist}", flush=True)

    between = build_between_factors(np.diff(enu_vo, axis=0), sigma_vo_m)
    loop_factors = build_loop_factors(acc, sigma_loop_m)
    anchor_idx = list(range(0, n, anchor_every))
    height_anchors = build_dem_anchor_factors(anchor_idx, sigma_dem_m)

    graph = DemHeightPoseGraph(dem)
    res_lc = graph.solve(enu_vo, between + loop_factors, [], prior_idx=0,
                         prior_xyz=enu_vo[0].copy(), prior_sigma_m=sigma_prior_m)
    res_lcdem = graph.solve(enu_vo, between + loop_factors, height_anchors, prior_idx=0,
                            prior_xyz=enu_vo[0].copy(), prior_sigma_m=sigma_prior_m)
    print(f"[lc] solve LC: conv={res_lc.converged} it={res_lc.iterations} "
          f"meanXY={res_lc.mean_abs_horizontal_correction_m:.1f}m meanH={res_lc.mean_abs_height_correction_m:.1f}m; "
          f"LC+DEM: conv={res_lcdem.converged} it={res_lcdem.iterations} "
          f"meanH={res_lcdem.mean_abs_height_correction_m:.1f}m", flush=True)

    ts_s = ts_ns / 1e9
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (ts_s.size, 1))
    vo_tum = os.path.join(out_dir, "lc_vo_enu.tum")
    lc_tum = os.path.join(out_dir, "lc_only_enu.tum")
    lcdem_tum = os.path.join(out_dir, "lc_dem_enu.tum")
    write_tum(vo_tum, ts_s, enu_vo, ident)
    write_tum(lc_tum, ts_s, res_lc.xyz, ident)
    write_tum(lcdem_tum, ts_s, res_lcdem.xyz, ident)

    a_nodes = sorted({lc.a_node for lc in acc})
    b_nodes = sorted({lc.b_node for lc in acc})
    meta = {
        "stride": int(stride), "every": int(every), "n_frames": int(n),
        "n_loop_keyframes": int(len(keyframes)),
        "yaw_deg": yaw["yaw_deg"], "yaw_peak_corr": yaw["peak_corr"], "z0_m": z0,
        "loop_params": {"min_index_gap": min_index_gap, "sim_min": sim_min, "min_inliers": min_inliers,
                        "max_translation_m": max_translation_m, "max_candidates": max_candidates,
                        "per_query_topk": 8},
        "solver_params": {"sigma_vo_m": sigma_vo_m, "sigma_loop_m": sigma_loop_m,
                          "sigma_dem_m": sigma_dem_m, "sigma_prior_m": sigma_prior_m,
                          "anchor_every": anchor_every, "n_dem_anchors": len(anchor_idx)},
        "n_candidates": loops["n_candidates"], "n_loop_closures": len(acc),
        "n_rejected": int(loops["n_candidates"] - len(acc)), "reject_reasons": reject_hist,
        "loop_a_node_range": [int(a_nodes[0]), int(a_nodes[-1])] if a_nodes else None,
        "loop_b_node_range": [int(b_nodes[0]), int(b_nodes[-1])] if b_nodes else None,
        "loop_inlier_min": int(min(lc.n_inliers for lc in acc)) if acc else None,
        "loop_inlier_max": int(max(lc.n_inliers for lc in acc)) if acc else None,
        "loop_closures": [lc.to_json() for lc in acc],
        "lc_solve_diag": {"converged": res_lc.converged, "iterations": res_lc.iterations,
                          "mean_abs_horizontal_correction_m": res_lc.mean_abs_horizontal_correction_m,
                          "mean_abs_height_correction_m": res_lc.mean_abs_height_correction_m},
        "lcdem_solve_diag": {"converged": res_lcdem.converged, "iterations": res_lcdem.iterations,
                             "mean_abs_horizontal_correction_m": res_lcdem.mean_abs_horizontal_correction_m,
                             "mean_abs_height_correction_m": res_lcdem.mean_abs_height_correction_m},
        "vo_tum": vo_tum, "lc_tum": lc_tum, "lcdem_tum": lcdem_tum,
        "cache_path": cache_path,
    }
    with open(os.path.join(out_dir, f"loopclosure_stride{stride}_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[lc] froze VO / VO+LC / VO+LC+DEM -> {lc_tum}", flush=True)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--every", type=int, default=6)
    ap.add_argument("--anchor-every", type=int, default=20)
    ap.add_argument("--sigma-loop-m", type=float, default=0.5)
    ap.add_argument("--min-inliers", type=int, default=15)
    args = ap.parse_args()
    run_freeze_loopclosure(args.stride, every=args.every, anchor_every=args.anchor_every,
                           sigma_loop_m=args.sigma_loop_m, min_inliers=args.min_inliers)
