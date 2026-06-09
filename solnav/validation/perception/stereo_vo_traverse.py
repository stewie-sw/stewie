#!/usr/bin/env python3
"""Run stereo-triangulation + PnP visual odometry on the REAL rendered lunar stereo traverse
(frames 000..003, crater_boulders scene, Godot sensor model) and write the VO trajectory PNG.

Calibration is the rig FOV (HFOV 73.99 deg -> fx ~= 254.84 px at 384 px width) and the calibrated
front-stereo baseline 0.07 m, both taken from the sequence.json camera_calibration block (a
perception input, not ground truth).

MATH printed: triangulated-depth band per frame, per-step VO translation magnitudes, and the
recovered total path length compared against the EVAL-only ground-truth traverse length from
truth.json (GROUND_TRUTH_EVAL). Truth is read ONLY in this eval/scoring print, never fed to the
estimator (invariant I3).

  python3 validation/perception/stereo_vo_traverse.py
"""
import json
import os

import numpy as np
from imageio.v3 import imread

from solnav.perception import stereo_vo

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                 # .../solnav (package root dir)
CAM = os.path.join(ROOT, "validation", "a6_traverse", "cam")
SEQUENCE = os.path.join(ROOT, "validation", "a6_traverse", "sequence.json")
# EVAL-ONLY truth (GROUND_TRUTH_EVAL); read only for the scoring print below.
TRUTH = os.path.join(ROOT, "validation", "a6_traverse", "truth", "truth.json")

HFOV_DEG = 73.99
WIDTH, HEIGHT = 384, 288


def _load(frame_dir):
    left = np.asarray(imread(os.path.join(frame_dir, "front_left.png")))
    right = np.asarray(imread(os.path.join(frame_dir, "front_right.png")))
    return left, right


def main() -> None:
    calib = json.load(open(SEQUENCE))["camera_calibration"]      # perception input (not truth)
    baseline = float(calib["baseline_m"])
    cfg = stereo_vo.StereoVOConfig.from_fov(
        width_px=WIDTH, height_px=HEIGHT, hfov_deg=HFOV_DEG, baseline_m=baseline,
    )
    print(f"calibration: fx={cfg.fx_px:.2f}px (HFOV {HFOV_DEG} deg @ {WIDTH}px), baseline={baseline} m, "
          f"reference={calib['reference_camera']}")

    pairs = [_load(os.path.join(CAM, f"frame_{k:03d}")) for k in range(4)]

    for k, (left, right) in enumerate(pairs):
        cloud = stereo_vo.triangulate_stereo(left, right, cfg)
        z = cloud.points_3d[:, 2]
        print(f"frame {k}: 3D points={len(z):4d}  depth median={np.median(z):6.3f} m  "
              f"[{z.min():.3f}, {z.max():.3f}] m  all_positive={bool(np.all(z > 0))}")

    result = stereo_vo.estimate_vo(pairs, cfg)
    steps = np.linalg.norm(result.relative_translations_m, axis=1)
    recovered = float(steps.sum())
    print(f"\nVO inter-frame |t| (m): {steps.round(3).tolist()}  inliers={result.pnp_inliers}")
    print(f"VO recovered path length: {recovered:.3f} m  (step CoV={np.std(steps)/np.mean(steps):.3f})")

    if os.path.exists(TRUTH):
        poses = json.load(open(TRUTH))["poses"]                  # EVAL ONLY (I3)
        xz = np.array([[p["x"], p["z"]] for p in poses], dtype=float)
        truth_len = float(np.sum(np.linalg.norm(np.diff(xz, axis=0), axis=1)))
        err = abs(recovered - truth_len) / truth_len
        print(f"EVAL: ground-truth traverse length={truth_len:.3f} m  scale error={err*100:.1f}%")

    out = os.path.join(HERE, "stereo_vo_trajectory.png")
    stereo_vo.save_trajectory_plot(result, out)
    print(f"\nwrote trajectory plot: {out}")


if __name__ == "__main__":
    main()
