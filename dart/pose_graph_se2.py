"""#78: the SE(2)+IMU pose-graph estimator (orientation-aware upgrade of dart.pose_graph).

Estimates (x, y, yaw) per node by Gauss-Newton on the SE(2) manifold. This is the orientation
state the 2-D position graph lacked and that ARGUS needs: the rover drives in its body frame, and
the shadow/stereo factors are heading-dependent. Factor types:

  prior(i, (x,y,yaw), sigma_xy, sigma_yaw)   anchor a full pose
  between(i, j, (dx,dy,dyaw), ...)           a relative SE(2) motion in i's BODY frame (wheel odo)
  imu_yaw(i, j, dyaw, sigma)                 a gyro-PREINTEGRATED relative heading change (IMU)
  shadow_yaw(i, measured_yaw, sigma)         SN-03: a weak absolute-yaw factor from an accepted shadow
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


def yaw_from_shadow(shadow_world_az: float, observed_body_bearing: float) -> float:
    """SN-03: the rover heading implied by an accepted shadow. The anti-solar shadow has a known
    WORLD azimuth; its bearing in the rover BODY frame fixes the heading:
    yaw = shadow_world_az - observed_body_bearing (wrapped). Feed the result to add_shadow_yaw."""
    return _wrap(float(shadow_world_az) - float(observed_body_bearing))


def _relative(pi: np.ndarray, pj: np.ndarray) -> np.ndarray:
    """The SE(2) relative pose T_i^-1 ⊗ T_j as (dx, dy, dyaw) in i's body frame."""
    c, s = math.cos(pi[2]), math.sin(pi[2])
    dxw, dyw = pj[0] - pi[0], pj[1] - pi[1]
    return np.array([c * dxw + s * dyw, -s * dxw + c * dyw, _wrap(pj[2] - pi[2])])


class PoseGraphSE2:
    """A sparse SE(2) pose graph. Add factors, then optimize() -> {id: (x, y, yaw)}.

    M-01 (2026-06-14): the solve is a robust, damped (Levenberg-Marquardt) Gauss-Newton with a Huber
    kernel on the data factors (between / IMU / shadow-yaw / absolute), iterative reweighting (IRLS),
    explicit convergence + conditioning diagnostics (``solve_status``), and a trust-region step that
    rejects cost-increasing updates. ``robust=False`` reverts to a plain squared loss (kept so the
    outlier-robustness improvement is testable head-to-head). The prior factor is the gauge anchor and
    is never down-weighted.
    """

    def __init__(self, *, robust: bool = True, huber_delta: float = 1.345) -> None:
        self._priors: list = []      # (i, pose[3], W[3])
        self._between: list = []     # (i, j, meas[3], W[3])
        self._imu: list = []         # (i, j, dyaw, w)
        self._shadow_yaw: list = []  # SN-03 (i, measured_yaw, w): weak absolute-yaw factor from shadow
        self._abs: list = []         # (i, xy[2], w)            -- isotropic absolute (x,y)
        self._abs_cov: list = []     # (i, xy[2], sqrt_info[2,2]) -- H-30 anisotropic absolute (x,y), keeps GDOP
        self._ids: set = set()
        self._robust = bool(robust)
        # Huber threshold on the whitened residual; 1.345 is the 95%-efficiency constant for unit-sigma
        # Gaussian noise (residuals are already information-weighted, so the scale is in sigma units).
        self._huber_delta = float(huber_delta)
        # populated by _solve(): convergence + conditioning diagnostics for solve_status()
        self._status: dict = {}

    @staticmethod
    def _w(sigma: float) -> float:
        """Information weight 1/sigma^2 for a measurement sigma. M-04 (2026-06-14): a sigma must be a
        finite, strictly-positive uncertainty. The old code clamped sigma<=0 to 1e-12, fabricating an
        ~1e24 information weight (over-confident, near-singular); reject the bad input instead."""
        s = float(sigma)
        if not math.isfinite(s) or s <= 0.0:
            raise ValueError(f"sigma must be finite and > 0 (got {sigma!r}); a non-positive/non-finite "
                             "sigma is not a valid measurement uncertainty")
        return 1.0 / (s * s)

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

    def add_shadow_yaw(self, i: int, measured_yaw: float, sigma: float) -> None:
        """SN-03: fuse an accepted shadow as a WEAK absolute-yaw factor with covariance (sigma from
        the shadow-sigma operating envelope: sharp low-sun shadow = small sigma, fuzzy high-sun =
        large). Never an unqualified heading -- one more covariance-weighted factor, so a confident
        prior/IMU can outweigh a fuzzy shadow."""
        self._shadow_yaw.append((int(i), float(measured_yaw), self._w(sigma)))
        self._ids.add(int(i))

    def add_absolute(self, i: int, xy, sigma: float) -> None:
        self._abs.append((int(i), np.asarray(xy, float), self._w(sigma)))
        self._ids.add(int(i))

    def add_absolute_cov(self, i: int, xy, cov, *, sigma_floor_m: float = 1e-3) -> None:
        """H-30: an ANISOTROPIC absolute (x,y) factor that keeps the full 2x2 measurement COVARIANCE (the
        GDOP direction), not a collapsed scalar sigma. Stored as the sqrt-information matrix S (S^T S = the
        information matrix) so the stacked residual S @ (x - z) makes J^T J the information matrix exactly.
        A small sigma_floor (default 1 mm on each axis) guards against an over-confident near-singular cov.

        M-04 (2026-06-14): the input covariance must be finite and positive-(semi)definite. A NaN/Inf
        entry, a negative variance, or an indefinite/non-symmetric matrix is not a covariance and is
        rejected here rather than Cholesky-factored into a garbage information matrix."""
        cov = np.asarray(cov, float).reshape(2, 2)
        if not np.all(np.isfinite(cov)):
            raise ValueError("absolute-fix covariance must be finite (no NaN/Inf entries)")
        sym = 0.5 * (cov + cov.T)
        if float(np.max(np.abs(cov - sym))) > 1e-9 * (1.0 + float(np.max(np.abs(cov)))):
            raise ValueError("absolute-fix covariance must be symmetric")
        eig = np.linalg.eigvalsh(sym)
        if float(eig.min()) <= 0.0:
            raise ValueError(f"absolute-fix covariance must be positive-definite (min eigenvalue "
                             f"{float(eig.min()):.3e} <= 0)")
        cov = sym + (float(sigma_floor_m) ** 2) * np.eye(2)
        info = np.linalg.inv(cov)
        info = 0.5 * (info + info.T)                       # symmetrize against round-off
        sqrt_info = np.linalg.cholesky(info).T            # upper factor: sqrt_info^T sqrt_info = info
        self._abs_cov.append((int(i), np.asarray(xy, float)[:2], sqrt_info))
        self._ids.add(int(i))

    # -- residuals (stacked, information-weighted as sqrt(w)*r so J^T J = the normal matrix) --------
    # Each entry carries a robust-block id: residual scalars from the SAME data factor share a block id
    # so the Huber kernel is applied on the factor's whitened residual NORM (not per scalar component).
    # The prior is the gauge anchor and is tagged non-robust (block id -1).
    def _residuals_blocked(self, X: np.ndarray, idx: dict):
        r: list = []
        block: list = []      # robust-block id per residual scalar; -1 = never down-weighted (prior)
        b = 0
        for i, p0, W in self._priors:
            d = X[idx[i]] - p0; d[2] = _wrap(d[2])
            vals = np.sqrt(W) * d
            r.extend(vals); block.extend([-1] * len(vals))     # prior: gauge anchor, non-robust
        for i, j, meas, W in self._between:
            e = _relative(X[idx[i]], X[idx[j]]) - meas; e[2] = _wrap(e[2])
            vals = np.sqrt(W) * e
            r.extend(vals); block.extend([b] * len(vals)); b += 1
        for i, j, dyaw, w in self._imu:
            r.append(math.sqrt(w) * _wrap((X[idx[j]][2] - X[idx[i]][2]) - dyaw))
            block.append(b); b += 1
        for i, myaw, w in self._shadow_yaw:                  # SN-03: absolute-yaw residual
            r.append(math.sqrt(w) * _wrap(X[idx[i]][2] - myaw))
            block.append(b); b += 1
        for i, xy, w in self._abs:
            vals = math.sqrt(w) * (X[idx[i]][:2] - xy)
            r.extend(vals); block.extend([b] * len(vals)); b += 1
        for i, xy, S in self._abs_cov:                       # H-30: anisotropic absolute (x,y) -- S @ (x - z)
            vals = S @ (X[idx[i]][:2] - xy)
            r.extend(vals); block.extend([b] * len(vals)); b += 1
        return np.asarray(r, float), np.asarray(block, int)

    def _residuals(self, X: np.ndarray, idx: dict) -> np.ndarray:
        return self._residuals_blocked(X, idx)[0]

    def _robust_weights(self, r: np.ndarray, block: np.ndarray) -> np.ndarray:
        """Per-residual sqrt(IRLS weight). Huber: w(s)=1 for |s|<=delta, else delta/|s|, computed on
        each robust block's whitened residual NORM (so a multi-DOF factor is down-weighted as a unit).
        Non-robust residuals (prior, block -1) and the plain-squared mode get weight 1."""
        w = np.ones_like(r)
        if not self._robust:
            return w
        delta = self._huber_delta
        for bid in np.unique(block):
            if bid < 0:
                continue                                     # prior: never down-weighted
            sel = block == bid
            norm = float(np.sqrt(np.sum(r[sel] ** 2)))       # whitened residual magnitude of the factor
            if norm > delta:
                w[sel] = math.sqrt(delta / norm)             # sqrt-weight so (sqrt_w*r) gives Huber cost
        return w

    def _solve(self, iters: int = 50):
        order = sorted(self._ids)
        idx = {nid: k for k, nid in enumerate(order)}
        n = len(order)
        if n == 0:
            self._status = {"converged": True, "iterations": 0, "condition_number": 1.0,
                            "well_conditioned": True, "final_gradient_norm": 0.0, "final_cost": 0.0}
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

        def robust_cost(X_):
            r_, blk_ = self._residuals_blocked(X_, idx)
            if not self._robust:
                return 0.5 * float(r_ @ r_)
            total = 0.0
            for bid in np.unique(blk_):
                sel = blk_ == bid
                norm = float(np.sqrt(np.sum(r_[sel] ** 2)))
                if bid < 0 or norm <= self._huber_delta:
                    total += 0.5 * norm * norm                       # quadratic region (and prior)
                else:
                    total += self._huber_delta * (norm - 0.5 * self._huber_delta)  # linear tail
            return total

        lam = 1e-3                                           # LM damping (trust region)
        H = None
        converged = False
        it = 0
        grad_norm = math.inf
        cost = robust_cost(X)
        for it in range(1, iters + 1):
            r0, block = self._residuals_blocked(X, idx)
            m = r0.size
            J = np.zeros((m, 3 * n))
            for v in range(3 * n):                       # numerical Jacobian (small graphs)
                node, comp = divmod(v, 3)
                Xp = X.copy(); Xp[node, comp] += eps
                J[:, v] = (self._residuals(Xp, idx) - r0) / eps
            sw = self._robust_weights(r0, block)         # IRLS sqrt-weights (Huber)
            Jw = J * sw[:, None]
            rw = r0 * sw
            JTJ = Jw.T @ Jw
            g = Jw.T @ rw
            grad_norm = float(np.linalg.norm(g))
            # Levenberg-Marquardt: damped step, accept only if the robust cost decreases.
            accepted = False
            for _ in range(12):
                H = JTJ + (lam + 1e-12) * np.eye(3 * n)
                try:
                    dx = np.linalg.solve(H, -g).reshape(n, 3)
                except np.linalg.LinAlgError:
                    lam *= 10.0
                    continue
                Xn = X + dx
                Xn[:, 2] = np.array([_wrap(a) for a in Xn[:, 2]])
                new_cost = robust_cost(Xn)
                if new_cost < cost:
                    X = Xn; cost = new_cost; lam = max(lam * 0.5, 1e-9); accepted = True
                    break
                lam *= 10.0
            if not accepted:
                # cannot make progress (at a minimum or stuck) -> stop; H from the last weighted normal eqs
                converged = grad_norm < 1e-4
                break
            if grad_norm < 1e-4 or float(np.linalg.norm(dx)) < 1e-9:
                converged = True
                break
        # final weighted information matrix (un-damped) for covariance + conditioning
        r0, block = self._residuals_blocked(X, idx)
        m = r0.size
        J = np.zeros((m, 3 * n))
        for v in range(3 * n):
            node, comp = divmod(v, 3)
            Xp = X.copy(); Xp[node, comp] += eps
            J[:, v] = (self._residuals(Xp, idx) - r0) / eps
        sw = self._robust_weights(r0, block)
        Jw = J * sw[:, None]
        info = Jw.T @ Jw
        H = info + 1e-9 * np.eye(3 * n)
        # conditioning: ratio of largest to smallest eigenvalue of the (un-damped) information matrix.
        evals = np.linalg.eigvalsh(0.5 * (info + info.T))
        lo = float(evals.min()); hi = float(evals.max())
        if lo <= 1e-12 or not math.isfinite(lo):
            cond = math.inf
        else:
            cond = hi / lo
        self._status = {
            "converged": bool(converged),
            "iterations": int(it),
            "condition_number": float(cond),
            "well_conditioned": bool(math.isfinite(cond) and cond < 1e6),
            "final_gradient_norm": float(grad_norm),
            "final_cost": float(cost),
        }
        return order, X, H

    def solve_status(self) -> dict:
        """M-01: run the solve and return its convergence + conditioning diagnostics (no pose). Keys:
        converged, iterations, condition_number, well_conditioned, final_gradient_norm, final_cost."""
        self._solve()
        return dict(self._status)

    def optimize(self) -> dict:
        order, X, _H = self._solve()
        return {nid: (float(X[k, 0]), float(X[k, 1]), float(X[k, 2])) for k, nid in enumerate(order)}

    def optimize_with_cov(self) -> dict:
        """Estimate + per-node xy / yaw 1-sigma from the inverse information matrix."""
        order, X, H = self._solve()
        pose = {nid: (float(X[k, 0]), float(X[k, 1]), float(X[k, 2])) for k, nid in enumerate(order)}
        # H-15: SE(2) gauge = (x, y, yaw). Translation is observable only with a prior/absolute-xy anchor;
        # yaw only with a prior/shadow-yaw anchor. Without them the solver ridge yields a finite-but-non-
        # physical sigma (the audit probe got ~23.5 km). Report observability and give an unobservable
        # component its honest INFINITE sigma instead of a misleading finite number.
        translation_anchored = bool(self._priors or self._abs or self._abs_cov)
        yaw_anchored = bool(self._priors or self._shadow_yaw)
        xy_sigma, yaw_sigma = {}, {}
        if len(order):
            cov = np.linalg.inv(H)
            for k, nid in enumerate(order):
                xy_sigma[nid] = (float(np.sqrt(0.5 * (cov[3 * k, 3 * k] + cov[3 * k + 1, 3 * k + 1])))
                                 if translation_anchored else math.inf)
                yaw_sigma[nid] = (float(np.sqrt(max(0.0, cov[3 * k + 2, 3 * k + 2])))
                                  if yaw_anchored else math.inf)
        return {"pose": pose, "xy_sigma": xy_sigma, "yaw_sigma": yaw_sigma,
                "observable": bool(translation_anchored and yaw_anchored)}
