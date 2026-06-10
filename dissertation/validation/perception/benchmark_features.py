#!/usr/bin/env python3
"""Benchmark the unified feature front end (CLASSICAL cv2 ORB/SIFT vs LEARNED kornia DISK+LightGlue)
on the REAL rendered lunar stereo pair and write a side-by-side match visualization PNG.

Real inputs only: the rendered Godot stereo frame at
validation/a6_traverse/cam/frame_000/{front_left,front_right}.png (crater_boulders scene). The clast
ground truth is read ONLY for the EVAL-path difficulty annotation (invariant I3) and never reaches
the matcher.

  python3 validation/perception/benchmark_features.py
"""
import os

import numpy as np
from imageio.v3 import imread

from dart import features

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # .../solnav (package root dir)
FRAME = os.path.join(ROOT, "validation", "a6_traverse", "cam", "frame_000")
# EVAL-ONLY truth (scene difficulty annotation; never fed to the matcher).
CLAST_TRUTH = "/mnt/projects/foss_ipex/dustgym/samples/crater_boulders/metadata.json"


def main() -> None:
    left = np.asarray(imread(os.path.join(FRAME, "front_left.png")))
    right = np.asarray(imread(os.path.join(FRAME, "front_right.png")))

    results = features.benchmark_all(left, right)

    header = (f"{'method':<16}{'kpL':>6}{'kpR':>6}{'raw':>6}{'inl':>6}"
              f"{'ratio':>8}{'sampson_px':>12}{'ms':>8}")
    print("REAL rendered lunar stereo (frame_000, crater_boulders, 384x288 Godot sensor model)")
    print(header)
    for r in results:
        print(f"{r.method:<16}{r.n_keypoints_left:>6}{r.n_keypoints_right:>6}"
              f"{r.n_raw_matches:>6}{r.n_inliers:>6}{r.inlier_ratio:>8.3f}"
              f"{r.median_sampson_px:>12.3f}{r.runtime_s * 1e3:>8.0f}")

    good = [r for r in results
            if 0.0 <= r.inlier_ratio <= 1.0 and r.inlier_ratio > 0.3 and r.median_sampson_px < 3.0]
    print(f"\nMATH: cleared inlier/epipolar floor: {[r.method for r in good]}")

    if os.path.exists(CLAST_TRUTH):
        print(f"EVAL-only scene difficulty: {features.count_clasts_in_truth(CLAST_TRUTH)} clasts")

    out = os.path.join(HERE, "feature_matches_real_stereo.png")
    _save_panel(left, right, results, out)
    print(f"\nwrote visualization: {out}")


def _save_panel(left, right, results, out_path):
    """One PNG, one row per method, drawing each method's RANSAC inliers on the side-by-side pair."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    gl, gr = features.to_gray_u8(left), features.to_gray_u8(right)
    off = gl.shape[1]
    canvas = np.concatenate([gl, gr], axis=1)

    fig, axes = plt.subplots(len(results), 1, figsize=(11, 3.6 * len(results)))
    if len(results) == 1:
        axes = [axes]
    for ax, r in zip(axes, results):
        ax.imshow(canvas, cmap="gray", vmin=0, vmax=255)
        p1, p2 = r.points_left, r.points_right
        n = min(len(p1), 80)
        if n:
            sel = np.linspace(0, len(p1) - 1, n).astype(int)   # deterministic even subsample of REAL matches
            for i in sel:
                x1, y1 = p1[i]; x2, y2 = p2[i]
                ax.plot([x1, x2 + off], [y1, y2], "-", color="lime", linewidth=0.5, alpha=0.7)
                ax.plot([x1], [y1], ".", color="red", markersize=2)
                ax.plot([x2 + off], [y2], ".", color="yellow", markersize=2)
        kind = "LEARNED" if r.method == "disk_lightglue" else "CLASSICAL"
        ax.set_title(
            f"[{kind}] {r.method}: kp L/R={r.n_keypoints_left}/{r.n_keypoints_right}  "
            f"raw={r.n_raw_matches}  inliers={r.n_inliers} (ratio={r.inlier_ratio:.2f})  "
            f"median Sampson={r.median_sampson_px:.2f}px  t={r.runtime_s * 1e3:.0f}ms",
            fontsize=9)
        ax.axis("off")
    fig.suptitle("Unified feature front end on REAL rendered lunar stereo "
                 "(left|right, lines = RANSAC-fundamental inliers)", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
