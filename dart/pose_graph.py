"""#78 (ARGUS subsystem): a windowed 2-D pose-graph estimator.

The unified-state contract the thesis protects, made concrete: a sparse least-squares graph over
2-D positions x_i, with three factor types, all sourced from the existing primitives --

  prior(i, x0, sigma)            -- the start fix / map anchor
  odometry(i, j, dx, sigma)      -- the drift model (relative motion between nodes)
  absolute(i, z, sigma)          -- a map-relative fix: DEM scan-registration (dart.localization
                                    register_to_dem) OR a SHADOW-outline match (shadow_fix_from_outline)

Each factor is a Gaussian residual; the MAP estimate minimizes the sum of squared
information-weighted residuals. For 2-D position-only factors the problem is LINEAR, so one
normal-equation solve is exact (no iteration); the marginal covariance comes from the inverse
information matrix. This is the structure resync.py's per-axis fuse was the 1-D placeholder for,
and the seam where the shadow channel becomes an instrument rather than a nuisance.

Honest scope: position-only (x, y) today; full SE(3) with orientation + IMU preintegration is the
next slice (the research track's pose graph proper). Real factors only -- no fabricated measurements.
"""
from __future__ import annotations

import numpy as np


class PoseGraph:
    """A sparse 2-D position pose graph. Nodes are integer ids; add factors, then optimize()."""

    def __init__(self) -> None:
        self._priors: list = []      # (i, x[2], info)
        self._odo: list = []         # (i, j, dx[2], info)
        self._abs: list = []         # (i, z[2], info)
        self._ids: set = set()

    @staticmethod
    def _info(sigma: float) -> float:
        return 1.0 / max(1e-12, float(sigma) ** 2)

    def add_prior(self, i: int, x0, sigma: float) -> None:
        self._priors.append((int(i), np.asarray(x0, float), self._info(sigma)))
        self._ids.add(int(i))

    def add_odometry(self, i: int, j: int, dx, sigma: float) -> None:
        self._odo.append((int(i), int(j), np.asarray(dx, float), self._info(sigma)))
        self._ids.update((int(i), int(j)))

    def add_absolute(self, i: int, z, sigma: float) -> None:
        self._abs.append((int(i), np.asarray(z, float), self._info(sigma)))
        self._ids.add(int(i))

    def _solve(self):
        """Build and solve the normal equations H x = b PER AXIS (x and y decouple for 2-D
        position factors). Returns (order, X[n,2], Hx, Hy) for covariance reuse."""
        order = sorted(self._ids)
        idx = {nid: k for k, nid in enumerate(order)}
        n = len(order)
        if n == 0:
            return order, np.zeros((0, 2)), np.zeros((0, 0)), np.zeros((0, 0))
        Hx = np.zeros((n, n)); Hy = np.zeros((n, n))
        bx = np.zeros(n); by = np.zeros(n)
        for i, x0, w in self._priors:
            k = idx[i]
            Hx[k, k] += w; Hy[k, k] += w
            bx[k] += w * x0[0]; by[k] += w * x0[1]
        for i, z, w in self._abs:
            k = idx[i]
            Hx[k, k] += w; Hy[k, k] += w
            bx[k] += w * z[0]; by[k] += w * z[1]
        for i, j, dx, w in self._odo:                    # residual x_j - x_i - dx
            a, b = idx[i], idx[j]
            for H, d in ((Hx, dx[0]), (Hy, dx[1])):
                H[a, a] += w; H[b, b] += w; H[a, b] -= w; H[b, a] -= w
            bx[a] -= w * dx[0]; bx[b] += w * dx[0]
            by[a] -= w * dx[1]; by[b] += w * dx[1]
        # a graph with only relative factors is gauge-free; the prior/absolute anchor it. A tiny
        # ridge keeps an under-anchored node solvable (documented, not a silent fudge).
        Hx += 1e-9 * np.eye(n); Hy += 1e-9 * np.eye(n)
        X = np.column_stack([np.linalg.solve(Hx, bx), np.linalg.solve(Hy, by)])
        return order, X, Hx, Hy

    def optimize(self) -> dict:
        """The MAP position estimate: {node_id: (x, y)}."""
        order, X, _hx, _hy = self._solve()
        return {nid: (float(X[k, 0]), float(X[k, 1])) for k, nid in enumerate(order)}

    def optimize_with_cov(self) -> dict:
        """The estimate PLUS the per-node 1-sigma position uncertainty (sqrt of the mean of the
        x/y marginal variances from H^-1) -- so an absolute fix visibly shrinks a node's sigma."""
        order, X, Hx, Hy = self._solve()
        pose = {nid: (float(X[k, 0]), float(X[k, 1])) for k, nid in enumerate(order)}
        sigma = {}
        if len(order):
            cx = np.linalg.inv(Hx); cy = np.linalg.inv(Hy)
            for k, nid in enumerate(order):
                sigma[nid] = float(np.sqrt(0.5 * (cx[k, k] + cy[k, k])))
        return {"pose": pose, "sigma": sigma}


def shadow_fix_from_outline(shadow_mask, *, cell_m: float, prior_xy, sigma_floor_m: float = 0.5):
    """#78/[REQ:SN]: turn a cast-shadow outline into an absolute position fix for the graph.

    The shadow boundary (lit<->dark transition) is a terrain-anchored landmark: its CENTROID in
    the local map frame is a position observable the rover can match against the predicted shadow
    from the conserved terrain + sun. Returns (xy_m, sigma_m). Confidence (-> sigma) scales with
    how SHARP the outline is -- a long, well-defined shadow edge localizes better than a fuzzy one.
    This is the structural form of the ARGUS shadow-as-instrument claim; the dense edge-matching
    front-end (SuperGlue-class) is the perception slice (#79).
    """
    m = np.asarray(shadow_mask, dtype=bool)
    rows, cols = np.where(m)
    if rows.size == 0:
        return (float(prior_xy[0]), float(prior_xy[1])), 1e3      # no shadow -> uninformative
    # the outline = boundary cells (shadowed cell adjacent to a lit cell)
    edge = np.zeros_like(m)
    edge[1:, :] |= m[1:, :] & ~m[:-1, :]
    edge[:, 1:] |= m[:, 1:] & ~m[:, :-1]
    er, ec = np.where(edge)
    if er.size == 0:
        er, ec = rows, cols
    cx = float(ec.mean()) * cell_m
    cy = float(er.mean()) * cell_m
    # sharper (more boundary cells per shadow area) -> tighter sigma; floor is honest
    sharpness = er.size / max(1, rows.size)
    sigma = max(sigma_floor_m, cell_m / (1.0 + 4.0 * sharpness))
    return (cx, cy), float(sigma)
