"""SE(2) pose-graph SLAM (Gauss-Newton), the estimator backbone (algorithm A5/A7).

Real least-squares pose-graph optimization in pure NumPy (no gtsam dependency). It
fuses the factors the dissertation needs:
  - prior      : anchor a pose (gauge + the meerkat lookout anchor for A7)
  - odom       : relative SE(2) between two poses (wheel odometry backbone)
  - heading    : absolute yaw at a pose (the solar-heading factor, A1)
  - landmark   : bearing to a known landmark (A4 triangulation aid)
Multi-rover (A7) reuses `odom` as an inter-rover relative-pose factor across two
trajectories packed into one pose array. Analytic Jacobians; diagonal information.

Pose state: an (N,3) array of [x, y, theta]. Angles wrapped to (-pi, pi].
"""
from __future__ import annotations

import numpy as np


def wrap(a):
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


def _Rt(th):
    """R(-th): rotates a world vector into the body frame at heading th."""
    c, s = np.cos(th), np.sin(th)
    return np.array([[c, s], [-s, c]])


class PoseGraph:
    def __init__(self):
        self.factors = []

    def add_prior(self, i, z, info=(1e6, 1e6, 1e6)):
        self.factors.append(("prior", int(i), np.asarray(z, float), np.asarray(info, float)))

    def add_odom(self, i, j, z, info=(100.0, 100.0, 100.0)):
        self.factors.append(("odom", int(i), int(j), np.asarray(z, float), np.asarray(info, float)))

    def add_heading(self, i, z, info=1000.0):
        self.factors.append(("heading", int(i), float(z), float(info)))

    def add_landmark(self, i, lm_xy, bearing, info=200.0):
        self.factors.append(("landmark", int(i), np.asarray(lm_xy, float), float(bearing), float(info)))

    # --- residual + Jacobian assembly ---
    def _linearize(self, X):
        N = X.shape[0]
        rows_r, rows_J, w = [], [], []
        for f in self.factors:
            kind = f[0]
            if kind == "prior":
                _, i, z, info = f
                r = X[i] - z; r[2] = wrap(r[2])
                J = np.zeros((3, 3 * N)); J[:, 3*i:3*i+3] = np.eye(3)
                rows_r.append(r); rows_J.append(J); w.append(info)
            elif kind == "odom":
                _, i, j, z, info = f
                c, s = np.cos(X[i, 2]), np.sin(X[i, 2])
                dp = X[j, :2] - X[i, :2]
                pred = np.array([c*dp[0] + s*dp[1], -s*dp[0] + c*dp[1], wrap(X[j, 2] - X[i, 2])])
                r = pred - z; r[2] = wrap(r[2])
                J = np.zeros((3, 3 * N))
                # d/d pose_i
                J[0, 3*i:3*i+3] = [-c, -s, (-s*dp[0] + c*dp[1])]
                J[1, 3*i:3*i+3] = [ s, -c, (-c*dp[0] - s*dp[1])]
                J[2, 3*i+2] = -1.0
                # d/d pose_j
                J[0, 3*j:3*j+3] = [ c,  s, 0.0]
                J[1, 3*j:3*j+3] = [-s,  c, 0.0]
                J[2, 3*j+2] = 1.0
                rows_r.append(r); rows_J.append(J); w.append(info)
            elif kind == "heading":
                _, i, z, info = f
                r = np.array([wrap(X[i, 2] - z)])
                J = np.zeros((1, 3 * N)); J[0, 3*i+2] = 1.0
                rows_r.append(r); rows_J.append(J); w.append(np.array([info]))
            elif kind == "landmark":
                _, i, lm, z, info = f
                dx, dy = lm[0] - X[i, 0], lm[1] - X[i, 1]
                q = dx*dx + dy*dy
                r = np.array([wrap(np.arctan2(dy, dx) - X[i, 2] - z)])
                J = np.zeros((1, 3 * N))
                J[0, 3*i:3*i+3] = [dy/q, -dx/q, -1.0]
                rows_r.append(r); rows_J.append(J); w.append(np.array([info]))
        r = np.concatenate(rows_r)
        J = np.vstack(rows_J)
        W = np.concatenate(w)
        return r, J, W

    def solve(self, X0, iters=30, tol=1e-9, huber_delta=None):
        """Gauss-Newton (IRLS with an optional Huber robust loss).

        huber_delta (in whitened-residual sigma units, e.g. 2.0) down-weights gross
        outliers: rows with |whitened residual| > delta get weight delta/|r| instead of 1,
        so a few bad bearings/loops cannot dominate. None = plain least squares."""
        X = np.array(X0, float)
        N = X.shape[0]
        for _ in range(iters):
            r, J, W = self._linearize(X)
            sw = np.sqrt(W)
            Jw = J * sw[:, None]
            rw = r * sw
            if huber_delta is not None:
                a = np.abs(rw)
                wh = np.where(a <= huber_delta, 1.0, huber_delta / np.maximum(a, 1e-12))
                shw = np.sqrt(wh)
                Jw = Jw * shw[:, None]
                rw = rw * shw
            H = Jw.T @ Jw + 1e-9 * np.eye(3 * N)
            b = Jw.T @ rw
            dx = np.linalg.solve(H, -b).reshape(N, 3)
            X[:, :2] += dx[:, :2]
            X[:, 2] = wrap(X[:, 2] + dx[:, 2])
            if np.linalg.norm(dx) < tol:
                break
        return X

    def information_matrix(self, X):
        """H = J^T W J at X (the Fisher information of the pose estimate)."""
        _, J, W = self._linearize(np.asarray(X, float))
        Jw = J * np.sqrt(W)[:, None]
        return Jw.T @ Jw + 1e-9 * np.eye(3 * np.asarray(X).shape[0])

    def covariance(self, X):
        """Full pose covariance = H^{-1} (the differential uncertainty of the estimate)."""
        return np.linalg.inv(self.information_matrix(X))

    def pose_covariances(self, X):
        """Per-pose marginal 3x3 covariances [x, y, theta]."""
        cov = self.covariance(X); N = np.asarray(X).shape[0]
        return [cov[3*i:3*i+3, 3*i:3*i+3] for i in range(N)]


def integrate_odometry(start_pose, odoms):
    """Dead-reckon a trajectory from a start pose and a list of SE(2) relative steps
    z=[dx,dy,dtheta] (each in the previous pose's body frame). Returns (N,3) poses."""
    X = [np.asarray(start_pose, float)]
    for z in odoms:
        x = X[-1]
        c, s = np.cos(x[2]), np.sin(x[2])
        nx = np.array([x[0] + c*z[0] - s*z[1], x[1] + s*z[0] + c*z[1], wrap(x[2] + z[2])])
        X.append(nx)
    return np.array(X)


def relative_odometry(poses):
    """SE(2) relative steps between consecutive poses (the inverse of integrate)."""
    odoms = []
    for a, b in zip(poses[:-1], poses[1:]):
        c, s = np.cos(a[2]), np.sin(a[2])
        dp = b[:2] - a[:2]
        odoms.append(np.array([c*dp[0] + s*dp[1], -s*dp[0] + c*dp[1], wrap(b[2] - a[2])]))
    return odoms
