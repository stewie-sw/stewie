"""PART A step 1: run SuperPoint+LightGlue stereo VO on the REAL S3LI ``s3li_crater`` bag and freeze
the camera-frame trajectory to disk -- with ZERO ground-truth access (truth firewall I3).

Streams stereo pairs from :class:`dart.s3li_reader.S3liReader`, runs the committed
:func:`dart.superpoint_vo.estimate_vo_superpoint`, and writes the frozen estimate (TUM + npz) BEFORE
any GT loader is ever touched. Real data only: no synthetic pairs, no GT, no fabricated motion.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from dart.s3li_capstone import rotmat_to_quat_wxyz, write_tum
from dart.s3li_reader import S3liReader
from dart.stereo_vo import StereoVOConfig
from dart.superpoint_vo import estimate_vo_superpoint

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_freeze(stride: int, *, limit: int | None = None, out_dir: str = OUT_DIR) -> dict:
    """Stream real stereo pairs (no GT), run VO, freeze the camera-frame trajectory to TUM + npz."""
    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)
    t_read0 = time.time()
    pairs: list = []
    ts_ns: list[int] = []
    for ts, left, right in reader.stereo_pairs(stride=stride):
        pairs.append((left, right))
        ts_ns.append(int(ts))
        if limit is not None and len(pairs) >= limit:
            break
    read_s = time.time() - t_read0
    print(f"[freeze] read {len(pairs)} stereo pairs (stride={stride}) in {read_s:.1f}s", flush=True)

    t_vo0 = time.time()
    res = estimate_vo_superpoint(pairs, cfg, deterministic=True)
    vo_s = time.time() - t_vo0
    print(f"[freeze] VO on {len(pairs)} frames in {vo_s:.1f}s ({vo_s/len(pairs)*1000:.1f} ms/frame)",
          flush=True)

    ts_ns_arr = np.asarray(ts_ns, dtype=np.int64)
    poses = res.camera_poses
    xyz = poses[:, :3, 3].astype(float)
    quat = np.array([rotmat_to_quat_wxyz(p[:3, :3]) for p in poses], dtype=float)
    valid = np.asarray(res.trajectory_valid, dtype=bool)

    npz_path = os.path.join(out_dir, f"vo_cam_stride{stride}.npz")
    np.savez(npz_path, ts_ns=ts_ns_arr, xyz_cam=xyz, quat_wxyz_cam=quat, valid=valid,
             pnp_inliers=np.asarray(res.vo.pnp_inliers, dtype=int),
             stereo_point_counts=np.asarray(res.vo.stereo_point_counts, dtype=int),
             n_temporal_matches=np.asarray(res.n_temporal_matches, dtype=int),
             n_pnp_correspondences=np.asarray(res.n_pnp_correspondences, dtype=int), stride=stride)
    tum_path = os.path.join(out_dir, f"vo_cam_stride{stride}.tum")
    write_tum(tum_path, ts_ns_arr / 1e9, xyz, quat)

    meta = {
        "stride": stride, "n_frames": int(len(pairs)), "read_s": read_s, "vo_runtime_s": vo_s,
        "ms_per_frame": vo_s / len(pairs) * 1000.0, "n_valid": int(valid.sum()),
        "n_invalid_steps": int((~valid).sum()),
        "median_pnp_inliers": float(np.median(res.vo.pnp_inliers)) if res.vo.pnp_inliers else 0.0,
        "median_stereo_points": float(np.median(res.vo.stereo_point_counts)),
        "median_temporal_matches": float(np.median(res.n_temporal_matches)) if res.n_temporal_matches else 0.0,
        "ts_first_ns": int(ts_ns_arr[0]), "ts_last_ns": int(ts_ns_arr[-1]),
        "duration_s": float((ts_ns_arr[-1] - ts_ns_arr[0]) / 1e9),
        "npz_path": npz_path, "tum_path": tum_path,
    }
    with open(os.path.join(out_dir, f"vo_cam_stride{stride}_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[freeze] froze VO -> {tum_path}  valid {meta['n_valid']}/{meta['n_frames']}  "
          f"med_inliers {meta['median_pnp_inliers']:.0f}  duration {meta['duration_s']:.1f}s", flush=True)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    run_freeze(args.stride, limit=args.limit)
