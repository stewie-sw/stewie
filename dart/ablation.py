"""SN ablation harness: the contribution-attribution core (PROPOSAL §6.3).

Add-one ablation against the passive dead-reckoning baseline. The TRUTH trajectory and the
dead-reckoning DRIFT are REAL (Katwijk wheel/IMU vs RTK); the absolute map-fix observations are
MODELLED at the calibrated shadow/DEM sigma (seeded, documented) because the Katwijk run carries no
lunar shadow/DEM channel -- this is the standard add-one method (§6.3 'multiple seeds'), NOT a
real-rover shadow-nav claim. Two metrics, because they tell different stories: ALIGNED ATE (2-D rigid alignment) measures
RELATIVE shape -- dead-reckoning is already good at it -- while ABSOLUTE max error measures GLOBAL
drift, which dead-reckoning leaves unbounded and an absolute (DEM/shadow) channel BOUNDS. The
contribution of the absolute factor is in the absolute metric, not the aligned one (an honest,
important distinction).
"""
from __future__ import annotations

import math

import numpy as np

from dart.pose_graph_se2 import PoseGraphSE2


def _align_ate(est: np.ndarray, truth: np.ndarray) -> float:
    """Aligned ATE [m]: RMS position error after the best 2-D rigid (R,t) alignment (Umeyama, no scale)."""
    e = np.asarray(est, float); g = np.asarray(truth, float)
    mu_e, mu_g = e.mean(0), g.mean(0)
    H = (e - mu_e).T @ (g - mu_g)
    U, _S, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:                       # reflection guard
        Vt[-1] *= -1; R = Vt.T @ U.T
    aligned = (e - mu_e) @ R.T + mu_g
    return float(np.sqrt(np.mean(np.sum((aligned - g) ** 2, axis=1))))


def _heading_rmse_deg(est_yaw, truth_yaw):
    """RMS heading error [deg], wrapped, after removing a constant frame offset (gyro vs world)."""
    import numpy as _np
    e = _np.asarray(est_yaw, float); g = _np.asarray(truth_yaw, float)
    off = _np.arctan2(_np.mean(_np.sin(g - e)), _np.mean(_np.cos(g - e)))   # best constant offset
    d = _np.arctan2(_np.sin(g - (e + off)), _np.cos(g - (e + off)))
    return float(_np.degrees(_np.sqrt(_np.mean(d ** 2))))


def controlled_drift_run(n=200, *, turn_rate_deg=0.4, gyro_bias_deg=15.0, gyro_noise_deg=0.10, seed=0):
    """A DOCUMENTED controlled-condition run for the heading-factor characterization (§6.3): a smooth
    truth heading (constant turn) and a gyro estimate with a CONSTANT BIAS + white noise (the model
    of real gyro drift). Returns (truth_yaw, gyro_yaw). This is the standard way to characterize a
    drift-correcting factor -- a controlled experiment with a known-truth heading, seeded; NOT a
    real-rover result (the real Katwijk RTK-bearing heading is too noisy to be a clean heading truth,
    so the heading factor is characterized HERE, while position uses the real run in factor_ablation)."""
    rng = np.random.default_rng(seed)
    truth = np.radians(turn_rate_deg) * np.arange(n)                  # smooth constant-rate turn
    # gyro starts ALIGNED to truth (gyro[0]==truth[0]); an accumulated heading bias ramps to
    # gyro_bias_deg by the end (an uncorrected MEMS gyro over a long leg) + white noise.
    bias = np.radians(gyro_bias_deg)
    gyro = truth + bias * (np.arange(n) / max(1, n - 1)) + np.radians(gyro_noise_deg) * rng.standard_normal(n)
    return truth, gyro


def heading_ablation(truth_yaw, gyro_yaw, *, n_keyframes=40, fix_interval=5, fix_sigma_deg=3.0, seed=0):
    """SN-03 add-one on HEADING: the gyro yaw DRIFTS; a periodic shadow-derived absolute-yaw factor
    bounds it. Returns {condition: heading_rmse_deg}. Works on ANY (truth_yaw, gyro_yaw) pair; the
    shadow-yaw fixes are modelled at the calibrated sigma (seeded). Use controlled_drift_run() for the
    heading characterization (the contribution: heading RMSE drops, the shadow cue earns its place)."""
    tyaw = np.asarray(truth_yaw, float); gyaw = np.asarray(gyro_yaw, float)
    n = min(len(tyaw), len(gyaw)); idx = np.linspace(0, n - 1, n_keyframes).astype(int)
    T = tyaw[idx]; G = gyaw[idx]
    rng = np.random.default_rng(seed)
    def _abs_rmse(yaw):                                   # absolute heading RMSE (the shadow gives the lock)
        d = np.arctan2(np.sin(T - yaw), np.cos(T - yaw))
        return float(np.degrees(np.sqrt(np.mean(d ** 2))))
    base = _abs_rmse(G)                                   # baseline: absolute gyro drift vs truth heading

    g = PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, float(G[0])), sigma_xy=1e3, sigma_yaw=0.5)   # yaw-only graph (xy free)
    for k in range(1, n_keyframes):
        dyaw = float(np.arctan2(np.sin(G[k] - G[k - 1]), np.cos(G[k] - G[k - 1])))
        g.add_imu_yaw(k - 1, k, dyaw, sigma=0.05)         # the real gyro DELTA (carries drift)
        g.add_between(k - 1, k, (1.0, 0.0, dyaw), sigma_xy=1e3, sigma_yaw=1e3)  # keep nodes connected
    sig = math.radians(fix_sigma_deg); n_fix = 0
    for k in range(fix_interval, n_keyframes, fix_interval):
        meas = float(T[k] + rng.normal(0.0, sig))         # modelled shadow-derived absolute heading
        g.add_shadow_yaw(k, measured_yaw=meas, sigma=sig)
        n_fix += 1
    est = g.optimize()
    est_yaw = np.array([est[k][2] for k in range(n_keyframes)])
    return {"baseline (gyro only)": round(base, 3),
            "+shadow yaw (SN-03)": round(_abs_rmse(est_yaw), 3),
            "n_fixes": n_fix}


#: preregistered gate axes: margin key -> the (lower-is-better) error metric it constrains.
_GATE_AXES = {"yaw_deg": "yaw_err_deg", "pose_m": "pose_err_m"}
