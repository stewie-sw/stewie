"""Freeze the S3LI ``s3li_crater`` FULL SE(3) pose-graph estimates to disk, GT-free (truth firewall I3).

This is the central navigation benchmark experiment: the position-only loop-closure solve caps at
~51 m because it holds keyframe ORIENTATIONS at their VO front-end values and cannot redistribute the
accumulated HEADING drift that bows the single-loop trajectory. A FULL SE(3) pose graph optimises the
keyframe orientations jointly with positions, so a visual loop closure can rotate the inter-loop chain
and redistribute that heading drift -- the lever arXiv:2603.17229 uses to reach 21.4 m on this sequence.

Two estimates are frozen, each GT-free:

  (a) SE(3) + LC        -- VO odometry (relative SE(3)) + visual loop-closure relative-SE(3) edges + the
                           declared start prior, solved on the SE(3) manifold (dart.se3_pose_graph).
  (b) SE(3) + LC + DEM  -- (a) plus online DEM height + surface-normal factors every ``anchor_every``
                           poses, re-sampled at the ESTIMATED (x, y).

The loop closures are re-detected (deterministically) from the frozen keyframe features so each carries
its PnP relative ROTATION ``r_ab`` (the position-only freeze kept only the translation); the re-detected
ENU displacements are asserted to match the committed position-only freeze (reproduction check). GT is
never touched here; it enters only downstream at scoring (run_s3li_crater_se3.py)."""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (public); DEM: Copernicus GLO-30.
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from dart.loop_closure_visual import (
    build_loop_feature_cache,
    detect_loops,
    load_loop_feature_cache,
    quat_wxyz_to_rotmat,
    registration_rotation,
)
from dart.s3li_capstone import register_cam_to_enu, rotmat_to_quat_wxyz, write_tum, yaw_search
from dart.s3li_dem import S3liDem
from dart.s3li_reader import S3liReader
from dart.se3_pose_graph import (
    DemHeightEdge,
    DemNormalEdge,
    PriorEdge,
    SE3PoseGraph,
    build_loop_edges,
    build_odometry_edges,
)
from dart.stereo_vo import StereoVOConfig

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def _initial_se3(xyz_cam, quat, dem):
    """Initial SE(3) state: position from the firewall-clean VO->DEM-ENU registration, orientation from
    the VO per-keyframe rotation rotated into ENU by the same registration. No GT (I3)."""
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)
    r_m = registration_rotation(yaw["yaw_rad"])
    t0 = register_cam_to_enu(xyz_cam, yaw["yaw_rad"], z0)
    R0 = np.stack([r_m @ quat_wxyz_to_rotmat(q) for q in quat])
    return R0, t0, yaw, z0


def run_freeze_se3(
    stride: int, *, every: int = 6, out_dir: str = OUT_DIR,
    sigma_vo_rot_deg: float = 0.2, sigma_vo_trans_m: float = 0.05,
    sigma_loop_rot_deg: float = 1.0, sigma_loop_trans_m: float = 0.5,
    sigma_prior_rot_deg: float = 5.0, sigma_prior_trans_m: float = 0.5,
    sigma_dem_m: float = 2.0, sigma_dem_normal: float = 0.2, anchor_every: int = 20,
    min_index_gap: int = 1500, sim_min: float = 0.80, min_inliers: int = 15,
    max_translation_m: float = 25.0, max_candidates: int = 4000, iters: int = 40,
) -> dict:
    npz_path = os.path.join(out_dir, f"vo_cam_stride{stride}.npz")
    if not os.path.isfile(npz_path):
        raise FileNotFoundError(f"frozen VO poses not found: {npz_path} (run freeze_vo.py --stride {stride})")
    d = np.load(npz_path)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    n = xyz_cam.shape[0]

    dem = S3liDem()
    R0, t0, yaw, z0 = _initial_se3(xyz_cam, quat, dem)
    print(f"[se3] yaw {yaw['yaw_deg']:.1f}deg (VO-vs-DEM corr {yaw['peak_corr']:.3f}) z0 {z0:.2f}m", flush=True)

    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)

    cache_path = os.path.join(out_dir, f"loop_feats_stride{stride}.npz")
    if not os.path.isfile(cache_path):
        build_loop_feature_cache(stride, every, cache_path)
    keyframes = load_loop_feature_cache(cache_path)
    print(f"[se3] {len(keyframes)} loop keyframes (every {every})", flush=True)

    t_det = time.time()
    loops = detect_loops(keyframes, quat, yaw["yaw_rad"], cfg, min_index_gap=min_index_gap,
                         sim_min=sim_min, min_inliers=min_inliers, max_translation_m=max_translation_m,
                         max_candidates=max_candidates)
    acc = loops["accepted"]
    print(f"[se3] detected {len(acc)}/{loops['n_candidates']} loop closures in {time.time()-t_det:.1f}s", flush=True)

    # reproduction check: the re-detected ENU displacements must match the committed position-only freeze
    lc_meta_path = os.path.join(out_dir, f"loopclosure_stride{stride}_meta.json")
    repro_ok = None
    if os.path.isfile(lc_meta_path):
        with open(lc_meta_path) as fh:
            committed = {(c["a_node"], c["b_node"]): np.asarray(c["d_enu_m"], float)
                         for c in json.load(fh)["loop_closures"]}
        repro_ok = True
        for lc in acc:
            key = (int(lc.a_node), int(lc.b_node))
            if key in committed and not np.allclose(committed[key], np.asarray(lc.d_enu, float), atol=1e-6):
                repro_ok = False
        print(f"[se3] loop-closure reproduction vs committed position-only freeze: {repro_ok}", flush=True)

    odo = build_odometry_edges(R0, t0, np.radians(sigma_vo_rot_deg), sigma_vo_trans_m)
    loop = build_loop_edges(acc, np.radians(sigma_loop_rot_deg), sigma_loop_trans_m)
    prior = PriorEdge(0, R0[0].copy(), t0[0].copy(), np.radians(sigma_prior_rot_deg), sigma_prior_trans_m)
    anchor_idx = list(range(0, n, anchor_every))
    dem_h = [DemHeightEdge(a, sigma_dem_m) for a in anchor_idx]
    dem_nrm = [DemNormalEdge(a, sigma_dem_normal) for a in anchor_idx]

    graph = SE3PoseGraph(dem)
    t_s = time.time()
    res_lc = graph.solve(R0, t0, prior=prior, odometry=odo, loop=loop, iters=iters)
    print(f"[se3] LC solve: conv={res_lc.converged} it={res_lc.iterations} grad={res_lc.grad_norm:.2e} "
          f"cost={res_lc.final_cost:.3f} meanXY={res_lc.mean_abs_horizontal_correction_m:.1f}m "
          f"meanRot={res_lc.mean_abs_rotation_correction_deg:.2f}deg ({time.time()-t_s:.1f}s)", flush=True)
    t_s = time.time()
    res_lcdem = graph.solve(R0, t0, prior=prior, odometry=odo, loop=loop, dem_height=dem_h,
                            dem_normal=dem_nrm, iters=iters)
    print(f"[se3] LC+DEM solve: conv={res_lcdem.converged} it={res_lcdem.iterations} "
          f"grad={res_lcdem.grad_norm:.2e} cost={res_lcdem.final_cost:.3f} "
          f"meanH={res_lcdem.mean_abs_height_correction_m:.1f}m "
          f"meanRot={res_lcdem.mean_abs_rotation_correction_deg:.2f}deg ({time.time()-t_s:.1f}s)", flush=True)

    ts_s = ts_ns / 1e9
    lc_tum = os.path.join(out_dir, "se3_lc_enu.tum")
    lcdem_tum = os.path.join(out_dir, "se3_lc_dem_enu.tum")
    q_lc = np.stack([rotmat_to_quat_wxyz(R) for R in res_lc.R])
    q_lcdem = np.stack([rotmat_to_quat_wxyz(R) for R in res_lcdem.R])
    write_tum(lc_tum, ts_s, res_lc.t, q_lc)
    write_tum(lcdem_tum, ts_s, res_lcdem.t, q_lcdem)

    a_nodes = sorted({lc.a_node for lc in acc})
    b_nodes = sorted({lc.b_node for lc in acc})
    meta = {
        "stride": int(stride), "every": int(every), "n_frames": int(n),
        "n_loop_keyframes": int(len(keyframes)), "yaw_deg": yaw["yaw_deg"],
        "yaw_peak_corr": yaw["peak_corr"], "z0_m": z0,
        "loop_reproduction_matches_committed": repro_ok,
        "n_loop_closures": len(acc),
        "loop_a_node_range": [int(a_nodes[0]), int(a_nodes[-1])] if a_nodes else None,
        "loop_b_node_range": [int(b_nodes[0]), int(b_nodes[-1])] if b_nodes else None,
        "loop_closures": [lc.to_json() for lc in acc],
        "solver_params": {
            "sigma_vo_rot_deg": sigma_vo_rot_deg, "sigma_vo_trans_m": sigma_vo_trans_m,
            "sigma_loop_rot_deg": sigma_loop_rot_deg, "sigma_loop_trans_m": sigma_loop_trans_m,
            "sigma_prior_rot_deg": sigma_prior_rot_deg, "sigma_prior_trans_m": sigma_prior_trans_m,
            "sigma_dem_m": sigma_dem_m, "sigma_dem_normal": sigma_dem_normal,
            "anchor_every": anchor_every, "n_dem_anchors": len(anchor_idx),
            "huber_delta": 1.345, "max_iters": iters,
        },
        "lc_solve_diag": {
            "converged": res_lc.converged, "iterations": res_lc.iterations,
            "grad_norm": res_lc.grad_norm, "final_cost": res_lc.final_cost,
            "cost_history": res_lc.cost_history,
            "mean_abs_horizontal_correction_m": res_lc.mean_abs_horizontal_correction_m,
            "mean_abs_height_correction_m": res_lc.mean_abs_height_correction_m,
            "mean_abs_rotation_correction_deg": res_lc.mean_abs_rotation_correction_deg,
        },
        "lcdem_solve_diag": {
            "converged": res_lcdem.converged, "iterations": res_lcdem.iterations,
            "grad_norm": res_lcdem.grad_norm, "final_cost": res_lcdem.final_cost,
            "cost_history": res_lcdem.cost_history,
            "mean_abs_horizontal_correction_m": res_lcdem.mean_abs_horizontal_correction_m,
            "mean_abs_height_correction_m": res_lcdem.mean_abs_height_correction_m,
            "mean_abs_rotation_correction_deg": res_lcdem.mean_abs_rotation_correction_deg,
        },
        "se3_lc_tum": lc_tum, "se3_lc_dem_tum": lcdem_tum, "cache_path": cache_path,
    }
    with open(os.path.join(out_dir, f"se3_stride{stride}_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[se3] froze SE(3)+LC / SE(3)+LC+DEM -> {lc_tum}", flush=True)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--every", type=int, default=6)
    ap.add_argument("--anchor-every", type=int, default=20)
    ap.add_argument("--iters", type=int, default=40)
    args = ap.parse_args()
    run_freeze_se3(args.stride, every=args.every, anchor_every=args.anchor_every, iters=args.iters)
