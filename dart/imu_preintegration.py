"""Manifold IMU preintegration factor (Forster, Carlone, Dellaert, Scaramuzza, IEEE T-RO 33(1):1-21,
2017, "On-Manifold Preintegration for Real-Time Visual-Inertial Odometry"), the B3.1 dissertation-spine
core for the ARGUS SE(3) estimator.

WHAT THIS ADDS OVER THE POSE-ONLY GRAPH. dart.se3_pose_graph.SE3PoseGraph carries pose only (R,t per
keyframe) and folds the Stim300 gyro into the odometry between-factor as a yaw increment. This module
implements the full inertial factor: it preintegrates the raw high-rate gyro+accelerometer stream
between two keyframes into a single relative motion increment (Delta R in SO(3), Delta v, Delta p),
propagates its 9x9 measurement covariance, and carries the FIRST-ORDER bias-correction Jacobians so the
gyro-bias b_g and accel-bias b_a become estimated states instead of being assumed zero. The keyframe
state grows from 6 DOF (R, p) to 15 DOF (R, p, v, b_g, b_a). Landmark states are DEFERRED (a separate
structural change, not attempted here).

EQUATIONS IMPLEMENTED (paper eq. numbers in Forster 2017).

Preintegrated measurements between keyframes i and j, over raw samples k = 0..M-1 with per-sample dt,
bias-corrected reading  a_k = a~_k - b_a,  w_k = w~_k - b_g   (eq. 33-37):

  Delta R_ij = prod_k Exp(w_k dt)                                                (rotation increment)
  Delta v_ij = sum_k  Delta R_ik (a_k) dt
  Delta p_ij = sum_k  [ Delta v_ik dt + 1/2 Delta R_ik (a_k) dt^2 ]

with Delta R_ik / Delta v_ik the partial products up to k. These are the exact closed form of the
forward-Euler NavState recursion (position uses the pre-step v and R, then v, then R advance), so
predict() reproduces a brute-force integrator to machine precision (test (a)).

State prediction from keyframe i (eq. 32), g = gravity vector (world frame, points down), DT = t_j-t_i:

  R_j = R_i Delta R_ij
  v_j = v_i + g DT + R_i Delta v_ij
  p_j = p_i + v_i DT + 1/2 g DT^2 + R_i Delta p_ij

Residual (eq. 45), with the first-order bias correction (eq. 44) db_g = b_g - b_g_lin, db_a similarly:

  Delta R_corr = Delta R_ij Exp( J^{R}_{bg} db_g )
  Delta v_corr = Delta v_ij + J^{v}_{bg} db_g + J^{v}_{ba} db_a
  Delta p_corr = Delta p_ij + J^{p}_{bg} db_g + J^{p}_{ba} db_a
  r_R = Log( Delta R_corr^T R_i^T R_j )
  r_v = R_i^T (v_j - v_i - g DT)       - Delta v_corr
  r_p = R_i^T (p_j - p_i - v_i DT - 1/2 g DT^2) - Delta p_corr

Bias-Jacobian recursion (eq. 39-45; Jr = SO(3) right Jacobian, [.]x = hat), applied per sample using
the PRE-step Delta R and Jacobians (matching the integration ordering p, then v, then R):

  J^{p}_{bg} += J^{v}_{bg} dt - 1/2 Delta R [a_k]x J^{R}_{bg} dt^2
  J^{p}_{ba} += J^{v}_{ba} dt - 1/2 Delta R dt^2
  J^{v}_{bg} += - Delta R [a_k]x J^{R}_{bg} dt
  J^{v}_{ba} += - Delta R dt
  J^{R}_{bg}  = Exp(w_k dt)^T J^{R}_{bg} - Jr(w_k dt) dt

Covariance propagation (eq. 45, discrete): Sigma_{k+1} = A Sigma A^T + B Sigma_eta B^T with the standard
9x9 A and 9x6 B built below; Sigma_eta = diag( (sigma_g^2/dt) I3, (sigma_a^2/dt) I3 ) converts continuous
white-noise DENSITIES to the per-step discrete covariance (so accumulated angle variance ~ T sigma_g^2,
the correct random-walk scaling).

TRUTH FIREWALL (I3/I7): every quantity here is a function of the raw IMU stream + the state estimate
only; no ground truth enters. This module is used by the estimator; RTK is read solely at scoring.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Reference: Forster et al. IEEE T-RO 2017.
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dart.se3_pose_graph import exp_so3, hat, log_so3

GRAVITY = np.array([0.0, 0.0, -9.81])   # world-frame gravity vector (z up), magnitude 9.81 m/s^2


# ------------------------------------------------------------------- robust single-rotation Exp/Log
def exp_so3_vec(phi: np.ndarray) -> np.ndarray:
    """Exp of a single rotation vector (3,) -> (3,3)."""
    return exp_so3(np.asarray(phi, float))


def log_so3_vec(R: np.ndarray) -> np.ndarray:
    """Log of a single rotation matrix (3,3) -> (3,); batches through the validated (1,3,3) path."""
    return log_so3(np.asarray(R, float)[None])[0]


def right_jacobian_so3(phi: np.ndarray) -> np.ndarray:
    """Right Jacobian of SO(3): Jr(phi) = I - (1-cos t)/t^2 [phi]x + (t - sin t)/t^3 [phi]x^2.

    Taylor fallback for t -> 0 (numerically stable). Exp(phi + dphi) ~= Exp(phi) Exp(Jr(phi) dphi)."""
    phi = np.asarray(phi, float)
    t = float(np.linalg.norm(phi))
    K = hat(phi)
    if t < 1e-8:
        return np.eye(3) - 0.5 * K + (1.0 / 6.0) * (K @ K)
    c1 = (1.0 - np.cos(t)) / t ** 2
    c2 = (t - np.sin(t)) / t ** 3
    return np.eye(3) - c1 * K + c2 * (K @ K)


def right_jacobian_inv_so3(phi: np.ndarray) -> np.ndarray:
    """Inverse right Jacobian: Jr^-1(phi) = I + 1/2 [phi]x + (1/t^2 - (1+cos t)/(2 t sin t)) [phi]x^2."""
    phi = np.asarray(phi, float)
    t = float(np.linalg.norm(phi))
    K = hat(phi)
    if t < 1e-8:
        return np.eye(3) + 0.5 * K + (1.0 / 12.0) * (K @ K)
    c2 = 1.0 / t ** 2 - (1.0 + np.cos(t)) / (2.0 * t * np.sin(t))
    return np.eye(3) + 0.5 * K + c2 * (K @ K)


@dataclass
class PreintegratedImu:
    """A preintegrated inertial measurement between two keyframes, linearized at (bias_g, bias_a).

    dR/dV/dP are the increments; dt is the summed interval. cov is the 9x9 measurement covariance in
    the [dphi, dv, dp] ordering. The dX_dbY are the first-order bias-correction Jacobians."""

    dR: np.ndarray          # (3,3)
    dV: np.ndarray          # (3,)
    dP: np.ndarray          # (3,)
    dt: float
    cov: np.ndarray         # (9,9)  order [dphi(3), dv(3), dp(3)]
    dR_dbg: np.ndarray      # (3,3)
    dV_dbg: np.ndarray      # (3,3)
    dV_dba: np.ndarray      # (3,3)
    dP_dbg: np.ndarray      # (3,3)
    dP_dba: np.ndarray      # (3,3)
    bias_g: np.ndarray      # (3,) linearization bias
    bias_a: np.ndarray      # (3,)
    n_samples: int = 0

    # -- first-order bias correction (eq. 44) --
    def corrected(self, dbg: np.ndarray, dba: np.ndarray):
        """(dR,dV,dP) re-evaluated at bias (bias_g+dbg, bias_a+dba) to first order."""
        dbg = np.asarray(dbg, float); dba = np.asarray(dba, float)
        dR_c = self.dR @ exp_so3_vec(self.dR_dbg @ dbg)
        dV_c = self.dV + self.dV_dbg @ dbg + self.dV_dba @ dba
        dP_c = self.dP + self.dP_dbg @ dbg + self.dP_dba @ dba
        return dR_c, dV_c, dP_c

    # -- forward prediction (eq. 32) at the linearization bias --
    def predict(self, Ri, vi, pi, g=GRAVITY):
        Ri = np.asarray(Ri, float); vi = np.asarray(vi, float); pi = np.asarray(pi, float)
        g = np.asarray(g, float); DT = self.dt
        Rj = Ri @ self.dR
        vj = vi + g * DT + Ri @ self.dV
        pj = pi + vi * DT + 0.5 * g * DT * DT + Ri @ self.dP
        return Rj, vj, pj

    # -- 9-vector residual (eq. 45) --
    def residual(self, Ri, pi, vi, bgi, bai, Rj, pj, vj, g=GRAVITY):
        Ri = np.asarray(Ri, float); Rj = np.asarray(Rj, float)
        pi = np.asarray(pi, float); pj = np.asarray(pj, float)
        vi = np.asarray(vi, float); vj = np.asarray(vj, float)
        g = np.asarray(g, float); DT = self.dt
        dbg = np.asarray(bgi, float) - self.bias_g
        dba = np.asarray(bai, float) - self.bias_a
        dR_c, dV_c, dP_c = self.corrected(dbg, dba)
        r_R = log_so3_vec(dR_c.T @ Ri.T @ Rj)
        r_v = Ri.T @ (vj - vi - g * DT) - dV_c
        r_p = Ri.T @ (pj - pi - vi * DT - 0.5 * g * DT * DT) - dP_c
        return np.concatenate([r_R, r_v, r_p])


def preintegrate(gyro, accel, dts, bias_g=None, bias_a=None,
                 sigma_g_density: float = 4.36e-5, sigma_a_density: float = 1.0e-3) -> PreintegratedImu:
    """Preintegrate a raw IMU window (Forster eq. 33-45).

    gyro (M,3) rad/s, accel (M,3) m/s^2 body-frame specific force, dts (M,) s. bias_g/bias_a (3,) the
    linearization biases (default 0). sigma_*_density are continuous white-noise DENSITIES
    (rad/s/sqrt(Hz), m/s^2/sqrt(Hz)); Stim300-class defaults (ARW 0.15 deg/sqrt(hr), VRW 0.06
    m/s/sqrt(hr)) -- disclosed, NOT tuned to any ground truth."""
    gyro = np.asarray(gyro, float); accel = np.asarray(accel, float); dts = np.asarray(dts, float)
    if not (gyro.shape == accel.shape and gyro.shape[0] == dts.shape[0] and gyro.shape[1] == 3):
        raise ValueError(f"gyro {gyro.shape}, accel {accel.shape}, dts {dts.shape} incompatible "
                         "(need gyro/accel (M,3) and dts (M,))")
    bg = np.zeros(3) if bias_g is None else np.asarray(bias_g, float)
    ba = np.zeros(3) if bias_a is None else np.asarray(bias_a, float)

    dR = np.eye(3); dV = np.zeros(3); dP = np.zeros(3)
    JR_bg = np.zeros((3, 3)); JV_bg = np.zeros((3, 3)); JV_ba = np.zeros((3, 3))
    JP_bg = np.zeros((3, 3)); JP_ba = np.zeros((3, 3))
    cov = np.zeros((9, 9))
    I3 = np.eye(3)
    total = 0.0
    M = gyro.shape[0]
    for k in range(M):
        dt = float(dts[k])
        if dt <= 0.0:
            raise ValueError(f"non-positive dt at sample {k}: {dt} (filter duplicate/rollover "
                             "timestamps before preintegrating)")
        a = accel[k] - ba                       # bias-corrected specific force
        w = gyro[k] - bg                         # bias-corrected angular rate
        dR_a = dR @ a                            # pre-step rotated accel
        a_hat = hat(a)
        dRstep = exp_so3_vec(w * dt)
        Jr = right_jacobian_so3(w * dt)

        # --- covariance propagation (build A,B from PRE-step dR) ---
        A = np.eye(9)
        A[0:3, 0:3] = dRstep.T
        A[3:6, 0:3] = -dR @ a_hat * dt
        A[6:9, 0:3] = -0.5 * dR @ a_hat * dt * dt
        A[6:9, 3:6] = I3 * dt
        B = np.zeros((9, 6))
        B[0:3, 0:3] = Jr * dt
        B[3:6, 3:6] = dR * dt
        B[6:9, 3:6] = 0.5 * dR * dt * dt
        sg2 = sigma_g_density ** 2 / dt          # discrete per-step gyro variance
        sa2 = sigma_a_density ** 2 / dt          # discrete per-step accel variance
        Seta = np.zeros((6, 6)); Seta[0:3, 0:3] = sg2 * I3; Seta[3:6, 3:6] = sa2 * I3
        cov = A @ cov @ A.T + B @ Seta @ B.T

        # --- bias Jacobians (use PRE-step dR, JR_bg; compute all new-from-old simultaneously) ---
        JP_bg_new = JP_bg + JV_bg * dt - 0.5 * dR @ a_hat @ JR_bg * dt * dt
        JP_ba_new = JP_ba + JV_ba * dt - 0.5 * dR * dt * dt
        JV_bg_new = JV_bg - dR @ a_hat @ JR_bg * dt
        JV_ba_new = JV_ba - dR * dt
        JR_bg_new = dRstep.T @ JR_bg - Jr * dt

        # --- integrate the increments (p uses pre-step dV,dR; v uses pre-step dR; R advances) ---
        dP = dP + dV * dt + 0.5 * dR_a * dt * dt
        dV = dV + dR_a * dt
        dR = dR @ dRstep

        JP_bg, JP_ba, JV_bg, JV_ba, JR_bg = JP_bg_new, JP_ba_new, JV_bg_new, JV_ba_new, JR_bg_new
        total += dt

    cov = 0.5 * (cov + cov.T)
    return PreintegratedImu(dR=dR, dV=dV, dP=dP, dt=total, cov=cov,
                            dR_dbg=JR_bg, dV_dbg=JV_bg, dV_dba=JV_ba, dP_dbg=JP_bg, dP_dba=JP_ba,
                            bias_g=bg, bias_a=ba, n_samples=M)
