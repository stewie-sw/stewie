#!/usr/bin/env python3
"""Corrected sub-baseline trajectory figure for the decks.

Reads the CANONICAL, hash-locked G1 capture
(`validation/g1_capture/{truth.csv,wheel_odom.csv,imu.csv}`), reintegrates the exact passive
wheel+IMU dead-reckoning that `validation/g1_capture.py` records, and reproduces the locked numbers:

  [MEASUREMENT_MODEL_SIM] path 87.74 m, raw same-frame 2-D ATE 4.632 m, aligned 2-D ATE 2.015 m,
  final raw position error 8.271 m, heading error 0.32 deg.

This is the real G1 sub-baseline artifact (real LOLA Haworth DEM + real dustgym slip; IMU/wheel are
the grounded sensor model). It is NOT a G1 pass, NOT sensor-derived stereo/SLAM, and is not directly
comparable to NavLab. The figure asserts it reproduces the locked g1_capture_result.json before
writing, so a drift in the underlying data fails loudly rather than silently mislabeling the plot.
"""
import csv
import json
import os

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from solnav.eval import metrics

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # projects/solnav/solnav
CAP = os.path.join(REPO, "validation", "g1_capture")
OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

DT, IMU_HZ, WHEEL_HZ = 2.0, 100.0, 10.0
N_IMU, N_WHEEL = int(IMU_HZ * DT), int(WHEEL_HZ * DT)


def _read_truth(path):
    xs, ys, yaws = [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            xs.append(float(row["x"])); ys.append(float(row["y"])); yaws.append(float(row["yaw"]))
    return np.column_stack([xs, ys, yaws])


def _read_col(path, col):
    out = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(float(row[col]))
    return np.array(out)


def dead_reckon(true):
    """Exact replica of validation/g1_capture.py: heading from IMU gyro, position from wheel speed."""
    n_steps = len(true) - 1
    gyro = _read_col(os.path.join(CAP, "imu.csv"), "gyro_z").reshape(n_steps, N_IMU).mean(axis=1)
    v = _read_col(os.path.join(CAP, "wheel_odom.csv"), "v").reshape(n_steps, N_WHEEL).mean(axis=1)
    dr = [true[0].copy()]; yaw = float(true[0, 2])
    for k in range(n_steps):
        yaw = yaw + gyro[k] * DT
        dr.append([dr[-1][0] + v[k] * DT * np.cos(yaw),
                   dr[-1][1] + v[k] * DT * np.sin(yaw), yaw])
    return np.array(dr)


def main():
    true = _read_truth(os.path.join(CAP, "truth.csv"))
    dr = dead_reckon(true)

    path_len = float(np.sum(np.linalg.norm(np.diff(true[:, :2], axis=0), axis=1)))
    ate_raw = metrics.ate_rmse_raw(dr, true)
    ate_aln = metrics.ate_rmse(dr, true)
    final_raw = float(np.linalg.norm(dr[-1, :2] - true[-1, :2]))
    head_err = metrics.heading_error_deg(dr[:, 2], true[:, 2])

    # honesty firewall: reproduce the locked numbers or fail loudly.
    locked = json.load(open(os.path.join(CAP, "g1_capture_result.json")))["baseline_wheel_imu_dead_reckoning"]
    assert abs(round(path_len, 2) - 87.74) < 0.01, f"path {path_len}"
    assert abs(round(ate_raw, 3) - locked["ate_raw_same_frame_m"]) < 1e-3, f"raw {ate_raw}"
    assert abs(round(ate_aln, 3) - locked["ate_aligned_m"]) < 1e-3, f"aligned {ate_aln}"
    assert abs(round(final_raw, 3) - locked["final_pos_error_raw_m"]) < 1e-3, f"final {final_raw}"
    assert abs(round(head_err, 2) - locked["heading_err_deg"]) < 1e-2, f"head {head_err}"

    # plot: trajectory + the locked headline numbers
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    ax[0].plot(true[:, 0], true[:, 1], "-", color="#5aa469", lw=2.6, label="ground truth (87.74 m)")
    ax[0].plot(dr[:, 0], dr[:, 1], "--", color="#c0762f", lw=1.8,
               label="passive wheel+IMU dead reckoning")
    ax[0].scatter([true[0, 0]], [true[0, 1]], marker="o", s=70, color="#004e42",
                  zorder=5, label="start")
    ax[0].scatter([true[-1, 0]], [true[-1, 1]], marker="s", s=70, color="#5aa469",
                  edgecolor="k", zorder=5, label="truth end")
    ax[0].scatter([dr[-1, 0]], [dr[-1, 1]], marker="X", s=90, color="#c0762f",
                  edgecolor="k", zorder=5, label="dead-reckoning end")
    ax[0].set_aspect("equal"); ax[0].grid(alpha=0.3)
    ax[0].set_xlabel("x (m)"); ax[0].set_ylabel("y (m)")
    ax[0].set_title("G1 sub-baseline traverse on real Haworth DEM")
    ax[0].legend(fontsize=8, loc="best")

    labels = ["raw same-frame\n2-D ATE", "Umeyama\naligned ATE", "final raw\npos error"]
    vals = [ate_raw, ate_aln, final_raw]
    colors = ["#005587", "#5aa469", "#c0762f"]
    bars = ax[1].bar(labels, vals, color=colors)
    ax[1].set_ylabel("error (m)")
    ax[1].set_title("Passive dead-reckoning drift\n(MEASUREMENT_MODEL_SIM; not a G1 pass, not sensed SLAM)")
    for b, v in zip(bars, vals):
        ax[1].text(b.get_x() + b.get_width() / 2, v + 0.12, f"{v:.3f} m", ha="center", fontsize=10)
    ax[1].text(0.98, 0.96, f"heading error {head_err:.2f} deg\nslip mean 8.6% / max 12.3%",
               transform=ax[1].transAxes, ha="right", va="top", fontsize=8.5,
               bbox=dict(boxstyle="round", fc="#fff7d6", ec="#999"))
    ax[1].set_ylim(0, max(vals) * 1.25)

    fig.suptitle("Reproducible passive wheel+IMU sub-baseline over 87.74 m "
                 "(real LOLA Haworth DEM + real dustgym slip; IMU/wheel = grounded sensor model)",
                 fontsize=11)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(OUT, "g1_subbaseline.png")
    fig.savefig(out, dpi=150); plt.close(fig)
    print(f"path={path_len:.2f} m  raw={ate_raw:.3f}  aligned={ate_aln:.3f}  "
          f"final_raw={final_raw:.3f}  heading={head_err:.2f} deg")
    print(f"wrote {out} (reproduces locked g1_capture_result.json)")


if __name__ == "__main__":
    main()
