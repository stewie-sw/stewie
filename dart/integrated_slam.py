"""KEYSTONE: the integrated multi-factor estimator run on the real Katwijk trajectory.

The dissertation's central claim assembled in one place: the SE(2) pose graph fusing odometry, the
gyro-IMU yaw factor, the SN-03 shadow-yaw factor, the SN-10 articulation-parallax position fix (at
the geometry-derived sigma), and a DEM-registration position fix, driven over the REAL Katwijk
truth + wheel/gyro odometry, with absolute trajectory error reported against RTK truth and a
leave-one-out ablation measuring each factor's marginal contribution.

HONESTY: the trajectory + odometry DRIFT are real; the active-cue factors (shadow-yaw, parallax,
DEM) are modeled at their calibrated/measured sigma because the Katwijk run carries no lunar shadow
channel. This is the integrated form of the §6.3 attribution; the full lunar-shadow integrated run
awaits a real lunar-analog dataset with pose truth (the medium gap in the completeness analysis).
"""
from __future__ import annotations

import math

import numpy as np

from dart.ablation import _align_ate
from dart.pose_graph_se2 import PoseGraphSE2

ALL_FACTORS = ("odom", "imu", "shadow", "parallax", "dem")


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, *, factors=ALL_FACTORS,
                        n_keyframes=30, fix_interval=4, sigma_shadow_deg=3.0,
                        sigma_parallax_m=0.5, sigma_dem_m=2.0, seed=0):
    """Fuse the chosen factors over the real Katwijk keyframes. 'odom' is the backbone (always kept).
    Returns {ate_aligned_m, abs_max_err_m, est_xy, n_fix}. Absolute fixes (parallax/dem) bound the
    global drift; shadow-yaw bounds heading."""
    T = np.asarray(truth_xy, float); D = np.asarray(dr_xy, float)
    Ty = np.asarray(truth_yaw, float); Gy = np.asarray(gyro_yaw, float)
    n = min(len(T), len(D), len(Ty), len(Gy))
    idx = np.linspace(0, n - 1, n_keyframes).astype(int)
    T, D, Ty, Gy = T[idx], D[idx], Ty[idx], Gy[idx]
    rng = np.random.default_rng(seed)

    g = PoseGraphSE2()
    g.add_prior(0, (T[0, 0], T[0, 1], Ty[0]), sigma_xy=0.1, sigma_yaw=0.1)
    for k in range(1, n_keyframes):
        d = D[k] - D[k - 1]
        dyaw = _wrap(Gy[k] - Gy[k - 1])
        g.add_between(k - 1, k, (float(d[0]), float(d[1]), dyaw), sigma_xy=0.5, sigma_yaw=0.5)
        if "imu" in factors:
            g.add_imu_yaw(k - 1, k, dyaw, sigma=0.05)
    n_fix = {"shadow": 0, "parallax": 0, "dem": 0}
    s_sh = math.radians(sigma_shadow_deg)
    for k in range(fix_interval, n_keyframes, fix_interval):
        if "shadow" in factors:
            g.add_shadow_yaw(k, float(Ty[k] + rng.normal(0, s_sh)), sigma=s_sh); n_fix["shadow"] += 1
        if "parallax" in factors:
            g.add_absolute(k, T[k] + rng.normal(0, sigma_parallax_m, 2), sigma=sigma_parallax_m); n_fix["parallax"] += 1
    for k in range(2 * fix_interval, n_keyframes, 2 * fix_interval):
        if "dem" in factors:
            g.add_absolute(k, T[k] + rng.normal(0, sigma_dem_m, 2), sigma=sigma_dem_m); n_fix["dem"] += 1
    est = g.optimize()
    E = np.array([est[k][:2] for k in range(n_keyframes)])
    return {"ate_aligned_m": round(_align_ate(E, T), 4),
            "abs_max_err_m": round(float(np.max(np.linalg.norm(E - T, axis=1))), 4),
            "est_xy": E, "n_fix": n_fix}


def leave_one_out(truth_xy, dr_xy, truth_yaw, gyro_yaw, **kw):
    """Baseline (odometry only), full fusion, and full-minus-each-factor. Returns the ATE table +
    each optional factor's marginal contribution (the abs-error increase when it is removed)."""
    base = run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, factors=("odom",), **kw)
    full = run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, factors=ALL_FACTORS, **kw)
    contrib = {}
    for f in ("imu", "shadow", "parallax", "dem"):
        without = run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw,
                                      factors=tuple(x for x in ALL_FACTORS if x != f), **kw)
        contrib[f] = {"abs_max_err_without_m": without["abs_max_err_m"],
                      "contribution_m": round(without["abs_max_err_m"] - full["abs_max_err_m"], 4)}
    return {"baseline_odom": base, "full": full, "leave_one_out": contrib}
