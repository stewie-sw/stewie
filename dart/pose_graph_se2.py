"""#78: the SE(2)+IMU pose-graph estimator (orientation-aware upgrade of dart.pose_graph).

Estimates (x, y, yaw) per node by Gauss-Newton on the SE(2) manifold. This is the orientation
state the 2-D position graph lacked and that ARGUS needs: the rover drives in its body frame, and
the shadow/stereo factors are heading-dependent. Factor types:

  prior(i, (x,y,yaw), sigma_xy, sigma_yaw)   anchor a full pose
  between(i, j, (dx,dy,dyaw), ...)           a relative SE(2) motion in i's BODY frame (wheel odo)
  imu_yaw(i, j, dyaw, sigma)                 a gyro-PREINTEGRATED relative heading change (IMU)
  absolute(i, (x,y), sigma)                  a map-relative position fix (DEM scan / shadow outline)

Planar by design: pitch/roll are terrain-conformance outputs (rover.conform_pose), not free
estimator state, so a ground rover's estimable DOF are exactly (x, y, yaw). Full 6-DOF SE(3) (a
flying/articulated body) would add (z, roll, pitch) the same way; the rover does not need them.

The relative SE(2) residual is nonlinear in yaw, so this iterates (unlike the linear 2-D graph);
Jacobians are numerical (robust + exact-to-machine for these small graphs). Real factors only.
"""
from __future__ import annotations

import math

import numpy as np


def _wrap(a: float) -> float:
    """Wrap an angle to (-pi, pi]."""
    return (float(a) + math.pi) % (2.0 * math.pi) - math.pi


def _relative(pi: np.ndarray, pj: np.ndarray) -> np.ndarray:
    """The SE(2) relative pose T_i^-1 ⊗ T_j as (dx, dy, dyaw) in i's body frame."""
    c, s = math.cos(pi[2]), math.sin(pi[2])
    dxw, dyw = pj[0] - pi[0], pj[1] - pi[1]
    return np.array([c * dxw + s * dyw, -s * dxw + c * dyw, _wrap(pj[2] - pi[2])])


class PoseGraphSE2:
    """A sparse SE(2) pose graph. Add factors, then optimize() -> {id: (x, y, yaw)}."""

    def __init__(self) -> None:
        self._priors: list = []      # (i, pose[3], W[3])
        self._between: list = []     # (i, j, meas[3], W[3])
        self._imu: list = []         # (i, j, dyaw, w)
        self._abs: list = []         # (i, xy[2], w)
        self._ids: set = set()

    @staticmethod
    def _w(sigma: float) -> float:
        return 1.0 / max(1e-12, float(sigma) ** 2)

    def add_prior(self, i: int, pose, sigma_xy: float, sigma_yaw: float) -> None:
        self._priors.append((int(i), np.asarray(pose, float),
                             np.array([self._w(sigma_xy), self._w(sigma_xy), self._w(sigma_yaw)])))
        self._ids.add(int(i))

    def add_between(self, i: int, j: int, meas, sigma_xy: float, sigma_yaw: float) -> None:
        self._between.append((int(i), int(j), np.asarray(meas, float),
                              np.array([self._w(sigma_xy), self._w(sigma_xy), self._w(sigma_yaw)])))
        self._ids.update((int(i), int(j)))

    def add_imu_yaw(self, i: int, j: int, dyaw: float, sigma: float) -> None:
        self._imu.append((int(i), int(j), float(dyaw), self._w(sigma)))
        self._ids.update((int(i), int(j)))

    def add_absolute(self, i: int, xy, sigma: float) -> None:
        self._abs.append((int(i), np.asarray(xy, float), self._w(sigma)))
        self._ids.add(int(i))

    # -- residuals (stacked, information-weighted as sqrt(w)*r so J^T J = the normal matrix) --------
    def _residuals(self, X: np.ndarray, idx: dict) -> np.ndarray:
        r: list = []
        for i, p0, W in self._priors:
            d = X[idx[i]] - p0; d[2] = _wrap(d[2])
            r.extend(np.sqrt(W) * d)
        for i, j, meas, W in self._between:
            e = _relative(X[idx[i]], X[idx[j]]) - meas; e[2] = _wrap(e[2])
            r.extend(np.sqrt(W) * e)
        for i, j, dyaw, w in self._imu:
            r.append(math.sqrt(w) * _wrap((X[idx[j]][2] - X[idx[i]][2]) - dyaw))
        for i, xy, w in self._abs:
            r.extend(math.sqrt(w) * (X[idx[i]][:2] - xy))
        return np.asarray(r, float)

    def _solve(self, iters: int = 25):
        order = sorted(self._ids)
        idx = {nid: k for k, nid in enumerate(order)}
        n = len(order)
        if n == 0:
            return order, np.zeros((0, 3)), np.zeros((0, 0))
        X = np.zeros((n, 3))
        # initialise from the prior + chained between-factors so GN starts near the basin
        for i, p0, _W in self._priors:
            X[idx[i]] = p0
        for i, j, meas, _W in self._between:
            a, b = idx[i], idx[j]
            c, s = math.cos(X[a][2]), math.sin(X[a][2])
            X[b] = [X[a][0] + c * meas[0] - s * meas[1],
                    X[a][1] + s * meas[0] + c * meas[1], _wrap(X[a][2] + meas[2])]
        eps = 1e-6
        H = None
        for _ in range(iters):
            r0 = self._residuals(X, idx)
            m = r0.size
            J = np.zeros((m, 3 * n))
            for v in range(3 * n):                       # numerical Jacobian (small graphs)
                node, comp = divmod(v, 3)
                Xp = X.copy(); Xp[node, comp] += eps
                J[:, v] = (self._residuals(Xp, idx) - r0) / eps
            H = J.T @ J + 1e-9 * np.eye(3 * n)
            g = J.T @ r0
            dx = np.linalg.solve(H, -g).reshape(n, 3)
            X = X + dx
            X[:, 2] = np.array([_wrap(a) for a in X[:, 2]])
            if np.linalg.norm(dx) < 1e-10:
                break
        return order, X, H

    def optimize(self) -> dict:
        order, X, _H = self._solve()
        return {nid: (float(X[k, 0]), float(X[k, 1]), float(X[k, 2])) for k, nid in enumerate(order)}

    def optimize_with_cov(self) -> dict:
        """Estimate + per-node xy / yaw 1-sigma from the inverse information matrix."""
        order, X, H = self._solve()
        pose = {nid: (float(X[k, 0]), float(X[k, 1]), float(X[k, 2])) for k, nid in enumerate(order)}
        xy_sigma, yaw_sigma = {}, {}
        if len(order):
            cov = np.linalg.inv(H)
            for k, nid in enumerate(order):
                xy_sigma[nid] = float(np.sqrt(0.5 * (cov[3 * k, 3 * k] + cov[3 * k + 1, 3 * k + 1])))
                yaw_sigma[nid] = float(np.sqrt(max(0.0, cov[3 * k + 2, 3 * k + 2])))
        return {"pose": pose, "xy_sigma": xy_sigma, "yaw_sigma": yaw_sigma}
