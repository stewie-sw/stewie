"""Trajectory metrics for navigation validation (see METRICS.md).

Real definitions, no fabricated values:
  ate_rmse           : absolute trajectory error (position RMSE) after frames are aligned
  rpe_rmse           : relative pose error over a step horizon (drift)
  heading_error_deg  : mean absolute heading error (deg)
  final_position_error : end-of-run position error (m)
"""
from __future__ import annotations

import numpy as np


def _wrap(a):
    return (np.asarray(a) + np.pi) % (2 * np.pi) - np.pi


def ate_rmse(est_xy: np.ndarray, gt_xy: np.ndarray) -> float:
    """Position RMSE between estimated and ground-truth xy (same frame, same length)."""
    e = np.asarray(est_xy)[:, :2] - np.asarray(gt_xy)[:, :2]
    return float(np.sqrt(np.mean(np.sum(e * e, axis=1))))


def final_position_error(est_xy: np.ndarray, gt_xy: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(est_xy)[-1, :2] - np.asarray(gt_xy)[-1, :2]))


def rpe_rmse(est_poses: np.ndarray, gt_poses: np.ndarray, delta: int = 1) -> float:
    """RMS of the position part of the relative-pose error over a step horizon delta."""
    est = np.asarray(est_poses); gt = np.asarray(gt_poses)
    errs = []
    for i in range(len(est) - delta):
        de = est[i + delta, :2] - est[i, :2]
        dg = gt[i + delta, :2] - gt[i, :2]
        errs.append(np.linalg.norm(de - dg))
    return float(np.sqrt(np.mean(np.square(errs)))) if errs else 0.0


def heading_error_deg(est_theta: np.ndarray, gt_theta: np.ndarray) -> float:
    """Mean absolute heading error in degrees."""
    d = _wrap(np.asarray(est_theta) - np.asarray(gt_theta))
    return float(np.degrees(np.mean(np.abs(d))))
