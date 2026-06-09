#!/usr/bin/env python3
"""G1 capture + baseline: produce the timestamped IMU/wheel channels that dustgym egress reported
UNAVAILABLE, lock them, and record the passive wheel+IMU dead-reckoning baseline ATE.

Provenance = MEASUREMENT_MODEL_SIM. The trajectory + per-step slip are dustgym's REAL physics on a
REAL LOLA Haworth DEM; the IMU/wheel channels are the grounded sensor model. Truth poses are kept on
a SEPARATE eval channel (I3). PORTABLE (G1.A3): dustgym, DEM, and output are resolved from CLI/env;
no machine path is hardcoded; the run records dustgym/solnav commits, parameter + DEM hashes, seed,
and Python/NumPy versions; no directories are created at import.

  python3 validation/g1_capture.py --dustgym-root <dir> --dem <heightmap.rf32> --output <dir> --seed 0
"""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys

import numpy as np

from solnav.eval import metrics
from solnav.slam import posegraph as pg

G, CELL_M, DT, MASS = 1.62, 5.0, 2.0, 30.0
IMU_HZ, WHEEL_HZ, V_CMD = 100.0, 10.0, 0.30
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # projects/solnav/solnav


def _sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _git_commit(path):
    try:
        r = subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def drive(dem_path, rover, slipmod, tm):
    h = np.fromfile(dem_path, dtype="<f4"); n = int(round(len(h) ** 0.5)); H = h.reshape(n, n)
    gr, gc = np.gradient(H)
    params = tm.TerramechanicsParams.from_constants()
    rc = (n // 2 - 30.0, n // 2 - 30.0); yaw = 0.6
    omegas = [0.0] * 40 + [0.012] * 40 + [-0.012] * 40 + [0.0] * 40
    true, steps = [], []
    for k in range(160):
        pr, _ = rover.step_pose(rc, yaw, 1.0, 0.0, 1.0, cell_m=CELL_M)
        hd = np.array([pr[0] - rc[0], pr[1] - rc[1]]); hd = hd / (np.linalg.norm(hd) + 1e-9)
        ri, ci = int(np.clip(rc[0], 0, n - 1)), int(np.clip(rc[1], 0, n - 1))
        slope = np.arctan2(gr[ri, ci] * hd[0] + gc[ri, ci] * hd[1], CELL_M)
        s = float(slipmod.slip_sinkage_equilibrium(MASS * G, slope, params=params)["slip"])
        nrc, nyaw = rover.step_pose(rc, yaw, (1 - s) * V_CMD, omegas[k], DT, cell_m=CELL_M)
        true.append([rc[1] * CELL_M, rc[0] * CELL_M, yaw])
        steps.append((V_CMD * (1 - s), omegas[k], s))     # true ground v, true yaw-rate, slip
        rc, yaw = nrc, nyaw
    true.append([rc[1] * CELL_M, rc[0] * CELL_M, yaw])
    return np.array(true), steps


def run(dustgym_root, dem_path, out_dir, seed):
    sys.path.insert(0, dustgym_root)
    from terrain_authority import rover
    from terrain_authority import slip as slipmod
    from terrain_authority import terramechanics as tm
    from terrain_authority.proprioception import ImuWheelModel  # generation lives in the producer

    os.makedirs(out_dir, exist_ok=True)
    true, steps = drive(dem_path, rover, slipmod, tm)
    model = ImuWheelModel(seed=seed)
    imu, wheel, t = [], [], 0.0
    n_imu, n_wheel = int(IMU_HZ * DT), int(WHEEL_HZ * DT)
    for (v_true, yaw_rate, s) in steps:
        for j in range(n_imu):
            imu.append(model.step_imu(t + j / IMU_HZ, yaw_rate, (0.0, 0.0)))
        for j in range(n_wheel):
            wheel.append(model.step_wheel(t + j / WHEEL_HZ, v_true, s, yaw_rate))
        t += DT

    paths = {}
    with open(os.path.join(out_dir, "imu.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "gyro_z", "acc_x", "acc_y"])
        for sm in imu:
            w.writerow([f"{sm.t:.4f}", f"{sm.gyro_z_rps:.8f}", f"{sm.accel_xy_mps2[0]:.6f}", f"{sm.accel_xy_mps2[1]:.6f}"])
    paths["imu.csv"] = os.path.join(out_dir, "imu.csv")
    with open(os.path.join(out_dir, "wheel_odom.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["timestamp", "v", "omega", "v_var", "omega_var"])
        for sm in wheel:
            w.writerow([f"{sm.t:.4f}", f"{sm.v_mps:.6f}", f"{sm.omega_rps:.6f}",
                        f"{sm.v_var:.8f}", f"{sm.omega_var:.8f}"])
    paths["wheel_odom.csv"] = os.path.join(out_dir, "wheel_odom.csv")
    with open(os.path.join(out_dir, "truth.csv"), "w", newline="") as f:     # EVAL channel only (I3)
        w = csv.writer(f); w.writerow(["step", "x", "y", "yaw", "true_slip", "provenance"])
        for i, p in enumerate(true):
            sl = steps[i][2] if i < len(steps) else 0.0
            w.writerow([i, f"{p[0]:.6f}", f"{p[1]:.6f}", f"{p[2]:.6f}", f"{sl:.4f}", "GROUND_TRUTH_EVAL"])
    paths["truth.csv"] = os.path.join(out_dir, "truth.csv")

    # passive wheel+IMU dead-reckoning baseline: position from wheel speed, heading from IMU gyro
    gyro_by_step = np.array([s.gyro_z_rps for s in imu]).reshape(len(steps), n_imu).mean(axis=1)
    v_by_step = np.array([s.v_mps for s in wheel]).reshape(len(steps), n_wheel).mean(axis=1)
    dr = [true[0].copy()]; yaw = true[0, 2]
    for k in range(len(steps)):
        yaw = yaw + gyro_by_step[k] * DT
        dr.append([dr[-1][0] + v_by_step[k] * DT * np.cos(yaw),
                   dr[-1][1] + v_by_step[k] * DT * np.sin(yaw), yaw])
    dr = np.array(dr)
    g = pg.PoseGraph(); g.add_prior(0, true[0])
    for i, z in enumerate(pg.relative_odometry(dr)):
        g.add_odom(i, i + 1, z)
    X = g.solve(np.array(dr))

    res = {
        "provenance": "MEASUREMENT_MODEL_SIM (real LOLA Haworth DEM + real dustgym slip; IMU/wheel = grounded sensor model)",
        "imu_rate_hz": IMU_HZ, "wheel_rate_hz": WHEEL_HZ, "n_steps": len(steps),
        "n_imu_samples": len(imu), "n_wheel_samples": len(wheel),
        "path_length_m": round(float(np.sum(np.linalg.norm(np.diff(true[:, :2], axis=0), axis=1))), 2),
        "mean_slip": round(float(np.mean([s for *_, s in steps])), 4),
        "max_slip": round(float(np.max([s for *_, s in steps])), 4),
        "baseline_wheel_imu_dead_reckoning": {
            "ate_raw_same_frame_m": round(metrics.ate_rmse_raw(dr, true), 3),
            "ate_aligned_m": round(metrics.ate_rmse(dr, true), 3),
            "final_pos_error_raw_m": round(float(np.linalg.norm(dr[-1, :2] - true[-1, :2])), 3),
            "heading_err_deg": round(metrics.heading_error_deg(dr[:, 2], true[:, 2]), 2),
        },
        "pose_graph_odom_only": {
            "ate_raw_same_frame_m": round(metrics.ate_rmse_raw(X, true), 3),
            "ate_aligned_m": round(metrics.ate_rmse(X, true), 3),
            "note": "no absolute cue -> smooths but does not reduce drift; P2/P4 cues are evaluated separately",
        },
        "reproducibility": {
            "dustgym_commit": _git_commit(dustgym_root),
            "solnav_commit": _git_commit(_REPO),
            "param_sha256": _sha256(os.path.join(dustgym_root, "terrain_authority", "data", "imu_wheel_params.json")),
            "dem_sha256": _sha256(dem_path),
            "seed": seed,
            "python": sys.version.split()[0],
            "numpy": np.__version__,
        },
        "files": {k: _sha256(v) for k, v in paths.items()},
    }
    json.dump(res, open(os.path.join(out_dir, "g1_capture_result.json"), "w"), indent=2)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="G1 wheel/IMU capture + baseline (portable).")
    ap.add_argument("--dustgym-root", default=os.environ.get("DUSTGYM_ROOT"),
                    help="path to the dustgym checkout (or set DUSTGYM_ROOT)")
    ap.add_argument("--dem", required=True, help="path to a LOLA heightmap.rf32")
    ap.add_argument("--output", required=True, help="output directory for the capture")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    if not args.dustgym_root:
        ap.error("--dustgym-root or DUSTGYM_ROOT is required")
    res = run(args.dustgym_root, args.dem, args.output, args.seed)
    print(json.dumps({k: v for k, v in res.items() if k != "files"}, indent=2))
    print("files:", {k: v[:12] for k, v in res["files"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
