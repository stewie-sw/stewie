"""Integrated multi-factor SE(2) estimator: odometry backbone plus gyro-IMU yaw, SN-03 shadow-yaw,
SN-10 articulation-parallax and DEM-registration fixes, with aligned ATE against the trajectory truth.

Callers supply the trajectory (truth, dead-reckoned odometry, truth yaw, gyro yaw) and, through
``measured_fixes``, the fixes measured by the rendered-sensor estimators (dart.slam_seam,
dart.render_traverse).
"""
from __future__ import annotations

import math

import numpy as np

from dart.ablation import _align_ate, _heading_rmse_deg
from dart.factors import FactorType, MeasurementFactor, factor_lookup
from dart.pose_graph_se2 import PoseGraphSE2

ALL_FACTORS = ("odom", "imu", "shadow", "parallax", "dem")


def _wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, *, factors=ALL_FACTORS,
                        n_keyframes=30, fix_interval=4, sigma_shadow_deg=3.0,
                        sigma_parallax_m=0.5, sigma_dem_m=2.0, seed=0, measured_fixes=None):
    """Fuse the chosen factors over the trajectory keyframes. 'odom' is the backbone (always kept).
    Returns {ate_aligned_m, abs_max_err_m, est_xy, n_fix, measured}. Absolute fixes (parallax/dem)
    bound the global drift; shadow-yaw bounds heading.

    SLAM-seam: ``measured_fixes`` optionally supplies MEASURED fixes produced by the rendered-sensor
    estimators (dart.slam_seam: register_to_dem / articulation_localize), keyed by factor then
    keyframe -- ``{"parallax": {k: ((x,y), sigma)}, "dem": {k: ((x,y), sigma)}, "shadow": {k:
    (yaw, sigma)}}``. When a (factor, keyframe) is present its measured value+sigma is fused in place
    of the modeled (truth + calibrated-sigma) fix. When ``measured_fixes is None`` (the default) the
    modeled path runs byte-identically -- the rng draw order is unchanged. The end-to-end run driving
    these off a real rendered lunar sequence with pose truth is GATED on such a dataset."""
    T = np.asarray(truth_xy, float); D = np.asarray(dr_xy, float)
    Ty = np.asarray(truth_yaw, float); Gy = np.asarray(gyro_yaw, float)
    n = min(len(T), len(D), len(Ty), len(Gy))
    idx = np.linspace(0, n - 1, n_keyframes).astype(int)
    T, D, Ty, Gy = T[idx], D[idx], Ty[idx], Gy[idx]
    rng = np.random.default_rng(seed)

    typed_lookup = factor_lookup(measured_fixes) if isinstance(measured_fixes, (list, tuple)) else None

    def _measured(factor, k):
        if typed_lookup and factor in typed_lookup and k in typed_lookup[factor]:
            return typed_lookup[factor][k]
        if measured_fixes and isinstance(measured_fixes, dict) and factor in measured_fixes and k in measured_fixes[factor]:
            return measured_fixes[factor][k]               # legacy (value, sigma)
        return None

    def _add_yaw(k, m):
        if isinstance(m, MeasurementFactor):
            v = float(np.asarray(m.value, float).reshape(-1)[0])
            g.add_shadow_yaw(k, v, sigma=m.scalar_sigma())
        else:
            g.add_shadow_yaw(k, float(m[0]), sigma=float(m[1]))

    def _add_xy(k, m):
        if isinstance(m, MeasurementFactor):
            g.add_absolute_cov(k, np.asarray(m.value, float), m.xy_covariance())
        else:
            g.add_absolute(k, np.asarray(m[0], float), sigma=float(m[1]))

    g = PoseGraphSE2()
    g.add_prior(0, (T[0, 0], T[0, 1], Ty[0]), sigma_xy=0.1, sigma_yaw=0.1)
    for k in range(1, n_keyframes):
        d = D[k] - D[k - 1]
        dyaw = _wrap(Gy[k] - Gy[k - 1])
        g.add_between(k - 1, k, (float(d[0]), float(d[1]), dyaw), sigma_xy=0.5, sigma_yaw=0.5)
        if "imu" in factors:
            g.add_imu_yaw(k - 1, k, dyaw, sigma=0.05)
    n_fix = {"shadow": 0, "parallax": 0, "dem": 0}
    n_measured = 0
    s_sh = math.radians(sigma_shadow_deg)
    for k in range(fix_interval, n_keyframes, fix_interval):
        if "shadow" in factors:
            m = _measured(FactorType.SHADOW_YAW, k) or _measured("shadow", k)
            if m is not None:
                _add_yaw(k, m); n_measured += 1
            else:
                g.add_shadow_yaw(k, float(Ty[k] + rng.normal(0, s_sh)), sigma=s_sh)
            n_fix["shadow"] += 1
        if "parallax" in factors:
            m = _measured(FactorType.PARALLAX_XY, k) or _measured("parallax", k)
            if m is not None:
                _add_xy(k, m); n_measured += 1
            else:
                g.add_absolute(k, T[k] + rng.normal(0, sigma_parallax_m, 2), sigma=sigma_parallax_m)
            n_fix["parallax"] += 1
    for k in range(2 * fix_interval, n_keyframes, 2 * fix_interval):
        if "dem" in factors:
            m = _measured(FactorType.DEM_XY, k) or _measured("dem", k)
            if m is not None:
                _add_xy(k, m); n_measured += 1
            else:
                g.add_absolute(k, T[k] + rng.normal(0, sigma_dem_m, 2), sigma=sigma_dem_m)
            n_fix["dem"] += 1
    est = g.optimize()
    E = np.array([est[k][:2] for k in range(n_keyframes)])
    Y = np.array([est[k][2] for k in range(n_keyframes)])
    return {"ate_aligned_m": round(_align_ate(E, T), 4),
            "abs_max_err_m": round(float(np.max(np.linalg.norm(E - T, axis=1))), 4),
            "heading_rmse_deg": round(_heading_rmse_deg(Y, Ty), 4),
            "est_xy": E, "est_yaw": Y, "n_fix": n_fix, "measured": n_measured}
