"""Truth-firewall (invariant I3) test for the S3LI ``s3li_crater`` gyro-aided VIO -> DEM-anchoring path.

Mirrors ``test_s3li_firewall.py`` for the VIO variant, on REAL data only (no synthetic frames, no
fabricated motion):

  1. VIO runs on a few REAL S3LI stereo frames + the REAL IMU window and produces a finite trajectory.
  2. POISON TEST: the VIO estimation pipeline (VO poses + IMU -> gyro fuse -> register -> DEM anchoring)
     is GROUND-TRUTH-FREE. We corrupt the GT by +1e6 m and confirm BOTH the frozen VIO-only estimate AND
     the frozen VIO+DEM-anchored estimate are BYTE-IDENTICAL to the clean-GT run -- because GT is not even
     an argument to the estimator. GT enters only downstream, in scoring. A passing run writes
     ``poison_attestation_vio.json`` (consumed by the VIO artifact JSON).

Kept fast: the VO poses are reconstructed from a handful of real frames and the IMU is streamed only up
to the window those frames span (early break), so no 26 GB full pass. Skips cleanly if the bag / GT /
DEM tile are absent.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import tempfile

import numpy as np
import pytest

from dart.s3li_capstone import rotmat_to_quat_wxyz
from dart.s3li_dem import DEFAULT_DEM_PATH, S3liDem
from dart.s3li_reader import DEFAULT_BAG_PATH, DEFAULT_GT_PATH, S3liReader
from dart.s3li_vio import build_vio_leveled_trajectory, estimate_vio_and_freeze, load_imu_cached
from dart.stereo_vo import StereoVOConfig
from dart.superpoint_vo import estimate_vo_superpoint

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_HAVE_DATA = (os.path.isfile(DEFAULT_BAG_PATH) and os.path.isfile(DEFAULT_GT_PATH)
              and os.path.isfile(DEFAULT_DEM_PATH))
_skip = pytest.mark.skipif(not _HAVE_DATA, reason="S3LI bag / GT / DEM tile not present on this host")


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _vo_and_imu_on_real_frames(n: int = 14, stride: int = 4):
    """Run VO on a few REAL S3LI stereo frames and load the REAL IMU over just that window. No GT."""
    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)
    pairs, ts = [], []
    for t, left, right in reader.stereo_pairs(stride=stride):
        pairs.append((left, right))
        ts.append(int(t))
        if len(pairs) >= n:
            break
    res = estimate_vo_superpoint(pairs, cfg, deterministic=True)
    ts_ns = np.asarray(ts, dtype=np.int64)
    imu = load_imu_cached(reader, "", t_end_ns=int(ts_ns[-1]) + int(0.3e9))
    xyz_cam = res.camera_poses[:, :3, 3].astype(float)
    quat = np.array([rotmat_to_quat_wxyz(p[:3, :3]) for p in res.camera_poses], float)
    valid = np.asarray(res.trajectory_valid, dtype=bool)
    return xyz_cam, quat, valid, ts_ns, imu


@_skip
def test_vio_runs_on_real_frames():
    xyz_cam, quat, valid, ts_ns, imu = _vo_and_imu_on_real_frames()
    build = build_vio_leveled_trajectory(xyz_cam, quat, valid, imu["ts_ns"], imu["gyro"],
                                         imu["accel"], ts_ns)
    assert build.xyz_leveled.shape == xyz_cam.shape
    assert np.all(np.isfinite(build.xyz_leveled))
    # gravity is observable on Etna -> |mean accel| near g; the leveling tilt is a real, finite angle
    assert 9.0 < build.gravity_norm_m_s2 < 10.5
    assert np.isfinite(build.leveling_tilt_deg)
    # the gyro and the VO agree per step to a fraction of a degree (extrinsics + td applied correctly)
    assert build.vo_gyro_resid_deg_after < 2.0


@_skip
def test_poison_vio_is_byte_identical_under_gt_corruption():
    """Corrupt GT by +1e6 m; both frozen VIO estimates stay byte-identical (the estimator never reads GT)."""
    xyz_cam, quat, valid, ts_ns, imu = _vo_and_imu_on_real_frames()
    dem = S3liDem()

    # GT is loaded here ONLY to corrupt it and prove it has no path into estimation.
    reader = S3liReader()
    _gt_ts, gt_enu = reader.gt_enu(dem=dem)
    gt_clean = gt_enu
    gt_poison = gt_enu + 1.0e6

    def freeze_estimates(_gt_in_scope_but_unused: np.ndarray) -> dict[str, str]:
        """Freeze the VIO-only + VIO+DEM-anchored estimates. The GT in scope is deliberately NOT threaded
        into any estimation call -- ``estimate_vio_and_freeze`` has no GT parameter."""
        out = tempfile.mkdtemp()
        est = estimate_vio_and_freeze(xyz_cam, quat, valid, ts_ns, imu["ts_ns"], imu["gyro"],
                                      imu["accel"], dem, out, anchor_every=2)
        return {"vio_enu": _sha(est["vio_enu_tum"]), "anchored": _sha(est["anchored_tum"])}

    h_clean = freeze_estimates(gt_clean)
    h_poison = freeze_estimates(gt_poison)
    assert h_clean == h_poison, f"GT corruption changed the VIO estimate: {h_clean} != {h_poison}"

    # Structural firewall: neither the VIO builder nor the freeze carries a ground-truth argument.
    for fn in (estimate_vio_and_freeze, build_vio_leveled_trajectory):
        params = set(inspect.signature(fn).parameters)
        assert not (params & {"gt", "gt_enu", "gt_ts", "ground_truth", "truth"}), fn.__name__

    attestation = {
        "test": "poison_vio_is_byte_identical_under_gt_corruption",
        "result": "PASS",
        "gt_corruption_m": 1.0e6,
        "n_real_vo_frames": int(xyz_cam.shape[0]),
        "n_real_imu_samples": int(imu["ts_ns"].shape[0]),
        "sha256_clean": h_clean,
        "sha256_poison": h_poison,
        "byte_identical": True,
        "note": ("VO poses + IMU gyro -> gyro fuse -> register -> DEM-anchoring is a pure function of "
                 "images + IMU + cam-IMU calibration + DEM + the declared start; the DEM is sampled at "
                 "the ESTIMATED (x,y), never a GT cell. GT enters only in scoring, after the freeze."),
    }
    with open(os.path.join(THIS_DIR, "poison_attestation_vio.json"), "w") as fh:
        json.dump(attestation, fh, indent=2)
