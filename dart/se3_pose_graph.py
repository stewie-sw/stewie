"""Full SE(3) pose-graph estimator -- the ORIENTATION-OPTIMISING upgrade of the position-only DEM graph.

The position-only solver (:mod:`dart.dem_height_graph`) holds every keyframe ORIENTATION fixed at its
VO front-end value and optimises only node positions, so a visual loop closure can translate the END arc
back onto the START arc but cannot un-bow the trajectory: the accumulated HEADING drift that bows the
single-loop traverse is frozen into the VO rotations and never redistributed. That is the documented
51 m floor on S3LI ``s3li_crater``.

This module removes that limitation. Each keyframe is a full SE(3) pose ``T_i = (R_i, t_i)`` (camera/
body-to-ENU rotation + ENU position) and BOTH the rotations and the positions are optimised jointly, on
the manifold. A loop closure now carries a relative ROTATION as well as a relative translation, so its
residual can rotate the whole inter-loop chain -- distributing the heading-closure error across every
odometry edge -- which is exactly the lever the literature (arXiv:2603.17229) uses to reach 21.4 m on
this sequence.

State + retraction (on-manifold Gauss-Newton / Levenberg-Marquardt):

  * state            ``T_i = (R_i in SO(3), t_i in R^3)`` per keyframe, increment ``xi_i = (phi, rho)``.
  * retraction       RIGHT perturbation, split form: ``R_i <- R_i Exp(phi_i)``, ``t_i <- t_i + R_i rho_i``
                     (Exp/Log are the SO(3) exponential/logarithm; the same retraction defines the
                     finite-difference Jacobian columns, so the linearisation is exact-to-first-order for
                     the step that is actually taken -- a genuine manifold GN, not an Euclidean fudge).

Factors (every residual is an SE(3) residual):

  * prior(0)         ``[Log(Rp^T R_0), Rp^T(t_0 - tp)]`` -- the single declared coarse start; gauge fix.
  * odometry(i,i+1)  the VO per-step relative pose ``T_i^{-1} T_{i+1}`` (rotation + translation).
  * loop(a,b)        the visual loop-closure relative pose from PnP -- rotation ``R_ab^T`` + translation
                     ``c_in_a`` -- expressed in keyframe a's frame (dart.loop_closure_visual).
  * dem_height(a)    ``z_a - H(x_a, y_a)`` sampled at the ESTIMATED (x, y); Jacobian uses the DEM surface
                     normal (slope coupling into the horizontal), re-sampled every iteration.
  * dem_normal(a)    align the body up-axis ``-R_a e_y`` to the DEM surface normal ``n(x_a, y_a)`` --
                     ``r = n x (-R_a e_y)`` -- the attitude constraint the position-only graph could not
                     represent. Re-sampled every iteration.

Robust kernel: a Huber re-weight (IRLS) on the LOOP and DEM rows (the prior + VO odometry are trusted).

TRUTH FIREWALL (invariant I3). The solver consumes ONLY: the VO relative poses (odometry edges), the
visual loop-closure relative poses (proposed by appearance + node index, verified by LightGlue + PnP --
NEVER GT proximity), the DEM sampled at the ESTIMATED (x, y), and the single declared start prior. No
function here takes a ground-truth trajectory; GT enters only downstream at scoring, after the freeze.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (public); DEM: Copernicus GLO-30.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

_E_Y = np.array([0.0, 1.0, 0.0])          # camera/body DOWN axis (ENU up = -R e_y after registration)


class DemSampler(Protocol):
    """The DEM interface the SE(3) anchor needs (satisfied by :class:`dart.s3li_dem.S3liDem`)."""

    def height_enu(self, east_m: float, north_m: float) -> float: ...
    def normal_enu(self, east_m: float, north_m: float) -> np.ndarray: ...


# ----------------------------------------------------------------------------------------------------
# SO(3) Lie-group helpers (vectorised). Exp/Log are the only nonlinear pieces; everything is real maths,
# no data -- these are the manifold operators the retraction and the rotation residuals are built on.
# ----------------------------------------------------------------------------------------------------
def hat(w: np.ndarray) -> np.ndarray:
    """Skew-symmetric matrix (or batch (...,3,3)) of a 3-vector (or batch (...,3))."""
    w = np.asarray(w, float)
    o = np.zeros(w.shape[:-1] + (3, 3), float)
    o[..., 0, 1] = -w[..., 2]; o[..., 0, 2] = w[..., 1]
    o[..., 1, 0] = w[..., 2];  o[..., 1, 2] = -w[..., 0]
    o[..., 2, 0] = -w[..., 1]; o[..., 2, 1] = w[..., 0]
    return o


def exp_so3(phi: np.ndarray) -> np.ndarray:
    """Vectorised SO(3) exponential: rotation-vector(s) ``phi`` (...,3) -> rotation matrix(es) (...,3,3).

    Rodrigues with a Taylor fallback for small angles (numerically stable to ``theta -> 0``)."""
    phi = np.asarray(phi, float)
    theta = np.linalg.norm(phi, axis=-1)                              # (...)
    K = hat(phi)                                                      # (...,3,3)
    K2 = K @ K
    small = theta < 1e-8
    t = np.where(small, 1.0, theta)                                  # avoid /0
    a = np.where(small, 1.0 - theta ** 2 / 6.0, np.sin(t) / t)       # sin x / x
    b = np.where(small, 0.5 - theta ** 2 / 24.0, (1.0 - np.cos(t)) / t ** 2)  # (1-cos x)/x^2
    eye = np.broadcast_to(np.eye(3), K.shape).copy()
    return eye + a[..., None, None] * K + b[..., None, None] * K2


def log_so3(R: np.ndarray) -> np.ndarray:
    """Vectorised SO(3) logarithm: rotation matrix(es) (...,3,3) -> rotation-vector(s) (...,3).

    Robust to ``theta -> 0`` (Taylor) and to ``theta -> pi`` (axis from the symmetric part)."""
    R = np.asarray(R, float)
    tr = np.trace(R, axis1=-2, axis2=-1)
    cos_t = np.clip((tr - 1.0) * 0.5, -1.0, 1.0)
    theta = np.arccos(cos_t)                                         # (...)
    # axis * 2 sin(theta) from the antisymmetric part
    w = np.stack([R[..., 2, 1] - R[..., 1, 2],
                  R[..., 0, 2] - R[..., 2, 0],
                  R[..., 1, 0] - R[..., 0, 1]], axis=-1)             # (...,3)
    out = np.zeros_like(w)
    small = theta < 1e-7
    out[small] = 0.5 * w[small]                                      # sin~theta -> 0.5*w
    mid = (~small) & (theta < np.pi - 1e-5)
    if np.any(mid):
        s = (theta[mid] / (2.0 * np.sin(theta[mid])))[..., None]
        out[mid] = s * w[mid]
    near_pi = theta >= np.pi - 1e-5
    if np.any(near_pi):                                             # axis from (R + I)/2 columns
        Rp = R[near_pi]
        A = 0.5 * (Rp + np.transpose(Rp, (0, 2, 1)))               # symmetric part ~ I + axis axis^T... actually (R+I)/2
        B = 0.5 * (Rp + np.eye(3))
        diag = np.clip(np.diagonal(B, axis1=-2, axis2=-1), 0.0, None)
        axis = np.sqrt(diag)                                        # |axis components|
        # fix signs from the off-diagonals of B (axis_i axis_j)
        for k in range(axis.shape[0]):
            i = int(np.argmax(axis[k]))
            if axis[k, i] > 0:
                axis[k] = B[k, i] / axis[k, i]
            nrm = np.linalg.norm(axis[k])
            axis[k] = axis[k] / nrm if nrm > 0 else np.array([1.0, 0.0, 0.0])
        out[near_pi] = theta[near_pi][..., None] * axis
        _ = A
    return out


def exp_se3_translation(phi: np.ndarray, rho: np.ndarray) -> np.ndarray:
    """The SE(3)-exp translation part ``V(phi) rho`` (used only if a full SE(3) exp is wanted; the
    estimator uses the simpler split retraction ``t <- t + R rho`` so this is provided for completeness
    and is exercised by the round-trip test)."""
    phi = np.asarray(phi, float); rho = np.asarray(rho, float)
    theta = float(np.linalg.norm(phi))
    K = hat(phi)
    if theta < 1e-8:
        V = np.eye(3) + 0.5 * K
    else:
        V = (np.eye(3) + (1.0 - np.cos(theta)) / theta ** 2 * K
             + (theta - np.sin(theta)) / theta ** 3 * (K @ K))
    return V @ rho


# ----------------------------------------------------------------------------------------------------
# edges
# ----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RelEdge:
    """A relative-pose (between) factor a -> b with measurement ``T_a^{-1} T_b = (R_meas, t_meas)`` and a
    diagonal information given by rotation / translation sigmas. ``robust`` marks it for Huber re-weight."""

    a: int
    b: int
    R_meas: np.ndarray
    t_meas: np.ndarray
    sigma_rot: float
    sigma_trans: float
    robust: bool = False
    kind: str = "odometry"


@dataclass(frozen=True)
class DemHeightEdge:
    a: int
    sigma_m: float


@dataclass(frozen=True)
class DemNormalEdge:
    a: int
    sigma: float


@dataclass(frozen=True)
class PriorEdge:
    a: int
    R_meas: np.ndarray
    t_meas: np.ndarray
    sigma_rot: float
    sigma_trans: float


@dataclass(frozen=True)
class SE3Result:
    """Frozen output of an SE(3) solve. ``R`` (N,3,3) + ``t`` (N,3) are the optimised poses; ``*_initial``
    the input. ``converged`` / ``iterations`` / ``final_cost`` / ``grad_norm`` are the solver diagnostics;
    ``cost_history`` the per-iteration 0.5||r||^2; ``mean_abs_*_correction`` summarise the motion."""

    R: np.ndarray
    t: np.ndarray
    R_initial: np.ndarray
    t_initial: np.ndarray
    converged: bool
    iterations: int
    final_cost: float
    grad_norm: float
    cost_history: list[float] = field(default_factory=list)
    mean_abs_horizontal_correction_m: float = 0.0
    mean_abs_height_correction_m: float = 0.0
    mean_abs_rotation_correction_deg: float = 0.0


# ----------------------------------------------------------------------------------------------------
# edge builders (firewall-clean: VO relative poses, PnP loop closures, the declared prior)
# ----------------------------------------------------------------------------------------------------
def build_odometry_edges(R0: np.ndarray, t0: np.ndarray, sigma_rot: float, sigma_trans: float) -> list[RelEdge]:
    """One odometry edge per consecutive keyframe pair, measurement = the VO relative pose
    ``T_i^{-1} T_{i+1}`` read off the INITIAL (registered VO) state. At the initial state every odometry
    residual is exactly zero; the solver then redistributes via the loop + prior + DEM factors."""
    R0 = np.asarray(R0, float); t0 = np.asarray(t0, float)
    out: list[RelEdge] = []
    for i in range(R0.shape[0] - 1):
        R_meas = R0[i].T @ R0[i + 1]
        t_meas = R0[i].T @ (t0[i + 1] - t0[i])
        out.append(RelEdge(i, i + 1, R_meas, t_meas, sigma_rot, sigma_trans, robust=False, kind="odometry"))
    return out


def build_loop_edges(closures, sigma_rot: float, sigma_trans: float) -> list[RelEdge]:
    """One loop edge per accepted visual loop closure. The PnP relative rotation ``r_ab = R_{cam_b<-cam_a}``
    gives the measured relative rotation in a's frame ``R_meas = r_ab^T`` (= ``R_a^T R_b``); the camera-b
    optical-centre-in-a ``c_in_a`` gives the measured relative translation ``t_meas`` (= ``R_a^T(t_b-t_a)``).
    These are the SAME geometry the position-only graph used (``d_enu = R_a c_in_a``) plus the rotation it
    discarded. Marked robust (Huber)."""
    out: list[RelEdge] = []
    for lc in closures:
        if not getattr(lc, "accepted", False):
            continue
        r_ab = np.asarray(lc.r_ab, float)
        out.append(RelEdge(int(lc.a_node), int(lc.b_node), r_ab.T, np.asarray(lc.c_in_a, float),
                           sigma_rot, sigma_trans, robust=True, kind="loop"))
    return out


# ----------------------------------------------------------------------------------------------------
# the solver
# ----------------------------------------------------------------------------------------------------
class SE3PoseGraph:
    """Sparse, on-manifold Gauss-Newton / Levenberg-Marquardt over full SE(3) keyframe poses.

    Jacobians are taken by finite differences in the SAME right-perturbation retraction used for the
    update, so each block is the exact first-order map of the step actually applied (the only nonlinear
    pieces are the SO(3) Log in the residuals and Exp in the retraction; both are batched). The DEM
    height/normal factors are re-sampled at the CURRENT estimate every iteration (firewall: estimated
    x, y -- never a GT cell)."""

    def __init__(self, dem: DemSampler | None = None, *, huber_delta: float = 1.345) -> None:
        self.dem = dem
        self.huber_delta = float(huber_delta)

    # ---- vectorised relative-pose residual (E edges) ----
    @staticmethod
    def _rel_residual(Ra, Rb, ta, tb, Rz, tz):
        """[Log(Rz^T Ra^T Rb), Rz^T(Ra^T(tb-ta) - tz)] for a batch of E edges -> (E,6), UNWEIGHTED."""
        Rrel = np.einsum("eji,ejk->eik", Ra, Rb)          # Ra^T Rb
        ER = np.einsum("eji,ejk->eik", Rz, Rrel)          # Rz^T Rrel
        rphi = log_so3(ER)                                # (E,3)
        dt = np.einsum("eji,ej->ei", Ra, tb - ta)         # Ra^T (tb-ta)
        Et = np.einsum("eji,ej->ei", Rz, dt - tz)         # Rz^T (dt - tz)
        return np.concatenate([rphi, Et], axis=1)         # (E,6)

    def _linearize_rel(self, edges, R, t, rows0, scale_rot, scale_trans, weights=None):
        """Finite-difference linearisation of a batch of relative edges. Returns (coo rows, cols, data,
        residual rows, n_rows). ``weights`` (E,) is the per-edge IRLS scale (sqrt) applied to all 6 rows."""
        E = len(edges)
        a = np.fromiter((e.a for e in edges), int, E)
        b = np.fromiter((e.b for e in edges), int, E)
        Rz = np.stack([e.R_meas for e in edges])
        tz = np.stack([e.t_meas for e in edges])
        sc = np.empty((E, 6))
        sc[:, :3] = scale_rot[:, None] if np.ndim(scale_rot) else scale_rot
        sc[:, 3:] = scale_trans[:, None] if np.ndim(scale_trans) else scale_trans
        if weights is not None:
            sc = sc * np.asarray(weights, float)[:, None]

        Ra, Rb, ta, tb = R[a], R[b], t[a], t[b]
        r0 = self._rel_residual(Ra, Rb, ta, tb, Rz, tz)                # (E,6) unweighted
        eps = 1e-6
        blk = np.zeros((E, 6, 12))                                     # d r / d [phi_a,rho_a,phi_b,rho_b]
        e3 = np.eye(3)
        for k in range(3):                                            # phi_a
            Rap = np.einsum("eij,ejk->eik", Ra, exp_so3(np.broadcast_to(eps * e3[k], (E, 3))))
            blk[:, :, k] = (self._rel_residual(Rap, Rb, ta, tb, Rz, tz) - r0) / eps
        for k in range(3):                                            # rho_a -> t_a + Ra (eps e_k)
            tap = ta + np.einsum("eij,j->ei", Ra, eps * e3[k])
            blk[:, :, 3 + k] = (self._rel_residual(Ra, Rb, tap, tb, Rz, tz) - r0) / eps
        for k in range(3):                                            # phi_b
            Rbp = np.einsum("eij,ejk->eik", Rb, exp_so3(np.broadcast_to(eps * e3[k], (E, 3))))
            blk[:, :, 6 + k] = (self._rel_residual(Ra, Rbp, ta, tb, Rz, tz) - r0) / eps
        for k in range(3):                                            # rho_b
            tbp = tb + np.einsum("eij,j->ei", Rb, eps * e3[k])
            blk[:, :, 9 + k] = (self._rel_residual(Ra, Rb, ta, tbp, Rz, tz) - r0) / eps

        blk *= sc[:, :, None]
        rvec = (r0 * sc).reshape(-1)                                   # (6E,)
        # scatter (E,6,12) into COO
        cols_node = np.concatenate([6 * a[:, None] + np.arange(6)[None, :],
                                    6 * b[:, None] + np.arange(6)[None, :]], axis=1)  # (E,12)
        row_base = rows0 + 6 * np.arange(E)
        rows = np.repeat(row_base[:, None, None] + np.arange(6)[None, :, None], 12, axis=2)
        cols = np.repeat(cols_node[:, None, :], 6, axis=1)
        return rows.reshape(-1), cols.reshape(-1), blk.reshape(-1), rvec, 6 * E

    def _solve_once(self, R, t, prior, odo, loop, dem_h, dem_n, lam):
        """Assemble J, r at the current (R, t); return (J, r, n_rows) for one linear step."""
        N = R.shape[0]
        ROWS: list = []; COLS: list = []; DATA: list = []; RVEC: list = []
        nrow = 0

        # prior (unary, node 0) -- gauge; never robust
        p = prior
        Rz = np.asarray(p.R_meas, float)[None]; tz = np.asarray(p.t_meas, float)[None]
        Ra = R[p.a:p.a + 1]; ta = t[p.a:p.a + 1]
        sr = 1.0 / p.sigma_rot; st = 1.0 / p.sigma_trans
        # prior residual (unary, node p.a): [Log(Rp^T Ra), Rp^T(ta - tp)]
        ER = Rz[0].T @ Ra[0]
        rphi = log_so3(ER[None])[0]
        Et = Rz[0].T @ (ta[0] - tz[0])
        rp = np.concatenate([rphi, Et])
        eps = 1e-6; e3 = np.eye(3)
        Jp = np.zeros((6, 6))
        for k in range(3):
            Rap = Ra[0] @ exp_so3(eps * e3[k])
            rphi_p = log_so3((Rz[0].T @ Rap)[None])[0]
            Jp[:3, k] = (rphi_p - rphi) / eps
        for k in range(3):
            tap = ta[0] + Ra[0] @ (eps * e3[k])
            Et_p = Rz[0].T @ (tap - tz[0])
            Jp[3:, 3 + k] = (Et_p - Et) / eps
        sc = np.array([sr, sr, sr, st, st, st])
        Jp *= sc[:, None]; rp = rp * sc
        for rr in range(6):
            for cc in range(6):
                if Jp[rr, cc] != 0.0:
                    ROWS.append(nrow + rr); COLS.append(6 * p.a + cc); DATA.append(Jp[rr, cc])
            RVEC.append(rp[rr])
        nrow += 6

        # odometry (vectorised, not robust)
        if odo:
            sro = np.full(len(odo), 1.0 / odo[0].sigma_rot)
            sto = np.full(len(odo), 1.0 / odo[0].sigma_trans)
            r, c, d, rv, nn = self._linearize_rel(odo, R, t, nrow, sro, sto)
            ROWS.append(r); COLS.append(c); DATA.append(d); RVEC.append(rv); nrow += nn

        # loop (vectorised, Huber-robust)
        if loop:
            srl = np.array([1.0 / e.sigma_rot for e in loop])
            stl = np.array([1.0 / e.sigma_trans for e in loop])
            # residual magnitude for IRLS (whitened): compute base residual first
            a = np.fromiter((e.a for e in loop), int, len(loop))
            b = np.fromiter((e.b for e in loop), int, len(loop))
            Rz = np.stack([e.R_meas for e in loop]); tz = np.stack([e.t_meas for e in loop])
            r_un = self._rel_residual(R[a], R[b], t[a], t[b], Rz, tz)
            wr = np.concatenate([srl[:, None] * np.ones((1, 3)), stl[:, None] * np.ones((1, 3))], axis=1)
            mag = np.linalg.norm(r_un * wr, axis=1)
            w = self._huber_w(mag)
            r, c, d, rv, nn = self._linearize_rel(loop, R, t, nrow, srl, stl, weights=np.sqrt(w))
            ROWS.append(r); COLS.append(c); DATA.append(d); RVEC.append(rv); nrow += nn

        # DEM height (unary, Huber-robust)
        if dem_h and self.dem is not None:
            for e in dem_h:
                x, y, z = float(t[e.a, 0]), float(t[e.a, 1]), float(t[e.a, 2])
                h = self.dem.height_enu(x, y)
                nrm = np.asarray(self.dem.normal_enu(x, y), float)
                nz = nrm[2] if abs(nrm[2]) > 1e-9 else 1e-9
                grad = np.array([nrm[0] / nz, nrm[1] / nz, 1.0])     # d(z-H)/dt = [-dH/dx,-dH/dy,1]=[n0/nz,n1/nz,1]
                Jrho = grad @ R[e.a]                                  # d/d rho = grad @ R_a
                res = z - h
                sd = 1.0 / e.sigma_m
                w = np.sqrt(self._huber_w(np.array([abs(res) * sd]))[0])
                sc1 = sd * w
                for cc in range(3):
                    if Jrho[cc] != 0.0:
                        ROWS.append(nrow); COLS.append(6 * e.a + 3 + cc); DATA.append(sc1 * Jrho[cc])
                RVEC.append(sc1 * res); nrow += 1

        # DEM normal (unary, Huber-robust): r = n x (-R_a e_y); couples to phi_a
        if dem_n and self.dem is not None:
            eps = 1e-6
            for e in dem_n:
                x, y = float(t[e.a, 0]), float(t[e.a, 1])
                n = np.asarray(self.dem.normal_enu(x, y), float)
                bup = -R[e.a] @ _E_Y
                r0n = np.cross(n, bup)
                sd = 1.0 / e.sigma
                w = np.sqrt(self._huber_w(np.array([np.linalg.norm(r0n) * sd]))[0])
                sc1 = sd * w
                Jn = np.zeros((3, 3))
                for k in range(3):
                    Rap = R[e.a] @ exp_so3(eps * e3[k])
                    bup_p = -Rap @ _E_Y
                    Jn[:, k] = (np.cross(n, bup_p) - r0n) / eps
                Jn *= sc1
                for rr in range(3):
                    for cc in range(3):
                        if Jn[rr, cc] != 0.0:
                            ROWS.append(nrow + rr); COLS.append(6 * e.a + cc); DATA.append(Jn[rr, cc])
                    RVEC.append(sc1 * r0n[rr])
                nrow += 3

        rows = np.concatenate([np.atleast_1d(x) for x in ROWS])
        cols = np.concatenate([np.atleast_1d(x) for x in COLS])
        data = np.concatenate([np.atleast_1d(x) for x in DATA])
        rvec = np.concatenate([np.atleast_1d(x) for x in RVEC])
        J = sp.csr_matrix((data, (rows, cols)), shape=(nrow, 6 * N))
        return J, rvec

    def _huber_w(self, mag: np.ndarray) -> np.ndarray:
        """Huber IRLS weight on a whitened residual magnitude: 1 for |r|<=delta, delta/|r| beyond."""
        d = self.huber_delta
        return np.where(mag <= d, 1.0, d / np.maximum(mag, 1e-12))

    def solve(self, R_init, t_init, *, prior, odometry, loop, dem_height=None, dem_normal=None,
              iters: int = 60, tol: float = 1e-6, gtol: float = 1e-4) -> SE3Result:
        """Levenberg-Marquardt on the SE(3) manifold. Returns the optimised poses + diagnostics."""
        R = np.array(R_init, float, copy=True)
        t = np.array(t_init, float, copy=True)
        N = R.shape[0]
        dem_height = dem_height or []
        dem_normal = dem_normal or []
        lam = 1e-3
        cost_hist: list[float] = []
        converged = False
        it = 0
        grad_norm = np.inf
        J, r = self._solve_once(R, t, prior, odometry, loop, dem_height, dem_normal, lam)
        cost = 0.5 * float(r @ r)
        cost_hist.append(cost)
        for it in range(1, iters + 1):
            g = J.T @ r
            grad_norm = float(np.max(np.abs(g)))
            H = (J.T @ J).tocsc()
            diag = sp.diags(H.diagonal() + 1e-12)
            accepted = False
            for _ in range(12):                                       # LM inner: grow lambda until decrease
                A = (H + lam * diag).tocsc()
                try:
                    dx = spsolve(A, -g)
                except Exception:
                    lam *= 10.0
                    continue
                dx = np.asarray(dx, float).reshape(N, 6)
                Rn = np.einsum("nij,njk->nik", R, exp_so3(dx[:, :3]))
                tn = t + np.einsum("nij,nj->ni", R, dx[:, 3:])
                Jn, rn = self._solve_once(Rn, tn, prior, odometry, loop, dem_height, dem_normal, lam)
                new_cost = 0.5 * float(rn @ rn)
                if new_cost < cost:
                    R, t, J, r = Rn, tn, Jn, rn
                    rel = (cost - new_cost) / (1.0 + cost)
                    cost = new_cost
                    cost_hist.append(cost)
                    lam = max(lam * 0.5, 1e-9)
                    accepted = True
                    # Converged when the cost has reached a stable minimum (relative decrease below
                    # tol) -- the honest criterion in 6N dimensions, where the raw step L2-norm stays
                    # O(1) even at the optimum and is not a reliable stop. grad_norm is reported too.
                    if rel < tol:
                        converged = True
                    break
                lam = min(lam * 10.0, 1e9)
            if grad_norm < gtol:                                      # stationary point (small gradient)
                converged = True
            if converged or not accepted:                            # accepted=False -> LM could not
                break                                                # reduce cost: a true stall


        # recompute the gradient at the final accepted estimate so the reported norm matches (R, t)
        g_final = J.T @ r
        grad_norm = float(np.max(np.abs(g_final)))

        corr_t = t - np.asarray(t_init, float)
        dR = np.einsum("nji,njk->nik", np.asarray(R_init, float), R)   # R_init^T R
        rot_deg = np.degrees(np.linalg.norm(log_so3(dR), axis=1))
        return SE3Result(
            R=R, t=t, R_initial=np.asarray(R_init, float), t_initial=np.asarray(t_init, float),
            converged=converged, iterations=it, final_cost=cost, grad_norm=grad_norm,
            cost_history=cost_hist,
            mean_abs_horizontal_correction_m=float(np.mean(np.linalg.norm(corr_t[:, :2], axis=1))),
            mean_abs_height_correction_m=float(np.mean(np.abs(corr_t[:, 2]))),
            mean_abs_rotation_correction_deg=float(np.mean(rot_deg)),
        )
