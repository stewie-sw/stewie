"""Wheel+IMU dead-reckoning baseline on the REAL Katwijk Traverse-1 (G1's real-world leg).

Inputs: the roboshare Part files via stewie.bridge.katwijk_io (documented headerless bindings).
Method (the same passive wheel/IMU baseline as the simulated G1 capture):
  v(t)   = mean(drive angular velocity over the 6 wheels) * R_wheel
  yaw(t) = integral of the IMU z gyro (Stim300; z up, |acc| ~ g verified by the parser tests)
  (x, y) = planar integration on the IMU clock
R_wheel is CALIBRATED on the FIRST THIRD of the RTK track (distance ratio) and DISCLOSED in the
output; heading is aligned at the calibration boundary; the ATE is scored on the untouched
remaining two thirds against RTK_FIXED truth (cm-class sigmas). The dataset's own
wheelTransformation.m supplies lever arms but no radius -- the data-driven scale is the honest
alternative to guessing, and the disjoint split keeps the evaluation clean.
"""
from __future__ import annotations

import os

import numpy as np

from stewie.bridge import katwijk_io as kio


def load_rtk_track(part_dir: str):
    """RTK_FIXED-only track -> (t[N], xy[N,2] local metres, EN plane)."""
    rows = [r for r in kio.load_gps_real(os.path.join(part_dir, "gps-latlong.txt"))
            if r["status"] == "RTK_FIXED"]
    if len(rows) < 10:
        raise ValueError("not enough RTK_FIXED rows")
    lat0, lon0 = rows[0]["lat"], rows[0]["lon"]
    R = 6371000.0
    xy = np.array([[np.radians(r["lon"] - lon0) * R * np.cos(np.radians(lat0)),
                    np.radians(r["lat"] - lat0) * R] for r in rows])
    t = np.array([r["t"] for r in rows])
    return t, xy


def _dead_reckon(part_dir: str, r_wheel: float):
    """Integrate wheel speed + gyro yaw on the odometry clock -> (t[N], xy[N,2], yaw[N])."""
    odo = kio.load_odometry_real(os.path.join(part_dir, "odometry.txt"))
    imu = kio.load_imu_real(os.path.join(part_dir, "imu.txt"))
    imu_t = np.array([r["t"] for r in imu])
    gyro_z = np.array([r["gyro"][2] for r in imu])
    t = np.array([r["t"] for r in odo])
    v = np.array([float(np.mean(r["drive_vel"])) for r in odo]) * r_wheel
    # yaw on the IMU clock, sampled to the odometry clock
    yaw_imu = np.concatenate([[0.0], np.cumsum(gyro_z[:-1] * np.diff(imu_t))])
    yaw = np.interp(t, imu_t, yaw_imu)
    dt = np.diff(t)
    x = np.concatenate([[0.0], np.cumsum(v[:-1] * np.cos(yaw[:-1]) * dt)])
    y = np.concatenate([[0.0], np.cumsum(v[:-1] * np.sin(yaw[:-1]) * dt)])
    return t, np.stack([x, y], axis=1), yaw


def _track_length(xy: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum())


def run(part_dir: str) -> dict:
    gt_t, gt_xy = load_rtk_track(part_dir)
    n_cal = len(gt_t) // 3
    cal_t = gt_t[n_cal - 1]

    # 1) unit-scale reckon -> wheel radius from the distance ratio on the CALIBRATION third
    t1, xy1, _ = _dead_reckon(part_dir, r_wheel=1.0)
    m_cal = t1 <= cal_t
    reck_cal_len = _track_length(xy1[m_cal])
    gt_cal_len = _track_length(gt_xy[: n_cal])
    if reck_cal_len <= 0:
        raise ValueError("no wheel motion in the calibration window")
    r_wheel = gt_cal_len / reck_cal_len

    # 2) full reckon at the calibrated scale; align position+heading AT the calibration boundary
    t, xy, _ = _dead_reckon(part_dir, r_wheel=r_wheel)
    gt_at = np.stack([np.interp(t, gt_t, gt_xy[:, 0]), np.interp(t, gt_t, gt_xy[:, 1])], axis=1)
    i0 = int(np.searchsorted(t, cal_t))
    # heading of each track over the last calibration leg
    def _heading(p, i, k=10):
        d = p[i] - p[max(0, i - k)]
        return np.arctan2(d[1], d[0])
    th = _heading(gt_at, i0) - _heading(xy, i0)
    Rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    xy_al = (xy - xy[i0]) @ Rm.T + gt_at[i0]

    # 3) ATE on the UNTOUCHED remainder
    m_eval = t > cal_t
    err = np.linalg.norm(xy_al[m_eval] - gt_at[m_eval], axis=1)
    return {
        "schema_version": "solnav_katwijk_dead_reckon/1.0",
        "dataset": "Katwijk Beach Traverse-1 Part1 (roboshare, RTK_FIXED truth)",
        "wheel_radius_m": round(float(r_wheel), 6),
        "calibration": {"segment": "first_third", "gt_len_m": round(gt_cal_len, 3),
                        "disclosure": "wheel scale + boundary pose/heading from the calibration "
                                      "third; evaluation segment untouched"},
        "eval_track_length_m": round(_track_length(gt_at[m_eval]), 3),
        "ate_aligned_m": round(float(np.sqrt(np.mean(err ** 2))), 4),
        "max_err_m": round(float(err.max()), 4),
        "n_eval_points": int(m_eval.sum()),
    }
