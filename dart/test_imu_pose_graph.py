"""Solver-wiring correctness for the IMU-augmented SE(3) pose graph (dart.imu_pose_graph).

Property test, not a data result: a trajectory that GENERATES the measurements is the unique zero-cost
minimum of the graph, so (1) its residual is zero and (2) LM recovers it from a perturbed initial guess.
The 'trajectory' is a unit-test fixture for that mathematical property, not a synthetic substitute for
the real Katwijk pipeline (which is scored separately on the real Stim300 stream vs RTK).
"""
from __future__ import annotations

import numpy as np

from dart.se3_pose_graph import exp_so3, log_so3
from dart.imu_preintegration import GRAVITY, preintegrate
from dart.imu_pose_graph import (
    BiasRWEdge, ImuEdge, ImuSe3PoseGraph, PriorImuEdge, WheelEdge,
)

RNG = np.random.default_rng(7)


def _generate_truth(n_kf=6, m_per=40, dt=0.01):
    """Integrate a known IMU stream -> true keyframe states + the raw windows between them."""
    R = np.eye(3); v = np.array([0.2, 0.0, 0.0]); p = np.zeros(3)
    g = GRAVITY
    Rs, ps, vs = [R.copy()], [p.copy()], [v.copy()]
    windows = []
    for _ in range(n_kf - 1):
        gyro = 0.2 * RNG.standard_normal((m_per, 3))
        acc = 0.15 * RNG.standard_normal((m_per, 3))
        # specific force = R^T(a_world - g); keep a_world small so it's a plausible slow motion
        # here we just drive with arbitrary specific force and integrate the TRUE response
        acc[:, 2] += 9.81
        dts = np.full(m_per, dt)
        for k in range(m_per):
            a_world = R @ acc[k] + g
            p = p + v * dt + 0.5 * a_world * dt * dt
            v = v + a_world * dt
            R = R @ exp_so3(gyro[k] * dt)
        windows.append((gyro, acc, dts))
        Rs.append(R.copy()); ps.append(p.copy()); vs.append(v.copy())
    return np.array(Rs), np.array(ps), np.array(vs), windows


def _build_graph(Rs, ps, vs, windows):
    imu_edges, wheel, bias_rw = [], [], []
    for i, (gyro, acc, dts) in enumerate(windows):
        pim = preintegrate(gyro, acc, dts, sigma_g_density=1e-3, sigma_a_density=1e-2)
        imu_edges.append(ImuEdge(i, i + 1, pim))
        t_meas = Rs[i].T @ (ps[i + 1] - ps[i])
        wheel.append(WheelEdge(i, i + 1, t_meas, sig_trans=0.02))
        bias_rw.append(BiasRWEdge(i, i + 1, sig_bg=1e-3, sig_ba=1e-2))
    prior = PriorImuEdge(0, Rs[0], ps[0], vs[0], np.zeros(3), np.zeros(3),
                         sig_rot=1e-3, sig_p=1e-3, sig_v=1e-3, sig_bg=1e-4, sig_ba=1e-3)
    return prior, imu_edges, bias_rw, wheel


def test_residual_zero_at_truth():
    Rs, ps, vs, windows = _generate_truth()
    prior, imu_edges, bias_rw, wheel = _build_graph(Rs, ps, vs, windows)
    n = len(Rs)
    g = ImuSe3PoseGraph()
    J, r = g._build(Rs, ps, vs, np.zeros((n, 3)), np.zeros((n, 3)), prior,
                    g._imu_stacks(imu_edges), bias_rw, wheel)
    assert np.linalg.norm(r) < 1e-6, f"graph residual not zero at the generating truth: {np.linalg.norm(r)}"


def test_lm_recovers_truth_from_perturbation():
    Rs, ps, vs, windows = _generate_truth()
    prior, imu_edges, bias_rw, wheel = _build_graph(Rs, ps, vs, windows)
    n = len(Rs)
    # perturb the initial guess (node 0 stays anchored by the tight prior)
    R0 = np.stack([R @ exp_so3(0.02 * RNG.standard_normal(3)) for R in Rs])
    p0 = ps + 0.05 * RNG.standard_normal(ps.shape)
    v0 = vs + 0.05 * RNG.standard_normal(vs.shape)
    bg0 = np.zeros((n, 3)); ba0 = np.zeros((n, 3))
    g = ImuSe3PoseGraph()
    res = g.solve(R0, p0, v0, bg0, ba0, prior=prior, imu_edges=imu_edges,
                  bias_rw=bias_rw, wheel=wheel, iters=60)
    assert res.final_cost < 1e-6, f"LM did not reach the zero-cost minimum: {res.final_cost}"
    pos_err = np.linalg.norm(res.p - ps, axis=1).max()
    assert pos_err < 1e-3, f"position not recovered: max err {pos_err} m"
    rot_err = max(np.linalg.norm(log_so3((Rs[i].T @ res.R[i])[None])[0]) for i in range(n))
    assert rot_err < 1e-3, f"rotation not recovered: max err {rot_err} rad"


def test_cost_monotone_decrease():
    Rs, ps, vs, windows = _generate_truth()
    prior, imu_edges, bias_rw, wheel = _build_graph(Rs, ps, vs, windows)
    n = len(Rs)
    R0 = np.stack([R @ exp_so3(0.03 * RNG.standard_normal(3)) for R in Rs])
    g = ImuSe3PoseGraph()
    res = g.solve(R0, ps + 0.1 * RNG.standard_normal(ps.shape), vs, np.zeros((n, 3)), np.zeros((n, 3)),
                  prior=prior, imu_edges=imu_edges, bias_rw=bias_rw, wheel=wheel, iters=60)
    h = res.cost_history
    assert all(h[i + 1] <= h[i] + 1e-9 for i in range(len(h) - 1)), "cost not monotone under accepted steps"
    assert h[-1] < h[0]
