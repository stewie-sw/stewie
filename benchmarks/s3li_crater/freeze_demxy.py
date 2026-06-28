"""Freeze the S3LI ``s3li_crater`` VIO + HORIZONTAL DEM terrain-correlation anchored trajectory to disk,
with ZERO ground-truth access (truth firewall I3).

Builds on the frozen gyro-fused stereo-VIO (``dart.s3li_vio``): re-derives the per-frame ENU camera
poses, streams the REAL stereo to triangulate per-frame terrain point clouds (cached so re-runs skip the
26 GB bag pass), registers sliding windows of the rover's locally-observed terrain to the independent
Copernicus DEM for absolute (E, N) fixes, and re-solves the pose graph with the VIO between-factors +
DEM height-normal anchors + the DEM_XY horizontal fixes jointly (:func:`dart.dem_terrain_match.
estimate_demxy_and_freeze`). GT is never touched here -- the registration matches terrain to the DEM,
never to a true position; the DEM is sampled at the ESTIMATED cell centres.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from dart.dem_terrain_match import (
    estimate_demxy_and_freeze,
    global_registration,
    whole_patch_cells,
)
from dart.s3li_capstone import yaw_search
from dart.s3li_dem import S3liDem
from dart.s3li_reader import S3liReader
from dart.s3li_vio import build_vio_leveled_trajectory, load_imu_cached, vio_enu_camera_frames
from dart.stereo_vo import StereoVOConfig, triangulate_stereo

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def build_stereo_cloud_cache(
    stride: int, *, out_dir: str = OUT_DIR, cloud_sample_every: int = 6,
    depth_min_m: float = 0.5, depth_max_m: float = 8.0, n_features: int = 4000,
) -> dict:
    """Stream the REAL S3LI stereo once (same stride as the frozen VO, so the k-th pair == VO node k),
    triangulate every ``cloud_sample_every``-th pair to a metric camera-frame terrain cloud (depth-gated
    to the accurate near range), and cache (concatenated points + per-frame CSR offsets + node indices)
    to ``stereo_cloud_stride{stride}.npz``. No GT (invariant I3 -- :meth:`stereo_pairs` carries no pose).

    Returns the loaded cache dict. Re-uses an existing cache iff its header params match."""
    cache_path = os.path.join(out_dir, f"stereo_cloud_stride{stride}.npz")
    if os.path.isfile(cache_path):
        d = np.load(cache_path)
        if (int(d["cloud_sample_every"]) == cloud_sample_every
                and float(d["depth_max_m"]) == depth_max_m and float(d["depth_min_m"]) == depth_min_m):
            return {k: d[k] for k in d.files}

    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m, n_features=n_features)
    frame_idx: list[int] = []
    chunks: list[np.ndarray] = []
    offsets: list[int] = [0]
    t0 = time.time()
    k = 0
    for _ts, left, right in reader.stereo_pairs(stride=stride):
        if k % cloud_sample_every == 0:
            cloud = triangulate_stereo(left, right, cfg)
            pts = cloud.points_3d
            if pts.shape[0]:
                z = pts[:, 2]
                keep = (z >= depth_min_m) & (z <= depth_max_m)
                pts = pts[keep]
            frame_idx.append(k)
            chunks.append(pts.astype(np.float32))
            offsets.append(offsets[-1] + int(pts.shape[0]))
        k += 1
    dt = time.time() - t0
    pts_all = (np.concatenate(chunks, axis=0) if chunks else np.empty((0, 3), np.float32))
    cache = {
        "frame_idx": np.asarray(frame_idx, np.int64),
        "pts": pts_all,
        "offsets": np.asarray(offsets, np.int64),
        "cloud_sample_every": np.int64(cloud_sample_every),
        "depth_min_m": np.float64(depth_min_m),
        "depth_max_m": np.float64(depth_max_m),
        "n_streamed": np.int64(k),
        "stride": np.int64(stride),
    }
    np.savez(cache_path, **cache)
    print(f"[demxy] stereo cloud cache: {len(frame_idx)} frames, {pts_all.shape[0]} pts in {dt:.1f}s "
          f"-> {cache_path}", flush=True)
    return cache


def _clouds_from_cache(cache: dict) -> tuple[np.ndarray, list[np.ndarray]]:
    """Reconstruct (frame_idx (F,), [points_cam (Mf,3) per frame]) from the CSR cache."""
    frame_idx = np.asarray(cache["frame_idx"], np.int64)
    pts = np.asarray(cache["pts"], float)
    offs = np.asarray(cache["offsets"], np.int64)
    per_frame = [pts[offs[f]:offs[f + 1]] for f in range(frame_idx.shape[0])]
    return frame_idx, per_frame


def run_freeze_demxy(stride: int, *, out_dir: str = OUT_DIR, cloud_sample_every: int = 6,
                     **kwargs) -> dict:
    """Re-derive the VIO ENU camera frames, build/load the stereo cloud cache, register windows to the
    DEM, and freeze the VIO+DEM_XY-anchored trajectory. No GT (invariant I3)."""
    npz_path = os.path.join(out_dir, f"vo_cam_stride{stride}.npz")
    if not os.path.isfile(npz_path):
        raise FileNotFoundError(f"frozen VO poses not found: {npz_path} (run freeze_vo.py --stride {stride})")
    d = np.load(npz_path)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)
    quat_wxyz = d["quat_wxyz_cam"].astype(float)
    valid = d["valid"].astype(bool)

    reader = S3liReader()
    imu = load_imu_cached(reader, os.path.join(out_dir, "imu_full.npz"))
    dem = S3liDem()

    t_vio0 = time.time()
    build = build_vio_leveled_trajectory(
        xyz_cam, quat_wxyz, valid, imu["ts_ns"], imu["gyro"], imu["accel"], ts_ns)
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(build.xyz_leveled, dem, z0)
    r_enu_cam, enu_vio = vio_enu_camera_frames(build, yaw["yaw_rad"], z0)
    vio_s = time.time() - t_vio0
    print(f"[demxy] VIO ENU frames in {vio_s:.1f}s  yaw {yaw['yaw_deg']:.1f}deg "
          f"(corr {yaw['peak_corr']:.3f})  z0 {z0:.2f}m", flush=True)

    cache = build_stereo_cloud_cache(stride, out_dir=out_dir, cloud_sample_every=cloud_sample_every)
    frame_idx, clouds = _clouds_from_cache(cache)

    # firewall-clean observability probe: best 4-DOF GLOBAL terrain registration of the whole patch.
    # The honest test of whether the 30 m DEM relief is observable from the stereo-range terrain at all.
    gc_centres, gc_heights = whole_patch_cells(frame_idx, clouds, r_enu_cam, enu_vio)
    global_reg = global_registration(gc_centres, gc_heights, dem, enu_vio[0, :2])
    print(f"[demxy] global 4-DOF terrain reg: corr {global_reg['best_corr']:.3f} "
          f"(dyaw {global_reg['dyaw_deg']:.0f} scale {global_reg['scale']:.2f} boundary "
          f"{global_reg['on_boundary']}) vs heading-only corr {yaw['peak_corr']:.3f}", flush=True)

    t_reg0 = time.time()
    est = estimate_demxy_and_freeze(enu_vio, r_enu_cam, ts_ns, frame_idx, clouds, dem, out_dir, **kwargs)
    reg_s = time.time() - t_reg0
    res = est["result"]
    print(f"[demxy] {est['n_windows']} windows -> {est['n_accepted']} accepted fixes in {reg_s:.1f}s; "
          f"solve converged={res.converged} iters={res.iterations} "
          f"meanH={res.mean_abs_height_correction_m:.1f}m meanXY={res.mean_abs_horizontal_correction_m:.1f}m",
          flush=True)

    acc = est["accepted"]
    corrs = [f.corr for f in acc]
    meta = {
        "stride": int(stride),
        "n_frames": int(xyz_cam.shape[0]),
        "n_cloud_frames": int(frame_idx.shape[0]),
        "n_cloud_points": int(np.asarray(cache["pts"]).shape[0]),
        "cloud_sample_every": int(cloud_sample_every),
        "depth_min_m": float(cache["depth_min_m"]),
        "depth_max_m": float(cache["depth_max_m"]),
        "yaw_deg": yaw["yaw_deg"],
        "yaw_peak_corr": yaw["peak_corr"],
        "z0_m": z0,
        "vio_build": {
            "gyro_bias_rad_s": [float(x) for x in build.gyro_bias_rad_s],
            "vo_gyro_resid_deg_after": build.vo_gyro_resid_deg_after,
            "gravity_norm_m_s2": build.gravity_norm_m_s2,
            "leveling_tilt_deg": build.leveling_tilt_deg,
        },
        "global_terrain_registration": {**global_reg, "heading_only_corr": yaw["peak_corr"],
                                         "whole_patch_cells": int(gc_centres.shape[0])},
        "n_windows": est["n_windows"],
        "n_accepted": est["n_accepted"],
        "accepted_corr": {
            "min": float(np.min(corrs)) if corrs else None,
            "median": float(np.median(corrs)) if corrs else None,
            "max": float(np.max(corrs)) if corrs else None,
        },
        "anchor_diag": {
            "mean_abs_height_correction_m": res.mean_abs_height_correction_m,
            "mean_abs_horizontal_correction_m": res.mean_abs_horizontal_correction_m,
            "converged": res.converged, "iterations": res.iterations,
            "final_cost": res.final_cost, "n_xy_anchors": res.n_xy_anchors,
        },
        "windows": [f.to_json() for f in est["fixes"]],
        "vio_enu_tum": os.path.join(out_dir, "vio_enu.tum"),
        "demxy_tum": est["demxy_tum"],
        "xy_only_tum": est["xy_only_tum"],
        "anchor_diag_xy_only": {
            "mean_abs_horizontal_correction_m": est["result_xy_only"].mean_abs_horizontal_correction_m,
            "n_xy_anchors": est["result_xy_only"].n_xy_anchors,
        },
    }
    with open(os.path.join(out_dir, f"demxy_stride{stride}_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[demxy] froze VIO+DEM_XY -> {est['demxy_tum']}", flush=True)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--cloud-sample-every", type=int, default=6)
    args = ap.parse_args()
    run_freeze_demxy(args.stride, cloud_sample_every=args.cloud_sample_every)
