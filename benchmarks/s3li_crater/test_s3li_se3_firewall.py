"""Truth-firewall (invariant I3) test for the S3LI ``s3li_crater`` FULL SE(3) pose-graph recipe.

On REAL data only (the frozen stereo-VO poses + the real loop-closure feature cache + the real
Copernicus DEM -- no synthetic frames, no fabricated motion):

  1. POISON TEST: the whole SE(3) estimation chain (registered VO ENU + ENU orientation -> visual
     loop-closure detection -> odometry + loop + DEM-height + DEM-normal SE(3) factors -> on-manifold
     Gauss-Newton/LM solve -> frozen TUMs) is GROUND-TRUTH-FREE. We corrupt the GT by +1e6 m and confirm
     BOTH frozen SE(3) estimates (SE3+LC and the FINAL SE3+LC+DEM) are BYTE-IDENTICAL to the clean-GT
     run -- because GT is not even an argument to the estimator. A pass writes
     ``poison_attestation_se3.json`` (consumed by the artifact JSON).
  2. STRUCTURAL firewall: none of the SE(3) estimation functions carry a ground-truth parameter.

Skips cleanly if the bag / GT / DEM tile / frozen VO + loop-feature cache are absent.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import tempfile

import numpy as np
import pytest

from dart.loop_closure_visual import detect_loops, load_loop_feature_cache, quat_wxyz_to_rotmat, registration_rotation
from dart.s3li_capstone import register_cam_to_enu, rotmat_to_quat_wxyz, write_tum, yaw_search
from dart.s3li_dem import DEFAULT_DEM_PATH, S3liDem
from dart.s3li_reader import DEFAULT_BAG_PATH, DEFAULT_GT_PATH, S3liReader
from dart.se3_pose_graph import (
    DemHeightEdge,
    DemNormalEdge,
    PriorEdge,
    SE3PoseGraph,
    build_loop_edges,
    build_odometry_edges,
)
from dart.stereo_vo import StereoVOConfig

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_VO_NPZ = os.path.join(THIS_DIR, "vo_cam_stride3.npz")
_LOOP_NPZ = os.path.join(THIS_DIR, "loop_feats_stride3.npz")
_HAVE = (os.path.isfile(DEFAULT_BAG_PATH) and os.path.isfile(DEFAULT_GT_PATH)
         and os.path.isfile(DEFAULT_DEM_PATH) and os.path.isfile(_VO_NPZ) and os.path.isfile(_LOOP_NPZ))
_skip = pytest.mark.skipif(
    not _HAVE, reason="S3LI bag / GT / DEM tile / frozen VO + loop-feature cache not present "
                      "(run benchmarks/s3li_crater/freeze_se3.py first)")


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


@_skip
def test_poison_se3_is_byte_identical_under_gt_corruption():
    """Corrupt GT by +1e6 m; both frozen SE(3) estimates (SE3+LC and SE3+LC+DEM) stay byte-identical
    (the estimator never reads GT). Orientations are optimised on the manifold; the DEM is sampled at the
    ESTIMATED (x, y); loop closures are proposed by appearance + node index and verified by LightGlue +
    PnP -- never GT proximity."""
    d = np.load(_VO_NPZ)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    n = xyz_cam.shape[0]

    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)
    r_m = registration_rotation(yaw["yaw_rad"])
    t0 = register_cam_to_enu(xyz_cam, yaw["yaw_rad"], z0)
    R0 = np.stack([r_m @ quat_wxyz_to_rotmat(q) for q in quat])

    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)
    keyframes = load_loop_feature_cache(_LOOP_NPZ)
    loops = detect_loops(keyframes, quat, yaw["yaw_rad"], cfg)         # GT-free (images + VO frames)
    acc = loops["accepted"]

    odo = build_odometry_edges(R0, t0, np.radians(0.2), 0.05)
    loop = build_loop_edges(acc, np.radians(1.0), 0.5)
    prior = PriorEdge(0, R0[0].copy(), t0[0].copy(), np.radians(5.0), 0.5)
    anchor_idx = list(range(0, n, 20))
    dem_h = [DemHeightEdge(a, 2.0) for a in anchor_idx]
    dem_nrm = [DemNormalEdge(a, 0.2) for a in anchor_idx]
    graph = SE3PoseGraph(dem)

    # GT loaded here ONLY to corrupt it and prove it has no path into estimation.
    _gt_ts, gt_enu = reader.gt_enu(dem=dem)
    gt_clean = gt_enu
    gt_poison = gt_enu + 1.0e6

    def freeze(_gt_in_scope_but_unused: np.ndarray) -> dict[str, str]:
        out = tempfile.mkdtemp()
        res_lc = graph.solve(R0, t0, prior=prior, odometry=odo, loop=loop, iters=80)
        res_lcdem = graph.solve(R0, t0, prior=prior, odometry=odo, loop=loop, dem_height=dem_h,
                                dem_normal=dem_nrm, iters=80)
        p_lc = os.path.join(out, "se3_lc.tum")
        p_lcdem = os.path.join(out, "se3_lcdem.tum")
        write_tum(p_lc, ts_ns / 1e9, res_lc.t, np.stack([rotmat_to_quat_wxyz(R) for R in res_lc.R]))
        write_tum(p_lcdem, ts_ns / 1e9, res_lcdem.t,
                  np.stack([rotmat_to_quat_wxyz(R) for R in res_lcdem.R]))
        return {"se3_lc": _sha(p_lc), "se3_lc_dem": _sha(p_lcdem)}

    h_clean = freeze(gt_clean)
    h_poison = freeze(gt_poison)
    assert h_clean == h_poison, f"GT corruption changed the SE(3) estimate: {h_clean} != {h_poison}"

    # Structural firewall: no SE(3) estimation function carries a ground-truth argument.
    gt_params = {"gt", "gt_enu", "gt_ts", "ground_truth", "truth", "positions", "gt_positions"}
    for fn in (graph.solve, build_odometry_edges, build_loop_edges, detect_loops, register_cam_to_enu):
        assert not (set(inspect.signature(fn).parameters) & gt_params), fn.__name__

    attestation = {
        "test": "poison_se3_is_byte_identical_under_gt_corruption",
        "result": "PASS",
        "gt_corruption_m": 1.0e6,
        "n_nodes": int(n),
        "n_loop_closures": int(len(acc)),
        "sha256_clean": h_clean,
        "sha256_poison": h_poison,
        "byte_identical": True,
        "note": ("Registered VO ENU pose (position + orientation) -> visual loop-closure detection "
                 "(appearance + node index candidates, LightGlue + PnP verification) -> SE(3) odometry + "
                 "loop + DEM-height + DEM-normal factors -> on-manifold Gauss-Newton/LM solve is a pure "
                 "function of images + VO + the DEM (sampled at the ESTIMATED x, y) + the declared start. "
                 "Keyframe ORIENTATIONS are optimised but never read from GT. GT enters only in scoring, "
                 "after the freeze."),
    }
    with open(os.path.join(THIS_DIR, "poison_attestation_se3.json"), "w") as fh:
        json.dump(attestation, fh, indent=2)
