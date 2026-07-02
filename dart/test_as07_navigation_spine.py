"""[REQ:AS-07] End-to-end composition test for the STEWIE (Stanford/NavLab-derived) navigation spine.

This binds the individual spine modules -- already unit-tested in isolation
(``dart.test_stereo_vo``, ``dart.test_se3_pose_graph``, ``stewie.bridge.test_autonomy_contract``) --
into ONE truth-denied pipeline that runs on REAL repo data and asserts the row's acceptance
non-vacuously. Two independent real-data legs cover the full spine:

  Leg A -- live stereo front-end on the REAL rendered lunar traverse (a6_traverse, crater_boulders):
    stereo feature detection + mutual matching (dart.features / dart.stereo_vo) -> stereo
    triangulation (dart.stereo_vo.triangulate_stereo, a real 3-D cloud in the left-camera frame) ->
    temporal PnP visual odometry across frames 000..003 (dart.stereo_vo.estimate_vo), with the M-03
    honest-failure contract (a failed step is INVALID/NaN, never fabricated zero motion).

  Leg B -- robust SE(3) back-end on the REAL frozen S3LI crater stereo-VO poses
    (benchmarks/s3li_crater/vo_cam_stride3.npz, 10599 real camera poses subsampled to a small slice):
    odometry factors from the VO relative poses (dart.se3_pose_graph.build_odometry_edges) + a real
    geometric loop-closure factor (dart.se3_pose_graph.build_loop_edges, built from the SAME VO
    geometry the appearance detector would verify) + a start prior -> on-manifold Gauss-Newton/LM
    pose-graph optimisation (dart.se3_pose_graph.SE3PoseGraph.solve) -> an optimised SE(3) trajectory
    with valid SO(3) rotations and finite translations.

Invariant I3 (ground-truth firewall): NONE of the estimator entry points composed here carry a
ground-truth / pose / slip argument. The only truth read anywhere in this test is the a6 EVAL-only
traverse length, used strictly in the metric-scale scoring assertion (never passed into an estimator).

Gated legs (named, NOT faked): the APPEARANCE-driven loop-closure DETECTOR
(``dart.loop_closure_visual.detect_loops``) needs the real S3LI loop-feature cache
(``loop_feats_stride3.npz``, regenerated from the real ESA rosbag) and the LightGlue weights; that
front-end is exercised by ``benchmarks/s3li_crater/test_s3li_loopclosure_firewall.py`` where the cache
is present. Here the loop factor is built directly from the frozen VO geometry (the verified
between-measurement), so the pose-graph BACK-END is tested without the gated detector.
"""
import inspect
import os

import numpy as np
import pytest

from dart import features, stereo_vo
from dart.loop_closure_visual import LoopClosure
from dart.se3_pose_graph import (
    PriorEdge,
    SE3PoseGraph,
    build_loop_edges,
    build_odometry_edges,
    exp_so3,
    log_so3,
)

HERE = os.path.dirname(__file__)
_A6 = os.path.join(HERE, "..", "stewie", "eval", "validation", "a6_traverse")
_CAM = os.path.join(_A6, "cam")
_TRUTH = os.path.join(_A6, "truth", "truth.json")
_FROZEN_VO = os.path.join(HERE, "..", "benchmarks", "s3li_crater", "vo_cam_stride3.npz")

_FRAMES = [os.path.join(_CAM, f"frame_{k:03d}") for k in range(4)]
_have_frames = all(
    os.path.exists(os.path.join(f, "front_left.png")) and os.path.exists(os.path.join(f, "front_right.png"))
    for f in _FRAMES
)
_have_frozen_vo = os.path.isfile(_FROZEN_VO)


def _load(frame_dir):
    from imageio.v3 import imread
    left = np.asarray(imread(os.path.join(frame_dir, "front_left.png")))
    right = np.asarray(imread(os.path.join(frame_dir, "front_right.png")))
    return left, right


def _load_stereo_pairs():
    return [_load(f) for f in _FRAMES]


def _quat_wxyz_to_rotmat(q: np.ndarray) -> np.ndarray:
    q = np.asarray(q, float)
    q = q / np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ], float)


# ---- structural firewall over the whole composed spine (no external assets) ---------------------
def test_navigation_spine_functions_are_all_truth_denied():
    """Invariant I3: EVERY estimator entry point composed by the spine -- the stereo front-end
    (triangulate + VO), the loop/odometry factor builders, and the SE(3) solver -- rejects a
    ground-truth / pose / slip argument. A structural gate: truth cannot flow into estimation because
    no estimator names a truth parameter."""
    forbidden = ("truth", "gt", "ground_truth", "pose_gt", "slip", "clast_truth")
    spine = (
        stereo_vo.triangulate_stereo,
        stereo_vo.estimate_vo,
        build_odometry_edges,
        build_loop_edges,
        SE3PoseGraph.solve,
    )
    for fn in spine:
        params = list(inspect.signature(fn).parameters)
        for bad in forbidden:
            assert not any(bad == p or p.startswith(bad + "_") for p in params), \
                f"{fn.__qualname__} leaks truth via a '{bad}' parameter"


# ---- Leg A: live stereo front-end -> triangulation -> temporal PnP VO on REAL rendered frames ----
@pytest.mark.skipif(not _have_frames, reason="rendered a6_traverse frames not present")
def test_leg_a_stereo_frontend_triangulation_and_vo_on_real_frames():
    """Leg A: detect + match stereo features on the REAL crater_boulders pair, triangulate a metric
    3-D cloud, then run temporal PnP VO across frames 000..003. Asserts a real front-end (many mutual
    matches, all-positive plausible depths, descriptors aligned 1:1 with points) feeds a real VO whose
    every step is valid + finite and whose recovered path length matches the EVAL-only truth traverse
    (metric scale recovered, not a pass-through). Truth is read ONLY in the final scoring line."""
    left0, right0 = _load(_FRAMES[0])

    # stereo feature detection + mutual matching (the front-end the spine's triangulation consumes)
    match = features.benchmark_method(left0, right0, "orb")
    assert match.n_inliers >= 50, "real stereo texture must yield many RANSAC-inlier matches"

    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=384, height_px=288, hfov_deg=73.99, baseline_m=0.07)

    # stereo triangulation -> a real metric cloud in the left-camera optical frame
    cloud = stereo_vo.triangulate_stereo(left0, right0, cfg)
    z = cloud.points_3d[:, 2]
    assert cloud.points_3d.shape[0] >= 50
    assert np.all(z > 0.0) and np.all(z < 100.0)
    assert 0.3 < float(np.median(z)) < 20.0
    assert cloud.descriptors.shape[0] == cloud.points_3d.shape[0]      # 1:1 for the PnP re-id step
    assert cloud.keypoints_px.shape == (cloud.points_3d.shape[0], 2)

    # temporal PnP visual odometry across the real traverse
    pairs = _load_stereo_pairs()
    vo = stereo_vo.estimate_vo(pairs, cfg)
    assert len(vo.relative_translations_m) == 3
    assert vo.trajectory_xyz_m.shape == (4, 3)
    assert all(vo.step_valid), "a clean real traverse keeps every PnP step valid (M-03)"
    assert np.all(np.isfinite(vo.relative_translations_m))
    assert all(n >= 30 for n in vo.pnp_inliers), "trustworthy PnP inlier support per step"

    step_mags = np.linalg.norm(vo.relative_translations_m, axis=1)
    assert float(np.std(step_mags) / np.mean(step_mags)) < 0.25    # constant straight drive

    # EVAL-only metric-scale check: recovered path length vs GROUND_TRUTH_EVAL traverse (~0.862 m).
    import json
    poses = json.load(open(_TRUTH))["poses"]
    xz = np.array([[p["x"], p["z"]] for p in poses], dtype=float)
    truth_len = float(np.sum(np.linalg.norm(np.diff(xz, axis=0), axis=1)))
    assert truth_len == pytest.approx(0.862, abs=0.01)
    assert abs(float(step_mags.sum()) - truth_len) / truth_len < 0.20


# ---- Leg B: robust SE(3) pose-graph back-end over the REAL frozen S3LI VO poses ------------------
@pytest.mark.skipif(not _have_frozen_vo, reason="frozen S3LI stereo-VO benchmark (vo_cam_stride3.npz) not present")
def test_leg_b_se3_posegraph_loop_closure_corrects_real_vo_drift():
    """Leg B: the standard loop-closure experiment on the REAL frozen S3LI crater stereo-VO poses.

    A per-step yaw bias (a REAL VO failure mode, not a truth field) is accumulated along the relative
    poses of the frozen chain, so the odometry-integrated endpoint drifts far from truth. Two SE(3)
    pose-graph solves are compared over the SAME drifted odometry: one with only the drifted odometry
    (no loop), one that ALSO closes the crater loop (last keyframe re-observes the first). The loop
    factor's between-measurement is the clean 0->b geometry -- exactly what the appearance detector +
    PnP would recover (the detector is the gated leg; see module docstring). Non-vacuous acceptance:

      * odometry-only cannot fix the drift (the drifted poses are self-consistent with drifted
        odometry -> its residuals are ~0 and the endpoint stays drifted);
      * the loop-closure solve pulls the drifted endpoint back by a large factor toward the true
        frozen geometry, on-manifold, with valid SO(3) rotations and finite translations throughout.

    This is pose-graph optimisation + loop-closure gating composed on real VO -- the back half of the
    spine -- verified numerically, not tautologically."""
    d = np.load(_FROZEN_VO)
    xyz = d["xyz_cam"].astype(float)
    quat = d["quat_wxyz_cam"].astype(float)
    valid = d["valid"].astype(bool)
    assert valid.all(), "the frozen benchmark advertises an all-valid VO chain"

    # subsample a small REAL slice (every 300th frozen pose) so the solve is fast but the geometry real
    idx = np.arange(0, xyz.shape[0], 300)
    n = idx.shape[0]
    assert n >= 20, "enough real keyframes for a meaningful graph"
    t0 = xyz[idx].copy()
    R0 = np.stack([_quat_wxyz_to_rotmat(quat[i]) for i in idx])

    # sanity on the real VO input: proper rotations, finite positions, a genuinely moving traverse
    for R in R0:
        assert np.allclose(R.T @ R, np.eye(3), atol=1e-6)
        assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-6)
    assert np.all(np.isfinite(t0))
    assert float(np.linalg.norm(t0[-1] - t0[0])) > 1.0            # real net displacement

    a, b = 0, n - 1

    # Accumulate a small constant per-step yaw bias into the frozen relative-pose chain -> a drifted
    # trajectory whose OWN odometry is self-consistent (the realistic VO gyro-bias failure). The loop
    # is what breaks that self-consistency and injects the truth-anchored correction.
    yaw_bias = exp_so3(np.array([0.0, 0.0, 0.01]))
    R_drift = [R0[0].copy()]
    t_drift = [t0[0].copy()]
    for k in range(1, n):
        dR = R0[k - 1].T @ R0[k]                                  # frozen VO relative rotation
        dt = R0[k - 1].T @ (t0[k] - t0[k - 1])                    # frozen VO relative translation
        R_drift.append(R_drift[-1] @ yaw_bias @ dR)
        t_drift.append(t_drift[-1] + R_drift[-1] @ dt)
    R_drift = np.stack(R_drift)
    t_drift = np.stack(t_drift)
    drift_err = float(np.linalg.norm(t_drift[b] - t0[b]))
    assert drift_err > 5.0, "the accumulated yaw bias produces a large endpoint drift"

    # odometry factors = the DRIFTED VO measurements (what the rover actually reported)
    odo = build_odometry_edges(R_drift, t_drift, np.radians(0.5), 0.10)
    assert len(odo) == n - 1

    # ONE real geometric loop closure: r_ab = R_b R_a^T, c_in_a = R_a^T (t_b - t_a) from the CLEAN
    # frozen geometry -- the between-measurement the appearance detector + PnP would verify.
    lc = LoopClosure(
        a_node=a, b_node=b, d_enu=(t0[b] - t0[a]), c_in_a=R0[a].T @ (t0[b] - t0[a]),
        n_inliers=120, n_matches=200, similarity=0.9,
        trans_m=float(np.linalg.norm(R0[a].T @ (t0[b] - t0[a]))),
        accepted=True, reject_reason="", r_ab=R0[b] @ R0[a].T,
    )
    loop = build_loop_edges([lc], np.radians(0.5), 0.1)
    assert len(loop) == 1, "the accepted closure yields exactly one loop edge"

    prior = PriorEdge(0, R0[0].copy(), t0[0].copy(), np.radians(1.0), 0.1)
    graph = SE3PoseGraph()

    res_no = graph.solve(R_drift, t_drift, prior=prior, odometry=odo, loop=[], iters=80)
    res_lc = graph.solve(R_drift, t_drift, prior=prior, odometry=odo, loop=loop, iters=80)

    # both solves return VALID optimised SE(3) trajectories
    for res in (res_no, res_lc):
        assert res.R.shape == (n, 3, 3) and res.t.shape == (n, 3)
        assert np.all(np.isfinite(res.R)) and np.all(np.isfinite(res.t))
        for R in res.R:                                          # every optimised pose stays on SO(3)
            assert np.allclose(R.T @ R, np.eye(3), atol=1e-5)
            assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-5)

    err_no = float(np.linalg.norm(res_no.t[b] - t0[b]))
    err_lc = float(np.linalg.norm(res_lc.t[b] - t0[b]))

    # odometry-only leaves the drift essentially untouched (self-consistent drifted chain)
    assert err_no == pytest.approx(drift_err, rel=0.05)
    # the loop closure corrects the endpoint by a large factor toward the true frozen geometry
    assert err_lc < 0.5 * err_no, "the loop closure must substantially reduce the endpoint drift"

    # the loop solve is a real optimisation (cost strictly decreased; loop residuals paid down)
    assert len(res_lc.cost_history) >= 2
    assert res_lc.final_cost < res_lc.cost_history[0]
    assert res_lc.cost_history[-1] == pytest.approx(res_lc.final_cost, rel=1e-9)

    # the correction is genuinely on the SO(3)/R^3 manifold (finite, non-trivial rotation correction)
    dR = np.einsum("nji,njk->nik", R_drift, res_lc.R)            # R_drift^T R_opt
    rot_corr_deg = np.degrees(np.linalg.norm(log_so3(dR), axis=1))
    assert np.all(np.isfinite(rot_corr_deg))
    assert float(np.max(rot_corr_deg)) > 0.1                    # the drifted yaw was genuinely corrected
