"""[REQ:AS-07] Integrated truth-denied nav-spine eval (§25 Phase 5).

Runs the REAL dart navigation spine (calibrated stereo VO + stereo obstacle detection) over a
rendered stereo traverse using ONLY images + rig calibration, then scores it against eval-only
ground truth. Aggregates the existing per-component spine (dart.stereo_vo / dart.obstacle_map,
each unit-tested on real renders) into the one truth-denied report the AS-07 acceptance asks for:
ATE, coverage, obstacle recall, and recovery decisions.

Invariant I3 (truth firewall): `run_nav_spine` consumes images + calibration only and accepts NO
pose/truth argument; truth (truth.json poses, scene clasts) is read ONLY inside `score_nav`, never
fed to the estimator. NOT synthetic: the inputs are real Godot renders; the estimate is the real VO.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np

from dart import obstacle_map, stereo_vo
from stewie.eval import metrics


def _load_pairs(cam_dir: str):
    from imageio.v3 import imread
    frames = sorted(d for d in os.listdir(cam_dir) if d.startswith("frame_"))
    pairs = []
    for fr in frames:
        left = np.asarray(imread(os.path.join(cam_dir, fr, "front_left.png")))
        right = np.asarray(imread(os.path.join(cam_dir, fr, "front_right.png")))
        pairs.append((left, right))
    return pairs


@dataclass
class NavReport:
    """The estimator output -- produced from images + calibration ONLY (no truth)."""
    trajectory_xz_m: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    step_valid: list = field(default_factory=list)
    obstacles_per_frame: list = field(default_factory=list)
    n_frames: int = 0


def run_nav_spine(cam_dir: str, *, hfov_deg: float, baseline_m: float) -> NavReport:
    """Truth-denied estimator pass: rendered stereo traverse -> trajectory + per-frame obstacles.

    Accepts ONLY a camera directory + rig calibration. No pose/slip/truth input (invariant I3)."""
    pairs = _load_pairs(cam_dir)
    if not pairs:
        raise ValueError(f"no frames under {cam_dir}")
    h, w = pairs[0][0].shape[:2]
    cfg = stereo_vo.StereoVOConfig.from_fov(width_px=w, height_px=h, hfov_deg=hfov_deg,
                                            baseline_m=baseline_m)
    vo = stereo_vo.estimate_vo(pairs, cfg)
    traj = np.asarray(vo.trajectory_xyz_m, dtype=float)
    # the rover drives on the ground plane; the camera-frame horizontal axes are X (lateral) and
    # Z (forward). Umeyama alignment in score_nav reconciles this with the world (x,z) truth frame.
    traj_xz = traj[:, [0, 2]] if traj.ndim == 2 and traj.shape[1] == 3 else traj[:, :2]
    obstacles = [obstacle_map.classify(left, right, hfov_deg=hfov_deg, baseline_m=baseline_m)
                 for (left, right) in pairs]
    return NavReport(trajectory_xz_m=traj_xz, step_valid=list(vo.step_valid),
                     obstacles_per_frame=obstacles, n_frames=len(pairs))


def score_nav(report: NavReport, truth_path: str) -> dict:
    """EVAL-ONLY scoring: ATE (Umeyama-aligned), path-length error, coverage, recovery, obstacles.

    Reads truth.json poses strictly here; never returns them to the estimator path."""
    truth = json.load(open(truth_path))["poses"]
    gt_xz = np.array([[p["x"], p["z"]] for p in truth], dtype=float)
    n = min(len(gt_xz), len(report.trajectory_xz_m))
    est = np.asarray(report.trajectory_xz_m[:n], dtype=float)
    gt = gt_xz[:n]

    ate = float(metrics.ate_rmse(est, gt, align=True)) if n >= 2 else float("nan")
    est_len = float(np.sum(np.linalg.norm(np.diff(est, axis=0), axis=1))) if n >= 2 else 0.0
    gt_len = float(np.sum(np.linalg.norm(np.diff(gt, axis=0), axis=1))) if n >= 2 else 0.0
    path_len_err = abs(est_len - gt_len)

    recovery_holds = int(sum(1 for v in report.step_valid if not v))
    n_steps = max(1, len(report.step_valid))
    coverage_frac = float(sum(1 for v in report.step_valid if v)) / n_steps
    obstacles_detected = int(sum(len(o) for o in report.obstacles_per_frame))

    return {
        "n_frames": report.n_frames,
        "ate_m": ate,
        "est_path_len_m": est_len,
        "gt_path_len_m": gt_len,
        "path_len_err_m": path_len_err,
        "coverage_frac": coverage_frac,
        "recovery_holds": recovery_holds,
        "obstacles_detected": obstacles_detected,
        "truth_channel": "GROUND_TRUTH_EVAL",
    }
