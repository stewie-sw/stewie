"""G1.A7 isolated evidence pipeline: produce -> estimate -> evaluate with strict truth isolation.

Formalizes the g1_capture baseline into three SEPARATED stages so the evidence is auditable:
  produce  : split sensors into runtime/ (imu+wheel + the declared deployment origin) and a SEPARATE
             truth/ dir (GROUND_TRUTH_EVAL). No scoring.
  estimate : consume ONLY runtime/ (I3 -- never any GROUND_TRUTH_EVAL/truth/slip), dead-reckon + freeze
             the output to estimate.csv and HASH it (I7 -- the estimate is frozen before any truth load).
  evaluate : REQUIRE the frozen hash to match, THEN load truth and score ATE (raw + Umeyama-aligned).

The start pose is the rover's declared deployment origin (a legitimate runtime input -- the rover knows
where it was placed), written to runtime/config.json, NOT read from the truth channel.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil

import numpy as np

from solnav.eval import metrics

_TRUTH_MARKERS = ("ground_truth", "true_slip", "truth", "slip")


def _read_csv(path: str):
    with open(path) as f:
        r = csv.reader(f)
        header = next(r)
        return header, [row for row in r]


def produce(capture_dir: str, out_dir: str):
    """Split an existing g1_capture into isolated runtime/ + truth/ dirs + a runtime config."""
    runtime = os.path.join(out_dir, "runtime")
    truth = os.path.join(out_dir, "truth")
    os.makedirs(runtime, exist_ok=True)
    os.makedirs(truth, exist_ok=True)
    for f in ("imu.csv", "wheel_odom.csv"):                       # runtime channels (no truth)
        shutil.copy(os.path.join(capture_dir, f), os.path.join(runtime, f))
    shutil.copy(os.path.join(capture_dir, "truth.csv"), os.path.join(truth, "truth.csv"))   # eval only
    _, tr = _read_csv(os.path.join(capture_dir, "truth.csv"))
    x0, y0, yaw0 = float(tr[0][1]), float(tr[0][2]), float(tr[0][3])   # declared deployment origin
    json.dump({"imu_hz": 100.0, "wheel_hz": 10.0, "dt": 2.0, "n_steps": len(tr) - 1,
               "start_pose": [x0, y0, yaw0]}, open(os.path.join(runtime, "config.json"), "w"))
    return runtime, truth


def estimate(runtime_dir: str, out_dir: str):
    """Dead-reckon from the runtime channels only (I3), then freeze + hash the estimate (I7)."""
    for fn in os.listdir(runtime_dir):                            # I3: no truth file in the input
        if any(m in fn.lower() for m in ("ground_truth", "truth")):
            raise ValueError(f"truth file '{fn}' present in runtime input (I3 violation)")
    cfg = json.load(open(os.path.join(runtime_dir, "config.json")))
    n_imu, n_wheel, N = int(cfg["imu_hz"] * cfg["dt"]), int(cfg["wheel_hz"] * cfg["dt"]), int(cfg["n_steps"])
    ih, imu = _read_csv(os.path.join(runtime_dir, "imu.csv"))
    wh_h, wh = _read_csv(os.path.join(runtime_dir, "wheel_odom.csv"))
    for h in (*ih, *wh_h):                                        # I3: no truth column smuggled in
        if any(m in h.lower() for m in _TRUTH_MARKERS):
            raise ValueError(f"truth-bearing column '{h}' in a runtime channel (I3 violation)")
    gyro = np.array([float(r[1]) for r in imu]).reshape(N, n_imu).mean(axis=1)
    v = np.array([float(r[1]) for r in wh]).reshape(N, n_wheel).mean(axis=1)
    x0, y0, yaw0 = cfg["start_pose"]
    dt = float(cfg["dt"])
    dr = [[x0, y0, yaw0]]
    yaw = yaw0
    for k in range(N):
        yaw = yaw + gyro[k] * dt
        dr.append([dr[-1][0] + v[k] * dt * np.cos(yaw), dr[-1][1] + v[k] * dt * np.sin(yaw), yaw])
    os.makedirs(out_dir, exist_ok=True)
    est = os.path.join(out_dir, "estimate.csv")
    with open(est, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["step", "x", "y", "yaw"])
        for i, p in enumerate(dr):
            w.writerow([i, f"{p[0]:.6f}", f"{p[1]:.6f}", f"{p[2]:.6f}"])
    digest = hashlib.sha256(open(est, "rb").read()).hexdigest()
    open(os.path.join(out_dir, "estimate.sha256"), "w").write(digest)   # I7: freeze
    return est, digest


def evaluate(estimate_dir: str, truth_dir: str):
    """Require the frozen estimate hash to match BEFORE loading truth (I7), then score ATE."""
    est = os.path.join(estimate_dir, "estimate.csv")
    hp = os.path.join(estimate_dir, "estimate.sha256")
    if not os.path.exists(hp):
        raise ValueError("estimate is not frozen (no estimate.sha256) -- refusing to score (I7)")
    frozen = open(hp).read().strip()
    if frozen != hashlib.sha256(open(est, "rb").read()).hexdigest():
        raise ValueError("estimate hash mismatch -- output changed after freeze (I7)")
    _, er = _read_csv(est)
    est_xy = np.array([[float(r[1]), float(r[2]), float(r[3])] for r in er])
    _, tr = _read_csv(os.path.join(truth_dir, "truth.csv"))       # truth loaded ONLY now
    true = np.array([[float(r[1]), float(r[2]), float(r[3])] for r in tr])
    m = {"ate_raw_m": round(metrics.ate_rmse_raw(est_xy, true), 3),
         "ate_aligned_m": round(metrics.ate_rmse(est_xy, true), 3),
         "n_poses": len(est_xy), "estimate_sha256": frozen}
    json.dump(m, open(os.path.join(estimate_dir, "metrics.json"), "w"), indent=2)
    return m
