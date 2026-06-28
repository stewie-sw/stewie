"""Freeze the S3LI ``s3li_crater`` gyro-aided VIO trajectory + its DEM-anchored variant to disk, with
ZERO ground-truth access (truth firewall I3).

Reuses the FROZEN vision-only VO camera poses (``vo_cam_stride{stride}.npz``, written by
``freeze_vo.py``) -- the per-step metric translation + rotation are reconstructed from them, so the VO
is NOT re-run -- and the real S3LI IMU stream (cached to ``imu_full.npz`` on first use). The VIO build +
DEM anchoring (:func:`dart.s3li_vio.estimate_vio_and_freeze`) are a pure function of (VO poses, IMU,
cam-IMU calibration, DEM-at-estimated-xy, declared start); GT is never touched here.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import numpy as np

from dart.s3li_dem import S3liDem
from dart.s3li_reader import S3liReader
from dart.s3li_vio import estimate_vio_and_freeze, load_imu_cached

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_freeze_vio(stride: int, *, out_dir: str = OUT_DIR, anchor_every: int = 10,
                   sigma_vo_m: float = 0.05, sigma_dem_m: float = 2.0,
                   sigma_prior_m: float = 0.5) -> dict:
    """Reconstruct the VO per-step motion from the frozen poses, fuse the IMU gyro, gravity-level, and
    freeze the VIO-ENU + VIO+DEM-anchored estimates (no GT)."""
    npz_path = os.path.join(out_dir, f"vo_cam_stride{stride}.npz")
    if not os.path.isfile(npz_path):
        raise FileNotFoundError(f"frozen VO poses not found: {npz_path} (run freeze_vo.py --stride {stride})")
    d = np.load(npz_path)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)
    quat_wxyz = d["quat_wxyz_cam"].astype(float)
    valid = d["valid"].astype(bool)

    reader = S3liReader()
    t_imu0 = time.time()
    imu = load_imu_cached(reader, os.path.join(out_dir, "imu_full.npz"))
    imu_s = time.time() - t_imu0
    print(f"[freeze-vio] IMU {imu['ts_ns'].shape[0]} samples in {imu_s:.1f}s", flush=True)

    dem = S3liDem()
    t_vio0 = time.time()
    est = estimate_vio_and_freeze(
        xyz_cam, quat_wxyz, valid, ts_ns, imu["ts_ns"], imu["gyro"], imu["accel"], dem, out_dir,
        anchor_every=anchor_every, sigma_vo_m=sigma_vo_m, sigma_dem_m=sigma_dem_m,
        sigma_prior_m=sigma_prior_m,
    )
    vio_s = time.time() - t_vio0
    vb = est["vio_build"]
    # save the gravity-leveled (right, down, forward) VIO trajectory so the scoring-side runner can run
    # the registration-robustness sweep (registration is firewall-clean; only the runner adds GT)
    lev_npz = os.path.join(out_dir, f"vio_cam_leveled_stride{stride}.npz")
    np.savez(lev_npz, ts_ns=ts_ns, xyz_leveled=est["xyz_leveled"])
    print(f"[freeze-vio] VIO build + anchoring in {vio_s:.1f}s  bias={vb['gyro_bias_rad_s']}  "
          f"resid {vb['vo_gyro_resid_deg_before']:.3f}->{vb['vo_gyro_resid_deg_after']:.3f} deg  "
          f"|g| {vb['gravity_norm_m_s2']:.3f}  tilt {vb['leveling_tilt_deg']:.2f} deg", flush=True)

    meta = {
        "stride": int(stride),
        "n_frames": int(xyz_cam.shape[0]),
        "n_imu_samples": int(imu["ts_ns"].shape[0]),
        "imu_load_s": imu_s,
        "vio_build_s": vio_s,
        "vio_enu_tum": est["vio_enu_tum"],
        "anchored_tum": est["anchored_tum"],
        "leveled_npz": lev_npz,
        "yaw_deg": est["yaw"]["yaw_deg"],
        "yaw_peak_corr": est["yaw"]["peak_corr"],
        "z0_m": est["z0_m"],
        "vio_build": vb,
        "anchor_diag": est["anchor_diag"],
    }
    with open(os.path.join(out_dir, f"vio_stride{stride}_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)
    print(f"[freeze-vio] froze VIO -> {est['vio_enu_tum']} + {est['anchored_tum']}", flush=True)
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--anchor-every", type=int, default=10)
    args = ap.parse_args()
    run_freeze_vio(args.stride, anchor_every=args.anchor_every)
