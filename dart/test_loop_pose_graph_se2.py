"""Unit tests for :mod:`dart.loop_pose_graph_se2` (the SE(2) heading-optimizing loop-closure fix).

Real data only: the SE(2) helpers + deformation lift are checked against the REAL frozen VO trajectory,
and the end-to-end loop-closes-the-gap test reconstructs the REAL detected loop closures from the frozen
meta (no GPU / no GT). Gates on those artifacts and skips cleanly otherwise.
"""
from __future__ import annotations

import inspect
import json
import math
import os

import numpy as np
import pytest

from dart.loop_closure_visual import LoopClosure, registration_rotation
from dart.loop_pose_graph_se2 import (
    _relative_se2,
    _wrap,
    estimate_se2_loopclosure,
    keyframe_indices,
    lift_se2_to_full,
    loop_se2_measurement,
    node_headings_enu,
    solve_se2_keyframes,
)
from dart.s3li_capstone import register_cam_to_enu, yaw_search

_BENCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "benchmarks", "s3li_crater")
_VO_NPZ = os.path.join(_BENCH, "vo_cam_stride3.npz")
_META = os.path.join(_BENCH, "se2_recipe_stride3_meta.json")
_META_ALT = os.path.join(_BENCH, "loopclosure_stride3_meta.json")
_have_vo = pytest.mark.skipif(not os.path.isfile(_VO_NPZ), reason="frozen VO npz absent")
# the tests below build S3liDem(), which reads the independent Copernicus GLO-30 tile at construction;
# gate on that real artifact too (it is absent in CI), else they FileNotFoundError instead of skipping.
from dart.s3li_dem import DEFAULT_DEM_PATH as _DEM_TILE  # noqa: E402
_have_dem = pytest.mark.skipif(not os.path.isfile(_DEM_TILE),
                               reason="independent Copernicus DEM tile absent (S3liDem build)")


def _meta_path() -> str | None:
    for p in (_META, _META_ALT):
        if os.path.isfile(p):
            return p
    return None


def _load_closures() -> list[LoopClosure]:
    p = _meta_path()
    assert p is not None
    with open(p) as fh:
        m = json.load(fh)
    out: list[LoopClosure] = []
    for c in m["loop_closures"]:
        out.append(LoopClosure(
            int(c["a_node"]), int(c["b_node"]), np.asarray(c["d_enu_m"], float),
            np.asarray(c.get("c_in_a_m", [0, 0, 0]), float), int(c["n_inliers"]), int(c["n_matches"]),
            float(c["similarity"]), float(c["trans_m"]), bool(c["accepted"]), c["reject_reason"],
            r_ab=np.asarray(c.get("r_ab", np.eye(3)), float)))
    return out


def test_relative_se2_and_wrap_identities():
    """_relative_se2(p, p) == 0; a pure translation in i's body frame round-trips; _wrap is in (-pi, pi]."""
    p = np.array([3.0, -2.0, 0.7])
    assert np.allclose(_relative_se2(p, p), 0.0)
    pj = np.array([3.0 + math.cos(0.7), -2.0 + math.sin(0.7), 0.7])      # 1 m forward in body frame
    rel = _relative_se2(p, pj)
    assert np.allclose(rel, [1.0, 0.0, 0.0], atol=1e-9)
    assert abs(_wrap(2 * math.pi + 0.3) - 0.3) < 1e-9
    assert abs(_wrap(5.0)) <= math.pi


@_have_vo
@_have_dem
def test_node_headings_enu_consistent_with_registration():
    """At node 0 (R_wc = I) the ENU heading equals atan2 of R_M @ camera-forward; all headings finite."""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz, dem, z0)["yaw_rad"]
    r_m = registration_rotation(yaw)
    head = node_headings_enu(quat, r_m)
    assert head.shape[0] == xyz.shape[0] and np.all(np.isfinite(head))
    fwd0 = r_m @ np.array([0.0, 0.0, 1.0])                               # node 0: R_wc = identity
    assert abs(_wrap(head[0] - math.atan2(fwd0[1], fwd0[0]))) < 1e-9


@_have_vo
@_have_dem
def test_lift_identity_and_hits_corrected_keyframes():
    """The deformation lift is the identity when the keyframe poses are unchanged, and reproduces a
    shifted keyframe EXACTLY (continuity anchor for the full-resolution lift)."""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz, dem, z0)["yaw_rad"]
    enu = register_cam_to_enu(xyz, yaw, z0)
    head = node_headings_enu(quat, registration_rotation(yaw))
    kf = keyframe_indices(enu.shape[0], 50, [])
    corr_id = {k: (enu[k, 0], enu[k, 1], head[k]) for k in kf}
    lifted = lift_se2_to_full(enu, head, kf, corr_id)
    assert np.allclose(lifted[:, :2], enu[:, :2], atol=1e-6)             # unchanged keyframes -> identity
    # shift one keyframe by (10, -5) and confirm that exact node lands there
    k1 = kf[len(kf) // 2]
    corr_shift = dict(corr_id)
    corr_shift[k1] = (enu[k1, 0] + 10.0, enu[k1, 1] - 5.0, head[k1])
    lifted2 = lift_se2_to_full(enu, head, kf, corr_shift)
    assert np.allclose(lifted2[k1, :2], [enu[k1, 0] + 10.0, enu[k1, 1] - 5.0], atol=1e-6)


@_have_vo
@_have_dem
def test_lift_applies_rotational_correction():
    """Exercise the LOAD-BEARING rotational branch of the lift (phi != 0): a CONSTANT rigid SE(2)
    correction (rotate headings by delta, rotate+translate positions) at every keyframe must rotate AND
    translate EVERY node by that same rigid transform. (The identity test only covers phi == 0.)"""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz, dem, z0)["yaw_rad"]
    enu = register_cam_to_enu(xyz, yaw, z0)
    head = node_headings_enu(quat, registration_rotation(yaw))
    kf = keyframe_indices(enu.shape[0], 50, [])
    delta, trans = 0.2, np.array([5.0, -3.0])                          # a rigid SE(2): rotate + translate
    c, s = math.cos(delta), math.sin(delta)
    rot = np.array([[c, -s], [s, c]])
    corr = {k: (*(rot @ enu[k, :2] + trans), head[k] + delta) for k in kf}
    lifted = lift_se2_to_full(enu, head, kf, corr)
    expected = (rot @ enu[:, :2].T).T + trans                          # same rigid transform on all nodes
    assert np.allclose(lifted[:, :2], expected, atol=1e-6)


@_have_vo
@_have_dem
@pytest.mark.skipif(_meta_path() is None, reason="loop-closure meta absent (run freeze_se2_recipe.py)")
def test_se2_loop_closure_closes_the_gap():
    """End-to-end on REAL detected closures: the SE(2) solve drives the loop-closed pair (end vs start)
    far closer together than the drifted VO, and the loop measurement itself is a small revisit offset.
    Coarse keyframe step for speed; no GPU, no GT."""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz, dem, z0)["yaw_rad"]
    enu = register_cam_to_enu(xyz, yaw, z0)
    r_m = registration_rotation(yaw)
    head = node_headings_enu(quat, r_m)
    closures = [c for c in _load_closures() if c.accepted]
    assert closures, "no accepted loop closures in the meta"

    # the visual loop measurement is a SMALL revisit offset (rover returns near its past pose)
    a, b, meas = loop_se2_measurement(closures[0], quat, enu, head, r_m)
    assert np.hypot(meas[0], meas[1]) < 5.0

    res = estimate_se2_loopclosure(enu, quat, r_m, closures, step=150)
    lc = closures[0]
    vo_gap = float(np.linalg.norm(enu[lc.b_node, :2] - enu[lc.a_node, :2]))
    se2_gap = float(np.linalg.norm(res.xyz[lc.b_node, :2] - res.xyz[lc.a_node, :2]))
    assert vo_gap > 40.0                                                # VO drifted the loop wide open
    assert se2_gap < 0.5 * vo_gap                                       # SE(2) closed it


@_have_vo
@_have_dem
def test_shadow_yaw_factor_is_fused_and_pulls_heading():
    """The optional shadow-yaw channel (anti-solar absolute-heading factor) is wired into the SE(2)
    solve: it is counted (n_shadow) and it pulls a node's optimized yaw toward the measured heading.
    (On S3LI the sun is high so shadows are weak; this verifies the FUSION path for the lunar grazing-sun
    case.) Tiny REAL keyframe graph; no GPU."""
    from dart.s3li_dem import S3liDem
    d = np.load(_VO_NPZ)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    dem = S3liDem()
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz, dem, z0)["yaw_rad"]
    enu = register_cam_to_enu(xyz, yaw, z0)
    head = node_headings_enu(quat, registration_rotation(yaw))
    kf = keyframe_indices(2000, 50, [])                                  # a short prefix graph
    target = kf[len(kf) // 2]
    measured = head[target] + 0.15                                      # a heading the shadow "sees"
    base, st0 = solve_se2_keyframes(enu, head, kf, [])
    pulled, st1 = solve_se2_keyframes(enu, head, kf, [], shadow_yaw=[(target, measured, 0.05)])
    assert st0["n_shadow"] == 0 and st1["n_shadow"] == 1
    # the shadow factor moves the node's yaw toward the measured heading (vs the no-shadow solve)
    assert abs(_wrap(pulled[target][2] - measured)) < abs(_wrap(base[target][2] - measured))


def test_estimators_carry_no_ground_truth_argument():
    """Structural firewall (I3): no SE(2) estimation function takes a ground-truth pose."""
    gt = {"gt", "gt_enu", "gt_ts", "ground_truth", "truth", "gt_positions"}
    for fn in (estimate_se2_loopclosure, solve_se2_keyframes, lift_se2_to_full, node_headings_enu,
               loop_se2_measurement):
        assert not (set(inspect.signature(fn).parameters) & gt), fn.__name__
