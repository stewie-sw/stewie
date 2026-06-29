"""Unit tests for :mod:`dart.loop_closure_visual` (visual loop closure for the S3LI recipe).

Real data only (the no-synthetic-data rule): the pure-math identities are checked against REAL frozen VO
camera poses, and the place-recognition / geometry against the REAL frozen loop-feature cache. Tests
gate on those artifacts being present and skip cleanly otherwise.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from dart.factors import FactorType
from dart.loop_closure_visual import (
    LoopClosure,
    build_loop_factors,
    detect_loops,
    global_descriptor,
    load_loop_feature_cache,
    propose_candidates,
    quat_wxyz_to_rotmat,
    registration_rotation,
    verify_candidate,
)
from dart.s3li_capstone import register_cam_to_enu, rotmat_to_quat_wxyz, yaw_search

_BENCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "benchmarks", "s3li_crater")
_VO_NPZ = os.path.join(_BENCH, "vo_cam_stride3.npz")
_LOOP_NPZ = os.path.join(_BENCH, "loop_feats_stride3.npz")
_have_vo = pytest.mark.skipif(not os.path.isfile(_VO_NPZ),
                              reason="frozen VO npz absent (run benchmarks/s3li_crater/freeze_vo.py)")
_have_cache = pytest.mark.skipif(not os.path.isfile(_LOOP_NPZ),
                                 reason="loop-feature cache absent (run freeze_loopclosure.py)")
# S3liDem() reads the independent Copernicus GLO-30 tile at construction; gate the tests that build it
# on that real artifact too (same skip-cleanly-when-absent contract as the VO/cache artifacts above),
# else they FileNotFoundError where the tile isn't fetched (e.g. CI).
from dart.s3li_dem import DEFAULT_DEM_PATH as _DEM_TILE  # noqa: E402
_have_dem = pytest.mark.skipif(not os.path.isfile(_DEM_TILE),
                               reason="independent Copernicus DEM tile absent (fetch GLO-30 N37/E015)")


@_have_vo
def test_quat_wxyz_to_rotmat_inverts_rotmat_to_quat():
    """quat_wxyz_to_rotmat is the exact inverse of dart.s3li_capstone.rotmat_to_quat_wxyz, on REAL VO
    quaternions (round-trip to within float epsilon, up to the quaternion double cover)."""
    quat = np.load(_VO_NPZ)["quat_wxyz_cam"].astype(float)
    for k in (0, 18, 5000, quat.shape[0] - 1):
        R = quat_wxyz_to_rotmat(quat[k])
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)        # proper rotation
        q2 = rotmat_to_quat_wxyz(R)
        err = min(np.linalg.norm(q2 - quat[k]), np.linalg.norm(q2 + quat[k]))
        assert err < 1e-9


@_have_vo
@_have_dem
def test_registration_rotation_matches_register_cam_to_enu():
    """registration_rotation(yaw) reproduces dart.s3li_capstone.register_cam_to_enu on REAL VO camera
    points: ``p_enu = R_M @ p_cam + [0,0,z0]``. (This is the rotation the loop factor uses to map a
    relative camera motion into ENU, so it MUST match the trajectory registration exactly.)"""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz_cam = d["xyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)["yaw_rad"]
    r_m = registration_rotation(yaw)
    sample = xyz_cam[:: max(1, xyz_cam.shape[0] // 200)]
    via_matrix = (r_m @ sample.T).T + np.array([0.0, 0.0, z0])
    via_func = register_cam_to_enu(sample, yaw, z0)
    assert np.max(np.abs(via_matrix - via_func)) < 1e-9


@_have_vo
@_have_dem
def test_build_loop_factors_emits_loop_closure_between_factors():
    """build_loop_factors turns accepted closures into LOOP_CLOSURE between-factors (keyframe a, metadata
    ``to`` = b, length-3 value, isotropic sigma) and drops rejected ones. The displacement values are
    REAL VO ENU deltas (not fabricated)."""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz_cam = d["xyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)["yaw_rad"]
    enu = register_cam_to_enu(xyz_cam, yaw, z0)
    real_disp = enu[100] - enu[0]                                  # a real ENU displacement
    accepted = LoopClosure(0, 100, real_disp, np.zeros(3), 40, 80, 0.9, 1.0, True, "ok")
    rejected = LoopClosure(5, 200, np.zeros(3), np.zeros(3), 3, 4, 0.5, 0.0, False, "too_few_matches")
    facs = build_loop_factors([accepted, rejected], sigma_m=0.5)
    assert len(facs) == 1
    f = facs[0]
    assert f.factor_type == FactorType.LOOP_CLOSURE
    assert f.keyframe == 0 and int(f.metadata["to"]) == 100
    assert np.allclose(np.asarray(f.value, float), real_disp)
    assert f.covariance_array().shape == (3, 3)
    assert np.isclose(f.covariance_array()[0, 0], 0.25)


@_have_cache
def test_global_descriptor_unit_and_self_similar():
    """global_descriptor of REAL cached SuperPoint descriptors is unit-norm, and a keyframe's appearance
    cosine with itself is 1 while two distinct keyframes are < 1 (a usable place-recognition signal)."""
    kfs = load_loop_feature_cache(_LOOP_NPZ)
    g0 = global_descriptor(kfs[0].descriptors)
    assert abs(float(np.linalg.norm(g0)) - 1.0) < 1e-5
    assert abs(float(kfs[0].global_desc @ kfs[0].global_desc) - 1.0) < 1e-5
    cross = float(kfs[0].global_desc @ kfs[-1].global_desc)
    assert cross < 1.0


@_have_cache
def test_propose_candidates_respects_gap_appearance_and_order():
    """Proposed candidates over REAL keyframes all satisfy the temporal-gap and similarity-floor gates,
    use only appearance + node index (no position/GT), and are returned highest-similarity first."""
    kfs = load_loop_feature_cache(_LOOP_NPZ)
    gap, sim_min = 1500, 0.80
    cands = propose_candidates(kfs, min_index_gap=gap, sim_min=sim_min, max_candidates=500)
    assert cands, "no revisit candidates proposed on the real crater loop"
    sims = [c[2] for c in cands]
    assert sims == sorted(sims, reverse=True)
    for ja, jb, sim in cands:
        assert kfs[jb].node - kfs[ja].node >= gap
        assert sim >= sim_min


@_have_cache
def test_detect_loops_finds_start_end_revisit_and_chain_matches_vo():
    """End-to-end on REAL data: detect_loops finds the genuine start<->end crater revisit, and the loop
    factor's ENU displacement chain is validated on a consecutive keyframe pair against the trusted VO
    ENU delta (the geometric-correctness anchor for the whole module)."""
    from dart.s3li_dem import S3liDem
    from dart.s3li_reader import S3liReader
    from dart.stereo_vo import StereoVOConfig
    d = np.load(_VO_NPZ)
    xyz_cam = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)
    enu_vo = register_cam_to_enu(xyz_cam, yaw["yaw_rad"], z0)
    reader = S3liReader()
    intr = reader.intrinsics
    cfg = StereoVOConfig(fx_px=intr.fx, fy_px=intr.fy, cx_px=intr.cx, cy_px=intr.cy,
                         baseline_m=reader.baseline_m)
    kfs = load_loop_feature_cache(_LOOP_NPZ)

    loops = detect_loops(kfs, quat, yaw["yaw_rad"], cfg)
    acc = loops["accepted"]
    assert acc, "no loop closures accepted on the real crater loop"
    # the genuine revisit ties LATE keyframes back to EARLY ones (the rover returns to its start)
    assert max(lc.b_node for lc in acc) - min(lc.a_node for lc in acc) > 9000
    assert all(lc.a_node < lc.b_node for lc in acc)
    assert all(lc.n_inliers >= 15 for lc in acc)

    # chain validation: a CONSECUTIVE keyframe pair's verified displacement matches the VO ENU delta
    r_m = registration_rotation(yaw["yaw_rad"])
    ja, jb = 3, 4
    lc = verify_candidate(kfs[ja], kfs[jb], 1.0, cfg.matrix(), cfg,
                          quat_wxyz_to_rotmat(quat[kfs[ja].node]), r_m,
                          min_inliers=15, max_translation_m=5.0)
    assert lc.accepted, lc.reject_reason
    vo_delta = enu_vo[kfs[jb].node] - enu_vo[kfs[ja].node]
    assert np.linalg.norm(lc.d_enu - vo_delta) < 0.1
