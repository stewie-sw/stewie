"""3-D position pose graph with DEM height-normal anchoring -- the consumer that wires the committed
``FactorType.DEM_HEIGHT_NORMAL`` factor (dart.factors) into a real estimator.

Reproduces the DEM-anchoring leg of arXiv:2603.17229: a drifting stereo-VO trajectory is registered
into the DEM's local ENU frame and then re-solved against a prior DIGITAL ELEVATION MODEL, so the
accumulated (mostly vertical) VO drift is pulled back onto the terrain surface the rover must lie on.

State + factors (a sparse, analytic-Jacobian Gauss-Newton; no dense numerical Jacobian, so the full
~10^4-node traverse solves in well under a second per iteration):

  * state            p_i = (x, y, z)_i in the ENU frame, one node per VO keyframe.
  * prior(p0)        the single DECLARED coarse start fix (S3liDem origin); the gauge anchor.
  * between(i,i+1)   the VO ENU displacement d_i = p_{i+1}-p_i (the de-oracled stereo VO; never GT).
  * dem_height_normal(a)   a point-to-plane constraint to the DEM surface, sampled at the ESTIMATED
                     horizontal (x_a, y_a) -- residual r = z_a - H_dem(x_a, y_a); its Jacobian uses the
                     DEM SURFACE NORMAL at (x_a, y_a) (dH/dE = -n_x/n_z, dH/dN = -n_y/n_z), so a height
                     residual is distributed into the horizontal on sloped terrain. The DEM is re-sampled
                     at the CURRENT estimate every Gauss-Newton iteration.

TRUTH FIREWALL (invariant I3). The solver reads ONLY: the registered VO chain, the single declared
prior, and the DEM sampler queried at the ESTIMATED position. It never receives a ground-truth
trajectory, and -- critically -- it samples the DEM at the estimated (x, y), NEVER at a true/GT cell
(sampling at the true cell would leak GT). Ground truth is loaded only downstream, for scoring, after
the estimate is frozen.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). DEM: Copernicus GLO-30 (public).
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from dart.factors import EvidenceClass, FactorType, Frame, MeasurementFactor


class DemSampler(Protocol):
    """The DEM interface the anchor needs (satisfied by :class:`dart.s3li_dem.S3liDem`)."""

    def height_enu(self, east_m: float, north_m: float) -> float: ...
    def normal_enu(self, east_m: float, north_m: float) -> np.ndarray: ...


@dataclass(frozen=True)
class DemAnchorResult:
    """Frozen output of a DEM-anchored solve.

    ``xyz`` (N,3) is the optimized ENU trajectory; ``xyz_initial`` the registered-VO input it started
    from. ``mean_abs_height_correction_m`` / ``mean_abs_horizontal_correction_m`` summarise how far the
    DEM pulled the estimate. ``converged`` + ``iterations`` + ``final_cost`` are the solver diagnostics.
    ``n_xy_anchors`` is the number of DEM_XY absolute horizontal fixes fused (0 for height-only)."""

    xyz: np.ndarray
    xyz_initial: np.ndarray
    mean_abs_height_correction_m: float
    mean_abs_horizontal_correction_m: float
    converged: bool
    iterations: int
    final_cost: float
    n_xy_anchors: int = 0


def build_between_factors(deltas: np.ndarray, sigma_xyz_m: float) -> list[MeasurementFactor]:
    """One ODOMETRY_BETWEEN factor per VO step: keyframe i carries the ENU displacement p_{i+1}-p_i."""
    cov = np.eye(3) * float(sigma_xyz_m) ** 2
    out: list[MeasurementFactor] = []
    for i, d in enumerate(np.asarray(deltas, float)):
        out.append(MeasurementFactor(
            factor_type=FactorType.ODOMETRY_BETWEEN, keyframe=int(i), value=np.asarray(d, float),
            covariance=cov, frame=Frame.WORLD, source="superpoint_lightglue_stereo_vo",
            evidence_class=EvidenceClass.COMPUTED, metadata={"to": int(i + 1)}))
    return out


def build_dem_anchor_factors(indices: list[int], sigma_height_m: float) -> list[MeasurementFactor]:
    """One DEM_HEIGHT_NORMAL factor per anchored keyframe (height sigma; sampled live at solve time)."""
    cov = np.array([[float(sigma_height_m) ** 2]])
    return [MeasurementFactor(
        factor_type=FactorType.DEM_HEIGHT_NORMAL, keyframe=int(a), value=np.array([0.0]),
        covariance=cov, frame=Frame.DEM, source="copernicus_glo30_dem_prior",
        evidence_class=EvidenceClass.COMPUTED,
        metadata={"sampled_at": "estimated_xy"}) for a in indices]


def build_dem_xy_factors(
    indices: list[int], xy_values: np.ndarray, sigmas_m: np.ndarray | float,
    *, source: str = "dem_terrain_correlation",
) -> list[MeasurementFactor]:
    """One DEM_XY ABSOLUTE-position factor per registered keyframe: an absolute (E, N) fix obtained by
    correlating the rover's locally-observed terrain to the global DEM (NOT by comparing to GT). The fix
    constrains the horizontal translation/scale drift that DEM height-normal anchoring (vertical only)
    cannot. ``xy_values`` is (K, 2) ENU fixes; ``sigmas_m`` a per-fix isotropic 1-sigma (or one scalar).

    Truth firewall (invariant I3): the value is a terrain-correlation fix (estimated terrain vs the DEM
    prior), never a ground-truth position. The DEM is sampled at the ESTIMATED cell centres."""
    xy = np.asarray(xy_values, float).reshape(-1, 2)
    sig = np.broadcast_to(np.asarray(sigmas_m, float), (xy.shape[0],))
    out: list[MeasurementFactor] = []
    for a, z, s in zip(indices, xy, sig):
        if not (np.isfinite(s) and s > 0.0):
            raise ValueError(f"DEM_XY sigma must be finite and > 0 (got {s!r})")
        out.append(MeasurementFactor(
            factor_type=FactorType.DEM_XY, keyframe=int(a), value=np.asarray(z, float),
            covariance=np.eye(2) * float(s) ** 2, frame=Frame.DEM, source=source,
            evidence_class=EvidenceClass.COMPUTED, metadata={"sampled_at": "estimated_xy"}))
    return out


class DemHeightPoseGraph:
    """Sparse analytic Gauss-Newton over 3-D ENU node positions with DEM height-normal anchoring."""

    def __init__(self, dem: DemSampler) -> None:
        self.dem = dem

    def _linearize(self, X: np.ndarray, between: list[MeasurementFactor],
                   anchors: list[MeasurementFactor], prior_idx: int, prior_xyz: np.ndarray,
                   prior_sigma_m: float, xy_anchors: list[MeasurementFactor] | None = None):
        """Build the sqrt-weighted (rows = residuals) sparse Jacobian J and residual r at X.

        DEM factors re-sample H + normal at the CURRENT estimate (firewall: estimated (x,y), not GT).
        DEM_XY factors add an absolute (E, N) residual S @ (X[a,:2] - z) (sqrt-info S), pulling the
        horizontal translation/scale drift onto the terrain-correlation fixes."""
        n = X.shape[0]
        rows: list[int] = []
        cols: list[int] = []
        data: list[float] = []
        rvec: list[float] = []
        row = 0

        def add(r_idx: int, node: int, comp: int, coeff: float) -> None:
            rows.append(r_idx)
            cols.append(3 * node + comp)
            data.append(coeff)

        # prior (gauge anchor): sqrt(wp) * (X[p] - prior)
        wp = 1.0 / float(prior_sigma_m) ** 2
        sp_w = np.sqrt(wp)
        for c in range(3):
            add(row, prior_idx, c, sp_w)
            rvec.append(sp_w * (X[prior_idx, c] - prior_xyz[c]))
            row += 1

        # VO between (i -> j): sqrt(wb) * ((X[j]-X[i]) - d)
        for f in between:
            i = f.keyframe
            j = int(f.metadata["to"])
            d = np.asarray(f.value, float)
            wb = 1.0 / float(f.covariance_array()[0, 0])
            sb = np.sqrt(wb)
            for c in range(3):
                add(row, j, c, sb)
                add(row, i, c, -sb)
                rvec.append(sb * ((X[j, c] - X[i, c]) - d[c]))
                row += 1

        # DEM height-normal: sqrt(wd) * (z_a - H(x_a,y_a)); Jacobian uses the DEM normal (slope coupling)
        for f in anchors:
            a = f.keyframe
            wd = 1.0 / float(f.covariance_array()[0, 0])
            sd = np.sqrt(wd)
            xa, ya, za = float(X[a, 0]), float(X[a, 1]), float(X[a, 2])
            h = self.dem.height_enu(xa, ya)                      # sampled at ESTIMATE (I3)
            nrm = np.asarray(self.dem.normal_enu(xa, ya), float)
            nz = nrm[2] if abs(nrm[2]) > 1e-9 else 1e-9
            dHdx = -nrm[0] / nz                                  # dH/dE = -n_x/n_z
            dHdy = -nrm[1] / nz                                  # dH/dN = -n_y/n_z
            add(row, a, 0, sd * (-dHdx))                         # d(z-H)/dx = -dH/dE
            add(row, a, 1, sd * (-dHdy))
            add(row, a, 2, sd * 1.0)
            rvec.append(sd * (za - h))
            row += 1

        # DEM_XY absolute horizontal fix: S @ (X[a,:2] - z), S the 2x2 sqrt-information (S^T S = cov^-1).
        for f in xy_anchors or []:
            a = f.keyframe
            cov = f.xy_covariance()
            info = np.linalg.inv(cov)
            info = 0.5 * (info + info.T)
            s_info = np.linalg.cholesky(info).T            # upper factor: s_info^T s_info = info
            z = np.asarray(f.value, float).reshape(2)
            d_xy = np.array([float(X[a, 0]) - z[0], float(X[a, 1]) - z[1]])
            res2 = s_info @ d_xy
            for rr in range(2):
                add(row, a, 0, s_info[rr, 0])
                add(row, a, 1, s_info[rr, 1])
                rvec.append(float(res2[rr]))
                row += 1

        J = sp.csr_matrix((data, (rows, cols)), shape=(row, 3 * n))
        return J, np.asarray(rvec, float)

    def solve(self, initial_xyz: np.ndarray, between: list[MeasurementFactor],
              anchors: list[MeasurementFactor], *, prior_idx: int, prior_xyz: np.ndarray,
              prior_sigma_m: float, xy_anchors: list[MeasurementFactor] | None = None,
              iters: int = 12, tol: float = 1e-6) -> DemAnchorResult:
        """Gauss-Newton solve. Returns the optimized ENU trajectory + correction diagnostics.

        ``xy_anchors`` (optional) are DEM_XY absolute horizontal fixes fused jointly with the VIO
        between-factors and the DEM height-normal anchors (the horizontal terrain-correlation anchor)."""
        X = np.array(initial_xyz, float, copy=True)
        prior_xyz = np.asarray(prior_xyz, float)
        n = X.shape[0]
        ridge = 1e-9 * sp.identity(3 * n, format="csr")
        prev_cost = np.inf
        converged = False
        it = 0
        cost = np.inf
        for it in range(1, iters + 1):
            J, r = self._linearize(X, between, anchors, prior_idx, prior_xyz, prior_sigma_m, xy_anchors)
            cost = 0.5 * float(r @ r)
            H = (J.T @ J + ridge).tocsc()
            g = J.T @ r
            dx = spsolve(H, -g)
            X = X + np.asarray(dx, float).reshape(n, 3)
            step = float(np.linalg.norm(dx))
            if abs(prev_cost - cost) <= tol * (1.0 + cost) and step < 1e-6:
                converged = True
                break
            prev_cost = cost
        # final cost at the updated estimate
        _, r_final = self._linearize(X, between, anchors, prior_idx, prior_xyz, prior_sigma_m, xy_anchors)
        final_cost = 0.5 * float(r_final @ r_final)
        corr = X - np.asarray(initial_xyz, float)
        return DemAnchorResult(
            xyz=X,
            xyz_initial=np.asarray(initial_xyz, float),
            mean_abs_height_correction_m=float(np.mean(np.abs(corr[:, 2]))),
            mean_abs_horizontal_correction_m=float(np.mean(np.linalg.norm(corr[:, :2], axis=1))),
            converged=converged,
            iterations=it,
            final_cost=final_cost,
            n_xy_anchors=len(xy_anchors or []),
        )
