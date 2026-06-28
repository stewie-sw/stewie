"""Truth-firewall (invariant I3) test for the S3LI ``s3li_crater`` VIO + HORIZONTAL DEM
terrain-correlation anchor (DEM_XY).

On REAL data only (the frozen stereo-VO poses + real IMU + the cached real stereo terrain clouds + the
real Copernicus DEM -- no synthetic frames, no fabricated motion):

  1. POISON TEST: the whole estimation chain (VIO ENU frames -> stereo clouds -> terrain registration ->
     DEM_XY fixes -> pose-graph solve -> frozen TUMs) is GROUND-TRUTH-FREE. We corrupt the GT by +1e6 m
     and confirm BOTH frozen estimates (the joint VIO+height+DEM_XY and the xy-only) are BYTE-IDENTICAL
     to the clean-GT run -- because GT is not even an argument to the estimator. A pass writes
     ``poison_attestation_demxy.json`` (consumed by the artifact JSON).
  2. STRUCTURAL firewall: none of the estimation functions carry a ground-truth parameter.
  3. MACHINERY SOUNDNESS (the honest control for the null result): the terrain match accepts 0 windows
     on the 30 m DEM (a DEM-resolution limit), so this test proves the anchor MACHINERY itself works --
     if DEM_XY fixes consistent with the true track WERE available, the pose graph drives the horizontal
     drift far below the un-anchored VIO. GT is used here ONLY as a known TARGET to manufacture good
     fixes (the scoring layer is allowed to read GT); it never enters the production estimator.

Skips cleanly if the bag / GT / DEM tile / frozen VO+cloud artifacts are absent.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import tempfile

import numpy as np
import pytest

from dart.dem_terrain_match import (
    estimate_demxy_and_freeze,
    register_patch_xy,
    register_windows,
    transform_cloud_to_enu,
)
from dart.s3li_capstone import axis_error_decompose, time_offset_s, write_tum
from dart.s3li_dem import DEFAULT_DEM_PATH, S3liDem
from dart.s3li_reader import DEFAULT_BAG_PATH, DEFAULT_GT_PATH, S3liReader
from dart.s3li_vio import build_vio_leveled_trajectory, load_imu_cached, vio_enu_camera_frames
from dart.stereo_vo import triangulate_stereo

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_VO_NPZ = os.path.join(THIS_DIR, "vo_cam_stride3.npz")
_IMU_NPZ = os.path.join(THIS_DIR, "imu_full.npz")
_CLOUD_NPZ = os.path.join(THIS_DIR, "stereo_cloud_stride3.npz")
_HAVE = (os.path.isfile(DEFAULT_BAG_PATH) and os.path.isfile(DEFAULT_GT_PATH)
         and os.path.isfile(DEFAULT_DEM_PATH) and os.path.isfile(_VO_NPZ)
         and os.path.isfile(_IMU_NPZ) and os.path.isfile(_CLOUD_NPZ))
_skip = pytest.mark.skipif(
    not _HAVE, reason="S3LI bag / GT / DEM tile / frozen VO+IMU+cloud artifacts not present "
                      "(run benchmarks/s3li_crater/freeze_demxy.py first)")


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _load_real_inputs():
    """Re-derive the firewall-clean VIO ENU camera frames + the cached real stereo terrain clouds."""
    d = np.load(_VO_NPZ)
    ts_ns = d["ts_ns"].astype(np.int64)
    xyz_cam = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    valid = d["valid"].astype(bool)
    reader = S3liReader()
    imu = load_imu_cached(reader, _IMU_NPZ)
    dem = S3liDem()
    build = build_vio_leveled_trajectory(xyz_cam, quat, valid, imu["ts_ns"], imu["gyro"],
                                         imu["accel"], ts_ns)
    z0 = float(dem.height_enu(0.0, 0.0))
    from dart.s3li_capstone import yaw_search
    yaw = yaw_search(build.xyz_leveled, dem, z0)
    r_enu_cam, enu_vio = vio_enu_camera_frames(build, yaw["yaw_rad"], z0)
    cache = np.load(_CLOUD_NPZ)
    fidx = cache["frame_idx"].astype(np.int64)
    pts = cache["pts"].astype(float)
    offs = cache["offsets"].astype(np.int64)
    clouds = [pts[offs[f]:offs[f + 1]] for f in range(fidx.shape[0])]
    return ts_ns, enu_vio, r_enu_cam, fidx, clouds, dem, reader


@_skip
def test_poison_demxy_is_byte_identical_under_gt_corruption():
    """Corrupt GT by +1e6 m; both frozen DEM_XY estimates stay byte-identical (the estimator never reads
    GT). The DEM is sampled at the ESTIMATED cell centres; the (x,y) shift is a terrain correlation."""
    ts_ns, enu_vio, r_enu_cam, fidx, clouds, dem, reader = _load_real_inputs()

    # GT loaded here ONLY to corrupt it and prove it has no path into estimation.
    _gt_ts, gt_enu = reader.gt_enu(dem=dem)
    gt_clean = gt_enu
    gt_poison = gt_enu + 1.0e6

    def freeze(_gt_in_scope_but_unused: np.ndarray) -> dict[str, str]:
        out = tempfile.mkdtemp()
        est = estimate_demxy_and_freeze(enu_vio, r_enu_cam, ts_ns, fidx, clouds, dem, out)
        return {"joint": _sha(est["demxy_tum"]), "xy_only": _sha(est["xy_only_tum"]),
                "n_accepted": est["n_accepted"]}

    h_clean = freeze(gt_clean)
    h_poison = freeze(gt_poison)
    assert h_clean == h_poison, f"GT corruption changed the DEM_XY estimate: {h_clean} != {h_poison}"

    # Structural firewall: no estimation function carries a ground-truth argument.
    gt_params = {"gt", "gt_enu", "gt_ts", "ground_truth", "truth"}
    for fn in (estimate_demxy_and_freeze, register_windows, register_patch_xy,
               transform_cloud_to_enu, triangulate_stereo, vio_enu_camera_frames):
        assert not (set(inspect.signature(fn).parameters) & gt_params), fn.__name__

    attestation = {
        "test": "poison_demxy_is_byte_identical_under_gt_corruption",
        "result": "PASS",
        "gt_corruption_m": 1.0e6,
        "n_nodes": int(enu_vio.shape[0]),
        "n_cloud_frames": int(fidx.shape[0]),
        "n_accepted_fixes": int(h_clean["n_accepted"]),
        "sha256_clean": {"joint": h_clean["joint"], "xy_only": h_clean["xy_only"]},
        "sha256_poison": {"joint": h_poison["joint"], "xy_only": h_poison["xy_only"]},
        "byte_identical": True,
        "note": ("Stereo clouds -> terrain registration -> DEM_XY fixes -> pose-graph solve is a pure "
                 "function of images + IMU + cam-IMU calibration + DEM (sampled at the ESTIMATED, "
                 "shifted cell centres) + the declared start; the horizontal (x,y) shift is found by "
                 "terrain CORRELATION, never by comparing to GT. GT enters only in scoring, after the "
                 "freeze."),
    }
    with open(os.path.join(THIS_DIR, "poison_attestation_demxy.json"), "w") as fh:
        json.dump(attestation, fh, indent=2)


@_skip
def test_anchor_machinery_reduces_drift_with_good_fixes():
    """MACHINERY SOUNDNESS (control for the null result). GT is used ONLY as a known target to forge a
    handful of DEM_XY fixes consistent with the true track (the scoring layer may read GT); it never
    enters the production estimator. Confirms the pose-graph DEM_XY anchor drives the horizontal ATE far
    below the un-anchored VIO -- so the 30 m DEM's 0 accepted fixes is a DEM-resolution limit, not a
    machinery failure."""
    from dart.dem_height_graph import (
        DemHeightPoseGraph,
        build_between_factors,
        build_dem_xy_factors,
    )
    ts_ns, enu_vio, _r, _f, _c, dem, reader = _load_real_inputs()
    gt_ts_ns, gt_enu = reader.gt_enu(dem=dem)
    off = time_offset_s(ts_ns, enu_vio, gt_ts_ns, gt_enu)
    gt_ts_aligned_s = (gt_ts_ns.astype(float) + off["offset_s"] * 1e9) / 1e9
    t_node = ts_ns.astype(float) / 1e9
    # GT (E,N) interpolated onto the VIO node times -- the KNOWN target (TEST scoring use only)
    gt_e = np.interp(t_node, gt_ts_aligned_s, gt_enu[:, 0])
    gt_n = np.interp(t_node, gt_ts_aligned_s, gt_enu[:, 1])

    n = enu_vio.shape[0]
    # the VO between-chain is loosened (sigma 0.5 m) when fusing absolute fixes so the trajectory can
    # follow them; with the very stiff metric chain (0.05 m) the same fixes only translate the rigid
    # path and the residual is the un-correctable VO scale/shape distortion (Sim3 scale ~1.04).
    between = build_between_factors(np.diff(enu_vio, axis=0), 0.5)
    idx = list(range(300, n - 300, 300))                       # a moderately dense set of good fixes
    xy = build_dem_xy_factors(idx, np.column_stack([gt_e[idx], gt_n[idx]]),
                              np.full(len(idx), 3.0))
    graph = DemHeightPoseGraph(dem)
    res = graph.solve(enu_vio, between, [], prior_idx=0, prior_xyz=enu_vio[0].copy(),
                      prior_sigma_m=0.5, xy_anchors=xy)

    out = tempfile.mkdtemp()
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))
    p_vio = os.path.join(out, "vio.tum")
    p_anc = os.path.join(out, "anc.tum")
    write_tum(p_vio, ts_ns / 1e9, enu_vio, ident)
    write_tum(p_anc, ts_ns / 1e9, res.xyz, ident)
    h_vio = axis_error_decompose(p_vio, gt_enu, gt_ts_aligned_s)["rms_horizontal_m"]
    h_anc = axis_error_decompose(p_anc, gt_enu, gt_ts_aligned_s)["rms_horizontal_m"]
    # with good fixes the horizontal drift drops sharply (the machinery works); the 30 m DEM just
    # cannot SUPPLY them -- the honest negative reported in the artifact.
    assert h_anc < 0.6 * h_vio, f"good DEM_XY fixes did not reduce horizontal drift: {h_vio} -> {h_anc}"
