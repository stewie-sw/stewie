"""IMU-augmented SE(3) pose graph: the B3.1 estimator that carries velocity + gyro/accel bias states
and consumes the manifold IMU preintegration factor (dart.imu_preintegration).

This is the state-block extension of dart.se3_pose_graph.SE3PoseGraph. It reuses that module's validated
SO(3) exp/log and its design (right-perturbation retraction, finite-difference-in-retraction Jacobians,
sparse Levenberg-Marquardt, Huber IRLS) unchanged; what is new is the per-keyframe state:

    x_i = ( R_i in SO(3),  p_i in R^3,  v_i in R^3,  b_g_i in R^3,  b_a_i in R^3 )      (15 DOF)

with tangent [ dphi(3), dp(3), dv(3), dbg(3), dba(3) ] and retraction
    R_i <- R_i Exp(dphi),   p_i <- p_i + dp,   v_i <- v_i + dv,   b_g <- b_g + dbg,   b_a <- b_a + dba.
Only the rotation is on-manifold; p, v, biases are Euclidean (the standard VIO / Forster parameterization).

Factors:
  * PriorImuEdge   full-state prior on keyframe 0 (gauge fix + velocity/bias anchoring).
  * ImuEdge        the 9-DOF preintegration residual (dart.imu_preintegration.PreintegratedImu.residual),
                   whitened by the preintegrated 9x9 covariance (Cholesky information whitener).
  * BiasRWEdge     the 6-DOF gyro/accel bias random-walk between consecutive keyframes.
  * WheelEdge      a 3-DOF relative-translation factor r = R_i^T (p_j - p_i) - t_meas carrying the real
                   wheel-drive displacement (the metric-scale constraint; the IMU owns rotation).

Landmark states are DEFERRED (a separate structural change; not implemented here).

TRUTH FIREWALL (I3/I7): every factor is a function of the IMU stream, the wheel displacement, and the
declared prior only. No ground truth enters. The estimate is frozen before RTK is read at scoring.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Reference: Forster et al. IEEE T-RO 2017.
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from dart.imu_preintegration import GRAVITY, PreintegratedImu, exp_so3_vec, log_so3
from dart.se3_pose_graph import exp_so3

NODE_DOF = 15
_EPS = 1e-6


# ------------------------------------------------------------------------------------------- edges
@dataclass(frozen=True)
class PriorImuEdge:
    node: int
    R_meas: np.ndarray
    p_meas: np.ndarray
    v_meas: np.ndarray
    bg_meas: np.ndarray
    ba_meas: np.ndarray
    sig_rot: float
    sig_p: float
    sig_v: float
    sig_bg: float
    sig_ba: float


@dataclass(frozen=True)
class ImuEdge:
    a: int
    b: int
    pim: PreintegratedImu


@dataclass(frozen=True)
class BiasRWEdge:
    a: int
    b: int
    sig_bg: float
    sig_ba: float


@dataclass(frozen=True)
class WheelEdge:
    a: int
    b: int
    t_meas: np.ndarray
    sig_trans: float
    robust: bool = False


@dataclass
class ImuResult:
    R: np.ndarray
    p: np.ndarray
    v: np.ndarray
    bg: np.ndarray
    ba: np.ndarray
    converged: bool
    iterations: int
    final_cost: float
    grad_norm: float
    cost_history: list = field(default_factory=list)


# ----------------------------------------------------------------------------- vectorised IMU residual
def _imu_res_batch(Ri, pi, vi, bgi, bai, Rj, pj, vj, S, g):
    """Batched 9-DOF IMU residual over E edges. S is a dict of stacked measurement arrays."""
    dbg = bgi - S["bias_g"]                                   # (E,3)
    dba = bai - S["bias_a"]
    corr = exp_batch(np.einsum("eij,ej->ei", S["JRbg"], dbg))  # (E,3,3)
    dR_c = np.einsum("eij,ejk->eik", S["dR"], corr)
    dV_c = S["dV"] + np.einsum("eij,ej->ei", S["JVbg"], dbg) + np.einsum("eij,ej->ei", S["JVba"], dba)
    dP_c = S["dP"] + np.einsum("eij,ej->ei", S["JPbg"], dbg) + np.einsum("eij,ej->ei", S["JPba"], dba)
    DT = S["DT"]                                              # (E,)
    gDT = DT[:, None] * g[None, :]                            # (E,3)
    # r_R = Log( dR_c^T Ri^T Rj )
    M = np.einsum("eji,ejk->eik", dR_c, np.einsum("eji,ejk->eik", Ri, Rj))
    r_R = log_so3(M)
    r_v = np.einsum("eji,ej->ei", Ri, vj - vi - gDT) - dV_c
    r_p = np.einsum("eji,ej->ei", Ri, pj - pi - vi * DT[:, None] - 0.5 * gDT * DT[:, None]) - dP_c
    return np.concatenate([r_R, r_v, r_p], axis=1)            # (E,9)


def exp_batch(phi):
    """Batched SO(3) exp (E,3) -> (E,3,3) using the single-vector exp (small angles here)."""
    return np.stack([exp_so3_vec(phi[e]) for e in range(phi.shape[0])]) if phi.shape[0] else \
        np.zeros((0, 3, 3))


class ImuSe3PoseGraph:
    """Sparse on-manifold LM over 15-DOF IMU keyframe states. Finite-difference-in-retraction Jacobians
    (the same choice as SE3PoseGraph): each block is the exact first-order map of the step taken."""

    def __init__(self, *, huber_delta: float = 1.345, gravity=GRAVITY) -> None:
        self.huber_delta = float(huber_delta)
        self.g = np.asarray(gravity, float)

    # ---- precompute stacked IMU measurement arrays + covariance whiteners (state-independent) ----
    @staticmethod
    def _imu_stacks(imu_edges):
        E = len(imu_edges)
        S = {k: np.zeros((E, 3, 3)) for k in ("dR", "JRbg", "JVbg", "JVba", "JPbg", "JPba")}
        for k in ("dV", "dP", "bias_g", "bias_a"):
            S[k] = np.zeros((E, 3))
        S["DT"] = np.zeros(E)
        W = np.zeros((E, 9, 9))
        for e, ed in enumerate(imu_edges):
            m = ed.pim
            S["dR"][e] = m.dR; S["dV"][e] = m.dV; S["dP"][e] = m.dP; S["DT"][e] = m.dt
            S["JRbg"][e] = m.dR_dbg; S["JVbg"][e] = m.dV_dbg; S["JVba"][e] = m.dV_dba
            S["JPbg"][e] = m.dP_dbg; S["JPba"][e] = m.dP_dba
            S["bias_g"][e] = m.bias_g; S["bias_a"][e] = m.bias_a
            info = np.linalg.inv(m.cov + 1e-12 * np.eye(9))
            info = 0.5 * (info + info.T)
            L = np.linalg.cholesky(info)                       # L L^T = info
            W[e] = L.T                                          # whitened r = W r  -> ||.||^2 = r^T info r
        S["a"] = np.fromiter((ed.a for ed in imu_edges), int, E)
        S["b"] = np.fromiter((ed.b for ed in imu_edges), int, E)
        S["W"] = W
        return S

    def _huber_w(self, mag):
        d = self.huber_delta
        return np.where(mag <= d, 1.0, d / np.maximum(mag, 1e-12))

    def _linearize_imu(self, R, p, v, bg, ba, S, rows0):
        E = S["a"].shape[0]
        if E == 0:
            return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0), 0
        a, b = S["a"], S["b"]
        Ra, pa, va, bga, baa = R[a], p[a], v[a], bg[a], ba[a]
        Rb, pb, vb = R[b], p[b], v[b]
        g = self.g
        r0 = _imu_res_batch(Ra, pa, va, bga, baa, Rb, pb, vb, S, g)   # (E,9) unwhitened
        W = S["W"]
        rw0 = np.einsum("eij,ej->ei", W, r0)                          # (E,9) whitened
        blk = np.zeros((E, 9, 30))
        e3 = np.eye(3)
        # node a perturbations (cols 0..14)
        for k in range(3):
            Rap = np.einsum("eij,ejk->eik", Ra, exp_batch(np.broadcast_to(_EPS * e3[k], (E, 3))))
            blk[:, :, k] = _imu_res_batch(Rap, pa, va, bga, baa, Rb, pb, vb, S, g) - r0
        for k in range(3):
            pap = pa + _EPS * e3[k]
            blk[:, :, 3 + k] = _imu_res_batch(Ra, pap, va, bga, baa, Rb, pb, vb, S, g) - r0
        for k in range(3):
            vap = va + _EPS * e3[k]
            blk[:, :, 6 + k] = _imu_res_batch(Ra, pa, vap, bga, baa, Rb, pb, vb, S, g) - r0
        for k in range(3):
            bgap = bga + _EPS * e3[k]
            blk[:, :, 9 + k] = _imu_res_batch(Ra, pa, va, bgap, baa, Rb, pb, vb, S, g) - r0
        for k in range(3):
            baap = baa + _EPS * e3[k]
            blk[:, :, 12 + k] = _imu_res_batch(Ra, pa, va, bga, baap, Rb, pb, vb, S, g) - r0
        # node b perturbations (cols 15..29); bg_b/ba_b do not enter -> stay ~0
        for k in range(3):
            Rbp = np.einsum("eij,ejk->eik", Rb, exp_batch(np.broadcast_to(_EPS * e3[k], (E, 3))))
            blk[:, :, 15 + k] = _imu_res_batch(Ra, pa, va, bga, baa, Rbp, pb, vb, S, g) - r0
        for k in range(3):
            pbp = pb + _EPS * e3[k]
            blk[:, :, 18 + k] = _imu_res_batch(Ra, pa, va, bga, baa, Rb, pbp, vb, S, g) - r0
        for k in range(3):
            vbp = vb + _EPS * e3[k]
            blk[:, :, 21 + k] = _imu_res_batch(Ra, pa, va, bga, baa, Rb, pb, vbp, S, g) - r0
        blk /= _EPS
        blk = np.einsum("eij,ejc->eic", W, blk)                       # whiten Jacobian rows
        cols_node = np.concatenate([15 * a[:, None] + np.arange(15)[None, :],
                                    15 * b[:, None] + np.arange(15)[None, :]], axis=1)  # (E,30)
        row_base = rows0 + 9 * np.arange(E)
        rows = np.repeat(row_base[:, None, None] + np.arange(9)[None, :, None], 30, axis=2)
        cols = np.repeat(cols_node[:, None, :], 9, axis=1)
        return rows.reshape(-1), cols.reshape(-1), blk.reshape(-1), rw0.reshape(-1), 9 * E

    def _build(self, R, p, v, bg, ba, prior, S, bias_rw, wheel):
        N = R.shape[0]
        ROWS, COLS, DATA, RVEC = [], [], [], []
        nrow = 0

        # prior (node 0, 15 rows)
        e = prior; n = e.node
        r_R = log_so3((np.asarray(e.R_meas).T @ R[n])[None])[0]
        res = np.concatenate([r_R, p[n] - e.p_meas, v[n] - e.v_meas, bg[n] - e.bg_meas, ba[n] - e.ba_meas])
        sc = np.array([1 / e.sig_rot] * 3 + [1 / e.sig_p] * 3 + [1 / e.sig_v] * 3
                      + [1 / e.sig_bg] * 3 + [1 / e.sig_ba] * 3)
        Jp = np.zeros((15, 15))
        e3 = np.eye(3)
        for k in range(3):                                            # rotation block by FD
            Rp = R[n] @ exp_so3(_EPS * e3[k])
            Jp[:3, k] = (log_so3((np.asarray(e.R_meas).T @ Rp)[None])[0] - r_R) / _EPS
        for k in range(12):                                           # p,v,bg,ba identity
            Jp[3 + k, 3 + k] = 1.0
        Jp *= sc[:, None]; res = res * sc
        rr, cc = np.nonzero(Jp)
        ROWS.append(nrow + rr); COLS.append(15 * n + cc); DATA.append(Jp[rr, cc])
        RVEC.append(res); nrow += 15

        # IMU factor
        r, c, d, rv, nn = self._linearize_imu(R, p, v, bg, ba, S, nrow)
        if nn:
            ROWS.append(r); COLS.append(c); DATA.append(d); RVEC.append(rv); nrow += nn

        # bias random walk (6 rows/edge, linear -> analytic +-I)
        for ed in bias_rw:
            res_bg = bg[ed.b] - bg[ed.a]; res_ba = ba[ed.b] - ba[ed.a]
            sbg = 1 / ed.sig_bg; sba = 1 / ed.sig_ba
            for k in range(3):
                ROWS += [nrow + k, nrow + k]; COLS += [15 * ed.a + 9 + k, 15 * ed.b + 9 + k]
                DATA += [-sbg, sbg]; RVEC.append(np.array([res_bg[k] * sbg]))
            for k in range(3):
                ROWS += [nrow + 3 + k, nrow + 3 + k]; COLS += [15 * ed.a + 12 + k, 15 * ed.b + 12 + k]
                DATA += [-sba, sba]; RVEC.append(np.array([res_ba[k] * sba]))
            nrow += 6

        # wheel relative-translation (3 rows/edge): r = Ra^T (pb - pa) - t_meas
        if wheel:
            aw = np.fromiter((e.a for e in wheel), int, len(wheel))
            bw = np.fromiter((e.b for e in wheel), int, len(wheel))
            tz = np.stack([np.asarray(e.t_meas, float) for e in wheel])
            sct = np.array([1 / e.sig_trans for e in wheel])
            Ra, pa, pb = R[aw], p[aw], p[bw]
            r0 = np.einsum("eji,ej->ei", Ra, pb - pa) - tz                # (Ew,3)
            if any(e.robust for e in wheel):
                w = self._huber_w(np.linalg.norm(r0 * sct[:, None], axis=1))
            else:
                w = np.ones(len(wheel))
            scl = (sct * np.sqrt(w))[:, None]
            Ew = len(wheel); blk = np.zeros((Ew, 3, 9))
            e3 = np.eye(3)
            for k in range(3):                                            # phi_a (via Ra)
                Rap = np.einsum("eij,ejk->eik", Ra, exp_batch(np.broadcast_to(_EPS * e3[k], (Ew, 3))))
                blk[:, :, k] = (np.einsum("eji,ej->ei", Rap, pb - pa) - tz - r0) / _EPS
            for k in range(3):                                            # p_a
                blk[:, :, 3 + k] = (np.einsum("eji,ej->ei", Ra, (pb - (pa + _EPS * e3[k]))) - tz - r0) / _EPS
            for k in range(3):                                            # p_b
                blk[:, :, 6 + k] = (np.einsum("eji,ej->ei", Ra, ((pb + _EPS * e3[k]) - pa)) - tz - r0) / _EPS
            blk *= scl[:, :, None]; rvec = (r0 * scl).reshape(-1)
            cols_node = np.concatenate([15 * aw[:, None] + np.arange(3)[None, :],           # phi_a
                                        15 * aw[:, None] + 3 + np.arange(3)[None, :],        # p_a
                                        15 * bw[:, None] + 3 + np.arange(3)[None, :]], axis=1)  # p_b
            row_base = nrow + 3 * np.arange(Ew)
            rows = np.repeat(row_base[:, None, None] + np.arange(3)[None, :, None], 9, axis=2)
            cols = np.repeat(cols_node[:, None, :], 3, axis=1)
            ROWS.append(rows.reshape(-1)); COLS.append(cols.reshape(-1)); DATA.append(blk.reshape(-1))
            RVEC.append(rvec); nrow += 3 * Ew

        rows = np.concatenate([np.atleast_1d(np.asarray(x)).reshape(-1) for x in ROWS])
        cols = np.concatenate([np.atleast_1d(np.asarray(x)).reshape(-1) for x in COLS])
        data = np.concatenate([np.atleast_1d(np.asarray(x, float)).reshape(-1) for x in DATA])
        rvec = np.concatenate([np.atleast_1d(np.asarray(x, float)).reshape(-1) for x in RVEC])
        J = sp.csr_matrix((data, (rows, cols)), shape=(nrow, NODE_DOF * N))
        return J, rvec

    def solve(self, R0, p0, v0, bg0, ba0, *, prior, imu_edges, bias_rw=(), wheel=(),
              iters: int = 50, tol: float = 1e-7, gtol: float = 1e-5) -> ImuResult:
        R = np.array(R0, float, copy=True); p = np.array(p0, float, copy=True)
        v = np.array(v0, float, copy=True); bg = np.array(bg0, float, copy=True)
        ba = np.array(ba0, float, copy=True)
        N = R.shape[0]
        S = self._imu_stacks(list(imu_edges))
        bias_rw = list(bias_rw); wheel = list(wheel)
        lam = 1e-3; cost_hist = []; converged = False; it = 0; grad_norm = np.inf
        J, r = self._build(R, p, v, bg, ba, prior, S, bias_rw, wheel)
        cost = 0.5 * float(r @ r); cost_hist.append(cost)
        for it in range(1, iters + 1):
            g = J.T @ r
            grad_norm = float(np.max(np.abs(g)))
            H = (J.T @ J).tocsc()
            diag = sp.diags(H.diagonal() + 1e-12)
            accepted = False
            for _ in range(12):
                A = (H + lam * diag).tocsc()
                try:
                    dx = spsolve(A, -g)
                except Exception:
                    lam *= 10.0; continue
                dx = np.asarray(dx, float).reshape(N, NODE_DOF)
                Rn = np.einsum("nij,njk->nik", R, np.stack([exp_so3(dx[i, :3]) for i in range(N)]))
                pn = p + dx[:, 3:6]; vn = v + dx[:, 6:9]; bgn = bg + dx[:, 9:12]; ban = ba + dx[:, 12:15]
                Jn, rn = self._build(Rn, pn, vn, bgn, ban, prior, S, bias_rw, wheel)
                new_cost = 0.5 * float(rn @ rn)
                if new_cost < cost:
                    R, p, v, bg, ba, J, r = Rn, pn, vn, bgn, ban, Jn, rn
                    rel = (cost - new_cost) / (1.0 + cost); cost = new_cost; cost_hist.append(cost)
                    lam = max(lam * 0.5, 1e-9); accepted = True
                    if rel < tol:
                        converged = True
                    break
                lam = min(lam * 10.0, 1e9)
            if grad_norm < gtol:
                converged = True
            if converged or not accepted:
                break
        g_final = J.T @ r; grad_norm = float(np.max(np.abs(g_final)))
        return ImuResult(R=R, p=p, v=v, bg=bg, ba=ba, converged=converged, iterations=it,
                         final_cost=cost, grad_norm=grad_norm, cost_history=cost_hist)

    def information_matrix(self, R, p, v, bg, ba, *, prior, imu_edges, bias_rw=(), wheel=()):
        """J^T J at the given state (the Fisher information for the observability named exit)."""
        S = self._imu_stacks(list(imu_edges))
        J, _r = self._build(R, p, v, bg, ba, prior, S, list(bias_rw), list(wheel))
        info = (J.T @ J).toarray()
        return 0.5 * (info + info.T)
