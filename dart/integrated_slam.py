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


def load_katwijk_arrays(part_dir):
    """(truth_xy, dr_xy, truth_yaw, gyro_yaw) for a Katwijk part, resampled to a common length."""
    from stewie.eval import katwijk_baseline as KB
    _t, truth = KB.load_rtk_track(part_dir)
    _td, dr, gyro = KB._dead_reckon(part_dir, r_wheel=0.123025)
    dr = dr[np.linspace(0, len(dr) - 1, len(truth)).astype(int)]
    gyro = gyro[np.linspace(0, len(gyro) - 1, len(truth)).astype(int)]
    seg = np.diff(truth, axis=0)
    tyaw = np.concatenate([np.arctan2(seg[:, 1], seg[:, 0]), [0.0]])
    return truth, dr, tyaw, gyro


def slam_statistics(truth_xy, dr_xy, truth_yaw, gyro_yaw, *, n_seeds=20, **kw):
    """Run the full fusion over n_seeds (the modeled-factor noise) -> the DISTRIBUTION of the fused
    absolute drift with a 95% CI, against the deterministic odometry-only baseline. Turns the single
    demonstration into a distribution."""
    base = run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, factors=("odom",), seed=0, **kw)["abs_max_err_m"]
    fused = np.array([run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, seed=s, **kw)["abs_max_err_m"]
                      for s in range(n_seeds)])
    mean, std = float(fused.mean()), float(fused.std(ddof=1)) if n_seeds > 1 else 0.0
    ci = 1.96 * std / math.sqrt(n_seeds)
    return {"baseline_abs_m": round(base, 3), "fused_mean_m": round(mean, 3), "fused_std_m": round(std, 3),
            "fused_ci95_m": round(ci, 3), "fused_min_m": round(float(fused.min()), 3),
            "fused_max_m": round(float(fused.max()), 3), "reduction_x_mean": round(base / mean, 1),
            "n_seeds": n_seeds}


def shared_testbed_comparison(truth_xy, dr_xy, truth_yaw, gyro_yaw, *, n_seeds=20, **kw):
    """The measured head-to-head: the SAME pose graph over the SAME trajectory under three approach
    classes, each at its characteristic fix sigma -- Stanford-class passive (no absolute fix on a
    single-pass traverse; bounds drift only by driving a loop-closure pattern), ShadowNav-class
    (global map-match fixes ~3 m), ARGUS (articulation-parallax fixes ~0.5 m). Returns each config's
    absolute-drift distribution (mean + 95% CI). Converts the positioning matrix into one-testbed
    numbers. The active-cue/map fixes are modeled at each method's reported sigma against the real
    Katwijk drift."""
    def stat(factors, **o):
        kk = dict(kw); kk.update(o)
        # passive (odom-only fixes) is deterministic; fix-bearing configs vary with the seed
        runs = [run_integrated_slam(truth_xy, dr_xy, truth_yaw, gyro_yaw, factors=factors, seed=s, **kk)["abs_max_err_m"]
                for s in range(n_seeds if any(f in factors for f in ("shadow", "parallax", "dem")) else 1)]
        a = np.array(runs)
        ci = 1.96 * a.std(ddof=1) / math.sqrt(len(a)) if len(a) > 1 else 0.0
        return {"mean_m": round(float(a.mean()), 3), "ci95_m": round(float(ci), 3)}
    return {
        "Stanford-class (passive, single pass)": {**stat(("odom", "imu")),
            "note": "no absolute fix on a non-looping traverse; bounds drift only via a driven loop-closure pattern"},
        "ShadowNav-class (global map-match)": {**stat(("odom", "imu", "dem"), sigma_dem_m=3.0),
            "note": "global map-match fixes ~3 m; needs the orbital prior"},
        "ARGUS (articulation parallax)": {**stat(("odom", "imu", "shadow", "parallax"), sigma_parallax_m=0.5),
            "note": "standstill parallax fixes ~0.5 m; map-free, heading-free"},
    }


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
