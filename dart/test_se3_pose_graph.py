"""[REQ:AS-07] Tests for the full SE(3) pose-graph estimator (dart.se3_pose_graph), the navigation-spine optimizer core.

Two layers, NO synthetic measurements:

  * Lie-group property checks on the SO(3)/SE(3) operators (Exp/Log round-trip, agreement with
    scipy.Rotation, near-0 and near-pi stability) -- these are mathematical identities, not data.
  * A solver convergence test whose MEASUREMENTS are real frozen S3LI stereo-VO relative poses (a small
    subsample of ``benchmarks/s3li_crater/vo_cam_stride3.npz``); only the INITIAL ITERATE is perturbed,
    so the optimiser must recover the real chain. Skips cleanly if the frozen VO is absent.
"""
from __future__ import annotations

import os

import numpy as np
import pytest
from scipy.spatial.transform import Rotation as Rot

from dart.loop_closure_visual import quat_wxyz_to_rotmat
from dart.se3_pose_graph import (
    PriorEdge,
    RelEdge,
    SE3PoseGraph,
    build_odometry_edges,
    exp_se3_translation,
    exp_so3,
    hat,
    log_so3,
)

_VO_NPZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "benchmarks", "s3li_crater",
                       "vo_cam_stride3.npz")


def test_hat_is_skew():
    w = np.array([0.3, -0.7, 1.2])
    H = hat(w)
    assert np.allclose(H, -H.T)
    assert np.allclose(H @ w, 0.0)
    assert np.allclose(H @ np.array([1.0, 0.0, 0.0]), np.cross(w, [1.0, 0.0, 0.0]))


def test_exp_so3_matches_scipy_and_round_trips():
    rng = np.random.default_rng(1)
    for _ in range(50):
        w = rng.normal(size=3)
        w = w / np.linalg.norm(w) * rng.uniform(0.0, 3.0)            # angle in [0, pi)
        R = exp_so3(w)
        assert np.allclose(R, Rot.from_rotvec(w).as_matrix(), atol=1e-10)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-10)
        assert np.isclose(np.linalg.det(R), 1.0, atol=1e-10)
        assert np.allclose(log_so3(R[None])[0], w, atol=1e-9)


def test_log_so3_stable_near_zero_and_pi():
    axis = np.array([0.3, -0.5, 0.8]); axis = axis / np.linalg.norm(axis)
    for ang in (0.0, 1e-9, 1e-4, np.pi - 1e-6):
        R = Rot.from_rotvec(axis * ang).as_matrix()
        w = log_so3(R[None])[0]
        assert np.isclose(np.linalg.norm(w), ang, atol=1e-4)
        assert np.allclose(exp_so3(w), R, atol=1e-6)


def test_log_so3_is_batched():
    rng = np.random.default_rng(2)
    W = rng.normal(size=(13, 3)) * 0.4
    assert np.allclose(log_so3(exp_so3(W)), W, atol=1e-9)


def test_exp_se3_translation_small_angle():
    # V(phi)->I as phi->0, so exp_se3_translation(0, rho) == rho
    rho = np.array([1.0, -2.0, 0.5])
    assert np.allclose(exp_se3_translation(np.zeros(3), rho), rho, atol=1e-12)


def test_rel_residual_zero_at_measurement():
    rng = np.random.default_rng(3)
    g = SE3PoseGraph()
    Ra = exp_so3(rng.normal(size=3))[None]; Rb = exp_so3(rng.normal(size=3))[None]
    ta = rng.normal(size=3)[None]; tb = rng.normal(size=3)[None]
    Rz = np.einsum("eji,ejk->eik", Ra, Rb)                          # measurement = predicted -> r == 0
    tz = np.einsum("eji,ej->ei", Ra, tb - ta)
    assert np.allclose(g._rel_residual(Ra, Rb, ta, tb, Rz, tz), 0.0, atol=1e-12)


def _real_vo_subsample(m: int = 40):
    if not os.path.isfile(_VO_NPZ):
        pytest.skip("frozen S3LI VO not present (run benchmarks/s3li_crater/freeze_vo.py)")
    d = np.load(_VO_NPZ)
    quat = d["quat_wxyz_cam"].astype(float)[:m]
    xyz = d["xyz_cam"].astype(float)[:m]
    R = np.stack([quat_wxyz_to_rotmat(q) for q in quat])
    return R, xyz


def test_odometry_residual_zero_at_real_vo_init():
    """The VO relative poses are exactly the odometry measurements, so the real VO chain has zero
    odometry residual at the initial state."""
    R, t = _real_vo_subsample()
    g = SE3PoseGraph()
    odo = build_odometry_edges(R, t, np.radians(0.2), 0.05)
    a = np.array([e.a for e in odo]); b = np.array([e.b for e in odo])
    Rz = np.stack([e.R_meas for e in odo]); tz = np.stack([e.t_meas for e in odo])
    r = g._rel_residual(R[a], R[b], t[a], t[b], Rz, tz)
    assert np.allclose(r, 0.0, atol=1e-12)


def test_solver_recovers_real_chain_from_perturbed_init_with_loop():
    """Measurements = real S3LI VO relative poses (odometry) + the real relative pose T_0^{-1} T_{M-1}
    as a loop closure. The unperturbed real chain is the exact optimum. We DRIFT the initial orientation
    guess (a growing heading error) and confirm the on-manifold GN/LM recovers the real chain -- the
    heading-redistribution behaviour that beats the position-only floor, validated on real relative
    poses (only the starting iterate is perturbed, never the data)."""
    R, t = _real_vo_subsample(m=40)
    m = R.shape[0]
    g = SE3PoseGraph()
    odo = build_odometry_edges(R, t, np.radians(0.2), 0.05)
    # real loop closure: the true relative pose between the first and last node of the window
    R_meas = R[0].T @ R[m - 1]
    t_meas = R[0].T @ (t[m - 1] - t[0])
    loop = [RelEdge(0, m - 1, R_meas, t_meas, np.radians(1.0), 0.5, robust=True, kind="loop")]
    prior = PriorEdge(0, R[0].copy(), t[0].copy(), np.radians(2.0), 0.2)

    # drift the INITIAL orientation guess: a yaw error that grows along the chain (heading drift)
    R_init = R.copy(); t_init = t.copy()
    for i in range(1, m):
        dyaw = 0.02 * i                                             # up to ~45 deg by the chain end
        R_init[i] = R[i] @ exp_so3(np.array([0.0, dyaw, 0.0]))

    res = g.solve(R_init, t_init, prior=prior, odometry=odo, loop=loop, iters=60)
    assert res.converged
    assert res.final_cost < 1e-3                                    # back to the consistent chain
    # recovered orientations match the real chain (gauge fixed by the node-0 prior)
    dR = np.einsum("nji,njk->nik", R, res.R)
    rot_err_deg = np.degrees(np.linalg.norm(log_so3(dR), axis=1))
    assert float(np.max(rot_err_deg)) < 0.5
    assert float(np.max(np.linalg.norm(res.t - t, axis=1))) < 0.1


def test_solver_pure_odometry_is_already_optimal():
    """With only the (real) odometry + prior and the real VO as the initial state, the graph is already
    at the optimum: the solve converges immediately and barely moves the estimate."""
    R, t = _real_vo_subsample()
    g = SE3PoseGraph()
    odo = build_odometry_edges(R, t, np.radians(0.2), 0.05)
    prior = PriorEdge(0, R[0].copy(), t[0].copy(), np.radians(2.0), 0.2)
    res = g.solve(R, t, prior=prior, odometry=odo, loop=[], iters=20)
    assert res.converged
    assert res.final_cost < 1e-9
    assert float(np.max(np.linalg.norm(res.t - t, axis=1))) < 1e-6
