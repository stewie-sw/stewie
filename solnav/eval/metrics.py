"""Trajectory metrics for navigation validation (see METRICS.md).

Standard, gauge-aware definitions:
  ate_rmse           : ABSOLUTE trajectory error after a rigid SE(2) (Umeyama) alignment
  ate_rmse_raw       : same-frame XY RMSE (no alignment) -- only when frames are already common
  rpe_rmse           : RELATIVE pose error from composed SE(2) transforms (gauge-invariant)
  heading_error_deg  : mean absolute heading error (deg)
  final_position_error : end-of-run position error (m, after alignment)

ATE is alignment-invariant (a global rotation/translation gives ~0); RPE is invariant to
any global gauge. Both verified by gauge-invariance tests.
"""
from __future__ import annotations

import numpy as np


def _wrap(a):
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


def _check_pair(est, gt, min_len=1):
    e = np.asarray(est, float); g = np.asarray(gt, float)
    if e.ndim != 2 or g.ndim != 2:
        raise ValueError("trajectories must be 2-D arrays (N, >=2)")
    if len(e) != len(g):
        raise ValueError(f"length mismatch: est {len(e)} vs gt {len(g)}")
    if len(e) < min_len:
        raise ValueError(f"need at least {min_len} poses (got {len(e)})")
    return e, g


def umeyama_align_2d(src_xy: np.ndarray, dst_xy: np.ndarray, with_scale: bool = False):
    """Rigid (optionally similarity) SE(2) alignment of src onto dst (Umeyama 1991).
    Returns (R 2x2, t 2, s). Maps src -> s R src + t."""
    src = np.asarray(src_xy, float)[:, :2]; dst = np.asarray(dst_xy, float)[:, :2]
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S = src - mu_s; D = dst - mu_d
    H = S.T @ D / len(src)
    U, sig, Vt = np.linalg.svd(H)
    Rm = (Vt.T @ U.T)
    if np.linalg.det(Rm) < 0:                  # reflection guard
        Vt[-1] *= -1; Rm = Vt.T @ U.T
    s = (sig.sum() / (S * S).sum() * len(src)) if with_scale else 1.0
    t = mu_d - s * Rm @ mu_s
    return Rm, t, s


def _apply(R, t, s, xy):
    return (s * (R @ np.asarray(xy, float)[:, :2].T).T) + t


def ate_rmse(est_xy: np.ndarray, gt_xy: np.ndarray, align: bool = True) -> float:
    """Absolute trajectory error (position RMSE). With align=True (default) a rigid SE(2)
    Umeyama alignment is applied first, so a global gauge difference scores ~0."""
    est, gt = _check_pair(est_xy, gt_xy, min_len=2 if align else 1)
    est = est[:, :2]; gt = gt[:, :2]
    if align:
        R, t, s = umeyama_align_2d(est, gt)
        est = _apply(R, t, s, est)
    e = est - gt
    return float(np.sqrt(np.mean(np.sum(e * e, axis=1))))


def ate_rmse_raw(est_xy: np.ndarray, gt_xy: np.ndarray) -> float:
    """Same-frame XY RMSE with no alignment (use only when frames are already common)."""
    return ate_rmse(est_xy, gt_xy, align=False)


def final_position_error(est_xy: np.ndarray, gt_xy: np.ndarray, align: bool = True) -> float:
    est = np.asarray(est_xy, float)[:, :2]; gt = np.asarray(gt_xy, float)[:, :2]
    if align:
        R, t, s = umeyama_align_2d(est, gt); est = _apply(R, t, s, est)
    return float(np.linalg.norm(est[-1] - gt[-1]))


def _T(p):
    c, s = np.cos(p[2]), np.sin(p[2])
    return np.array([[c, -s, p[0]], [s, c, p[1]], [0, 0, 1.0]])


def _inv(T):
    R = T[:2, :2]; t = T[:2, 2]
    Ti = np.eye(3); Ti[:2, :2] = R.T; Ti[:2, 2] = -R.T @ t
    return Ti


def rpe_rmse(est_poses: np.ndarray, gt_poses: np.ndarray, delta: int = 1) -> float:
    """RMS translation of the relative-pose error E_i = (T_gt_i^-1 T_gt_{i+d})^-1 (T_est_i^-1 T_est_{i+d}).
    Gauge-invariant: any global SE(2) on est or gt leaves it unchanged."""
    est, gt = _check_pair(est_poses, gt_poses, min_len=2)
    if delta < 1 or delta >= len(est):
        raise ValueError(f"delta must be in [1, len-1]; got {delta} for length {len(est)}")
    errs = []
    for i in range(len(est) - delta):
        rel_gt = _inv(_T(gt[i])) @ _T(gt[i + delta])
        rel_est = _inv(_T(est[i])) @ _T(est[i + delta])
        E = _inv(rel_gt) @ rel_est
        errs.append(np.linalg.norm(E[:2, 2]))
    return float(np.sqrt(np.mean(np.square(errs)))) if errs else 0.0


def heading_error_deg(est_theta: np.ndarray, gt_theta: np.ndarray) -> float:
    """Mean absolute heading error in degrees (gauge-relative differences should be used
    for cross-frame trajectories; this is the raw per-pose heading error)."""
    d = _wrap(np.asarray(est_theta) - np.asarray(gt_theta))
    return float(np.degrees(np.mean(np.abs(d))))
