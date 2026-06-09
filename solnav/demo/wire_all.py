#!/usr/bin/env python3
"""Wire the cues into the pose graph and study how far the distance offset (ATE) can drop.

[MEASUREMENT_MODEL_SIM] The baseline is the CANONICAL, hash-locked G1 sub-baseline read from
`validation/g1_capture/` (passive wheel+IMU dead reckoning = 4.632 m raw same-frame / 2.015 m
aligned 2-D ATE over 87.74 m on the real LOLA Haworth DEM with real dustgym slip). The
heading/landmark cues added on top are a SIMULATED_SENSOR model: truth + seeded Gaussian noise,
weighted info=1/sigma^2 (NOT image-derived; this is an estimator/observation-geometry study, not
sensed SLAM). Reports BOTH the same-frame absolute 2-D RMSE (the known-map localization headline,
HIGH-07) and the Umeyama aligned ATE (gauge-free trajectory shape). The 8-camera rig reports
landmark coverage per station. Not a "full SLAM" result and not directly comparable to NavLab.
"""
import csv
import json
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solnav.eval import metrics
from solnav.perception import camera_rig as cr
from solnav.slam import posegraph as pg

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # projects/solnav/solnav
CAP = os.path.join(REPO, "validation", "g1_capture")
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
DT, IMU_HZ, WHEEL_HZ = 2.0, 100.0, 10.0
N_IMU, N_WHEEL = int(IMU_HZ * DT), int(WHEEL_HZ * DT)


def _col(path, col):
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(float(row[col]))
    return np.array(out)


def load_canonical():
    """Read the locked G1 capture (truth.csv + the passive wheel+IMU dead reckoning).

    This is the SAME baseline `validation/g1_capture.py` records (4.632 m raw / 2.015 m aligned over
    87.74 m); anchoring the cue-wiring study on it keeps every deck number consistent rather than
    re-deriving a near-but-different odometry baseline.
    """
    xs, ys, yaws = [], [], []
    with open(os.path.join(CAP, "truth.csv"), newline="") as f:
        for row in csv.DictReader(f):
            xs.append(float(row["x"])); ys.append(float(row["y"])); yaws.append(float(row["yaw"]))
    true = np.column_stack([xs, ys, yaws])
    n_steps = len(true) - 1
    gyro = _col(os.path.join(CAP, "imu.csv"), "gyro_z").reshape(n_steps, N_IMU).mean(axis=1)
    v = _col(os.path.join(CAP, "wheel_odom.csv"), "v").reshape(n_steps, N_WHEEL).mean(axis=1)
    dr = [true[0].copy()]; yaw = float(true[0, 2])
    for k in range(n_steps):
        yaw = yaw + gyro[k] * DT
        dr.append([dr[-1][0] + v[k] * DT * np.cos(yaw),
                   dr[-1][1] + v[k] * DT * np.sin(yaw), yaw])
    return true, np.array(dr)


def main():
    true, dr = load_canonical()
    odo = pg.relative_odometry(dr)
    cx, cy = true[:,0].mean(), true[:,1].mean()
    # six distributed landmarks (good multipoint geometry)
    K = 6
    lm = [np.array([cx + 45*np.cos(t), cy + 45*np.sin(t)]) for t in np.linspace(0, 2*np.pi, K, endpoint=False)]
    rig = cr.CameraRig()

    SB, SH = np.radians(0.5), np.radians(1.0)   # [SIM sensor model] bearing/heading 1-sigma

    def build(solar, n_lm, every):
        rng = np.random.default_rng(0)          # seeded -> reproducible, comparable across stages
        g = pg.PoseGraph(); g.add_prior(0, true[0])
        for i, z in enumerate(odo):
            g.add_odom(i, i+1, z)
        if solar:
            for i in range(0, len(true), 5):
                g.add_heading(i, true[i,2] + rng.normal(0, SH), info=1.0/SH**2)
        for i in range(0, len(true), every):
            for L in lm[:n_lm]:
                b = np.arctan2(L[1]-true[i,1], L[0]-true[i,0]) - true[i,2] + rng.normal(0, SB)
                g.add_landmark(i, L, b, info=1.0/SB**2)
        return g.solve(np.array(dr))

    stages = [
        ("wheel+IMU dead reckoning", build(False, 0, 999)),
        ("+ solar heading", build(True, 0, 999)),
        ("+ 1 landmark", build(True, 1, 8)),
        ("+ 6 landmarks (multipoint)", build(True, 6, 8)),
        ("+ 6 lm, dense (every pose)", build(True, 6, 1)),
    ]
    ates_raw = [(name, round(metrics.ate_rmse_raw(X, true), 3)) for name, X in stages]
    ates_aln = [(name, round(metrics.ate_rmse(X, true), 3)) for name, X in stages]
    # 8-camera coverage of landmarks per station (rig wired in)
    seen_counts = []
    for i in range(0, len(true), 8):
        for L in lm:
            wb = np.degrees(np.arctan2(L[1]-true[i,1], L[0]-true[i,0]))
            d = np.linalg.norm(L - true[i,:2])
            seen_counts.append(len(rig.cameras_seeing(wb, np.degrees(true[i,2]), d)))
    res = {
        "provenance": "MEASUREMENT_MODEL_SIM (SIMULATED_SENSOR: seeded bearing/heading noise, info=1/sigma^2)",
        "metric_note": "ate_raw_same_frame = absolute 2-D RMSE (known-map localization headline); "
                       "ate_aligned = Umeyama gauge-free companion (trajectory shape only)",
        "ate_raw_same_frame_m": dict(ates_raw),
        "ate_aligned_m": dict(ates_aln),
        "reduction_x_raw": round(ates_raw[0][1] / max(ates_raw[-1][1], 1e-6), 1),
        "mean_cameras_seeing_a_landmark": round(float(np.mean(seen_counts)), 2),
    }
    ates = ates_raw   # figures use the same-frame (absolute) numbers
    json.dump(res, open(os.path.join(OUT, "wire_all_metrics.json"), "w"), indent=2)
    for k, v in res.items():
        print(f"  {k}: {v}")

    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    names = [n for n, _ in ates]; vals = [a for _, a in ates]
    ax[0].barh(range(len(names)), vals, color="#005587"); ax[0].set_yticks(range(len(names)))
    ax[0].set_yticklabels(names, fontsize=9); ax[0].invert_yaxis()
    ax[0].set_xlabel("ATE distance offset (m)"); ax[0].set_title("Minimizing distance offset by wiring in cues")
    for i, v in enumerate(vals):
        ax[0].text(v, i, f" {v} m", va="center", fontsize=9)
    best = stages[-1][1]
    ax[1].plot(true[:,0], true[:,1], "-", color="#5aa469", lw=2.5, label="ground truth")
    ax[1].plot(dr[:,0], dr[:,1], "--", color="#c0762f", lw=1.5, label=f"dead reckoning ({ates[0][1]} m)")
    ax[1].plot(best[:,0], best[:,1], ":", color="#005587", lw=2, label=f"best (sim sensors, {ates[-1][1]} m raw)")
    ax[1].scatter([L[0] for L in lm], [L[1] for L in lm], marker="*", s=120, color="#ffcd00", edgecolor="k", label="landmarks")
    ax[1].legend(fontsize=8); ax[1].set_aspect("equal"); ax[1].set_title("Best wiring vs truth")
    fig.suptitle("Estimator cue-wiring sensitivity on the canonical G1 sub-baseline "
                 f"({ates[0][1]} m raw / {ates_aln[0][1]} m aligned over 87.74 m); "
                 "added cues are seeded sensor models, not image-derived",
                 fontsize=10)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(os.path.join(OUT, "wire_all.png"), dpi=150); plt.close(fig)
    print("wrote wire_all.png + wire_all_metrics.json")


if __name__ == "__main__":
    main()
