"""TDD spec for manifold IMU preintegration (Forster et al. 2017, IEEE T-RO 33(1):1-21).

These tests are the B3.1-core gate: they are written BEFORE dart/imu_preintegration.py exists, so
they FAIL on import first, then PASS once the factor is implemented. They validate the four properties
the dissertation spine names:

  (a) preintegration == brute-force step integration on a known synthetic IMU sequence (tight tol);
  (b) the first-order bias-correction Jacobians match finite differences of a full re-preintegration;
  (c) SO(3) Exp/Log and the right-Jacobian round-trip (the manifold retraction is exact-to-1st-order);
  (d) zero-motion / gravity-only input yields ZERO predicted Delta v, Delta p AFTER gravity removal.

No data is fabricated as a stand-in for a real pipeline: the synthetic IMU here is a UNIT TEST FIXTURE
for a mathematical identity (preintegration is the closed form of the same Euler recursion), not a
substitute for the real Katwijk run, which is scored separately on the real Stim300 stream.
"""
from __future__ import annotations

import numpy as np
import pytest

from dart.se3_pose_graph import exp_so3  # validated SO(3) exp (round-trips to 1e-16)

# module under test (does not exist yet -> import fails -> tests fail, as TDD requires)
from dart.imu_preintegration import (  # noqa: E402
    GRAVITY,
    preintegrate,
    right_jacobian_so3,
    right_jacobian_inv_so3,
)

RNG = np.random.default_rng(20260702)


def _brute_force(R0, v0, p0, gyro, accel, dts, g):
    """Independent forward-Euler NavState integrator (the reference preintegration must match).

    Convention: accel is body-frame SPECIFIC FORCE, so world acceleration = R @ f + g. Position uses
    the pre-step velocity/rotation, then velocity, then rotation advance -- the exact ordering the
    preintegrated Delta terms are the closed form of."""
    R, v, p = R0.copy(), v0.copy(), p0.copy()
    for k in range(len(dts)):
        dt = float(dts[k])
        a_world = R @ accel[k] + g
        p = p + v * dt + 0.5 * a_world * dt * dt
        v = v + a_world * dt
        R = R @ exp_so3(gyro[k] * dt)
    return R, v, p


def _random_sequence(m=200, dt=0.008, rot_rate=0.4, acc=0.3):
    """A non-trivial synthetic IMU sequence: real rotation + real specific force (gravity + motion)."""
    gyro = rot_rate * (RNG.standard_normal((m, 3)))
    # specific force ~ gravity reaction on z plus small horizontal motion (like a real IMU at rest+drift)
    accel = acc * RNG.standard_normal((m, 3))
    accel[:, 2] += 9.81
    dts = np.full(m, dt)
    return gyro, accel, dts


# --------------------------------------------------------------------------- (c) manifold round-trips
def test_so3_exp_log_roundtrip():
    from dart.imu_preintegration import log_so3_vec
    for phi in [np.zeros(3), np.array([1e-9, 0, 0]), np.array([0.1, -0.2, 0.3]),
                np.array([1.5, -1.0, 0.7]), np.array([np.pi - 1e-4, 0.0, 0.0])]:
        R = exp_so3(phi)
        back = log_so3_vec(R)
        # compare rotations (Log is unique only up to 2pi; compare via the rotation they produce).
        # tol matches the reused se3_pose_graph.log_so3 near-pi axis-recovery accuracy (~1e-8); the
        # preintegration factor itself never operates near theta=pi (per-sample rotation ~2e-4 rad).
        tol = 1e-7 if np.linalg.norm(phi) > np.pi - 1e-3 else 1e-12
        assert np.linalg.norm(exp_so3(back) - R) < tol, f"exp(log(exp(phi))) != exp(phi) for {phi}"


def test_right_jacobian_roundtrip():
    for phi in [np.zeros(3), np.array([1e-10, 0, 0]), np.array([0.2, 0.1, -0.4]),
                np.array([2.0, -0.5, 0.3])]:
        Jr = right_jacobian_so3(phi)
        Ji = right_jacobian_inv_so3(phi)
        assert np.allclose(Jr @ Ji, np.eye(3), atol=1e-9), f"Jr Jr^-1 != I for {phi}"


def test_right_jacobian_definition_via_fd():
    """Jr(phi) is the derivative of Exp at phi: Exp(phi+dphi) ~= Exp(phi) Exp(Jr(phi) dphi)."""
    from dart.imu_preintegration import log_so3_vec
    phi = np.array([0.3, -0.2, 0.15])
    Jr = right_jacobian_so3(phi)
    eps = 1e-6
    Jfd = np.zeros((3, 3))
    for k in range(3):
        d = np.zeros(3); d[k] = eps
        dR = exp_so3(phi).T @ exp_so3(phi + d)
        Jfd[:, k] = log_so3_vec(dR) / eps
    assert np.allclose(Jr, Jfd, atol=1e-5)


# --------------------------------------------------------------------------- (a) brute-force identity
def test_preintegration_matches_brute_force():
    gyro, accel, dts = _random_sequence()
    pim = preintegrate(gyro, accel, dts)                 # zero bias
    R0 = exp_so3(np.array([0.05, -0.1, 0.2]))
    v0 = np.array([0.3, -0.2, 0.05]); p0 = np.array([1.0, 2.0, 0.5])
    Rb, vb, pb = _brute_force(R0, v0, p0, gyro, accel, dts, GRAVITY)
    Rp, vp, pp = pim.predict(R0, v0, p0, GRAVITY)
    assert np.allclose(Rp, Rb, atol=1e-9), "predicted R != brute-force R"
    assert np.allclose(vp, vb, atol=1e-9), "predicted v != brute-force v"
    assert np.allclose(pp, pb, atol=1e-8), "predicted p != brute-force p"


def test_residual_zero_at_consistent_state():
    """A state that satisfies predict() exactly has a zero IMU residual."""
    gyro, accel, dts = _random_sequence()
    pim = preintegrate(gyro, accel, dts)
    Ri = exp_so3(np.array([0.0, 0.0, 0.3])); vi = np.array([0.1, 0.0, 0.0]); pi = np.zeros(3)
    bg = np.zeros(3); ba = np.zeros(3)
    Rj, vj, pj = pim.predict(Ri, vi, pi, GRAVITY)
    r = pim.residual(Ri, pi, vi, bg, ba, Rj, pj, vj, GRAVITY)
    assert np.linalg.norm(r) < 1e-8, f"residual not zero at consistent state: {r}"


# --------------------------------------------------------------------------- (b) bias Jacobians vs FD
def test_bias_jacobian_gyro_matches_fd():
    gyro, accel, dts = _random_sequence()
    pim = preintegrate(gyro, accel, dts)                 # linearized at zero bias
    from dart.imu_preintegration import log_so3_vec
    eps = 1e-6
    for k in range(3):
        db = np.zeros(3); db[k] = eps
        pk = preintegrate(gyro, accel, dts, bias_g=db)
        dR_fd = log_so3_vec(pim.dR.T @ pk.dR) / eps
        dV_fd = (pk.dV - pim.dV) / eps
        dP_fd = (pk.dP - pim.dP) / eps
        assert np.allclose(pim.dR_dbg[:, k], dR_fd, atol=1e-4), f"dR/dbg col {k}"
        assert np.allclose(pim.dV_dbg[:, k], dV_fd, atol=1e-4), f"dV/dbg col {k}"
        assert np.allclose(pim.dP_dbg[:, k], dP_fd, atol=1e-4), f"dP/dbg col {k}"


def test_bias_jacobian_accel_matches_fd():
    gyro, accel, dts = _random_sequence()
    pim = preintegrate(gyro, accel, dts)
    eps = 1e-6
    for k in range(3):
        db = np.zeros(3); db[k] = eps
        pk = preintegrate(gyro, accel, dts, bias_a=db)
        dV_fd = (pk.dV - pim.dV) / eps
        dP_fd = (pk.dP - pim.dP) / eps
        assert np.allclose(pim.dV_dba[:, k], dV_fd, atol=1e-4), f"dV/dba col {k}"
        assert np.allclose(pim.dP_dba[:, k], dP_fd, atol=1e-4), f"dP/dba col {k}"


def test_bias_correction_first_order_accuracy():
    """The corrected(dbg,dba) delta approximates a full re-preintegration to first order in db."""
    gyro, accel, dts = _random_sequence()
    pim = preintegrate(gyro, accel, dts)
    from dart.imu_preintegration import log_so3_vec
    dbg = np.array([2e-3, -1e-3, 5e-4]); dba = np.array([-3e-3, 1e-3, 2e-3])
    dR_c, dV_c, dP_c = pim.corrected(dbg, dba)
    full = preintegrate(gyro, accel, dts, bias_g=dbg, bias_a=dba)
    # first-order agreement: error is O(||db||^2), so << the raw correction magnitude
    assert np.linalg.norm(log_so3_vec(dR_c.T @ full.dR)) < 5e-4
    assert np.linalg.norm(dV_c - full.dV) < 5e-3
    assert np.linalg.norm(dP_c - full.dP) < 5e-3


# --------------------------------------------------------------------------- (d) gravity-only at rest
def test_gravity_only_zero_motion():
    """At rest (a_world = 0): the accelerometer reads +g upward specific force, the gyro reads 0.
    predict() must return v_j = v_i and p_j = p_i once gravity is removed -- no phantom motion."""
    m, dt = 300, 0.008
    gyro = np.zeros((m, 3))
    accel = np.zeros((m, 3)); accel[:, 2] = 9.81      # specific force = -R^T g with R = I
    dts = np.full(m, dt)
    pim = preintegrate(gyro, accel, dts)
    Ri = np.eye(3); vi = np.zeros(3); pi = np.zeros(3)
    Rj, vj, pj = pim.predict(Ri, vi, pi, GRAVITY)
    assert np.allclose(Rj, np.eye(3), atol=1e-12)
    assert np.linalg.norm(vj - vi) < 1e-6, f"phantom velocity at rest: {vj}"
    assert np.linalg.norm(pj - pi) < 1e-6, f"phantom position at rest: {pj}"


def test_gravity_only_with_tilt():
    """Same rest condition but with a real tilt: accel = R^T(-g), still zero net motion."""
    m, dt = 200, 0.008
    R = exp_so3(np.array([0.03, -0.02, 0.0]))          # small pitch/roll tilt
    f_rest = R.T @ (-GRAVITY)                            # specific force the IMU reads at rest
    gyro = np.zeros((m, 3))
    accel = np.tile(f_rest, (m, 1))
    dts = np.full(m, dt)
    pim = preintegrate(gyro, accel, dts)
    Rj, vj, pj = pim.predict(R, np.zeros(3), np.zeros(3), GRAVITY)
    assert np.linalg.norm(vj) < 1e-6, f"phantom velocity under tilt: {vj}"
    assert np.linalg.norm(pj) < 1e-6, f"phantom position under tilt: {pj}"


# --------------------------------------------------------------------------- covariance sanity
def test_covariance_spd_and_grows():
    gyro, accel, dts = _random_sequence(m=50)
    p1 = preintegrate(gyro, accel, dts, sigma_g_density=1e-3, sigma_a_density=1e-2)
    gyro2, accel2, dts2 = _random_sequence(m=150)
    p2 = preintegrate(gyro2, accel2, dts2, sigma_g_density=1e-3, sigma_a_density=1e-2)
    assert p1.cov.shape == (9, 9)
    ev1 = np.linalg.eigvalsh(0.5 * (p1.cov + p1.cov.T))
    assert ev1.min() >= -1e-18, "covariance not PSD"
    # more integration steps -> more accumulated uncertainty (trace grows)
    assert np.trace(p2.cov) > np.trace(p1.cov)


def test_preintegrate_rejects_shape_mismatch():
    with pytest.raises((ValueError, AssertionError)):
        preintegrate(np.zeros((5, 3)), np.zeros((4, 3)), np.full(5, 0.008))
