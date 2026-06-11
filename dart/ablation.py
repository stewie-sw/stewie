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


def factor_ablation(truth_xy, dr_xy, *, n_keyframes=30, fix_interval=5, fix_sigma_m=2.0, seed=0):
    """Add-one ablation over keyframes. Returns {condition: {ate_m, max_err_m, n_fixes}}.

    baseline = the real dead-reckoned keyframes (ATE vs RTK truth). +abs_fix = a pose graph whose
    BETWEEN factors are the real DR deltas (the real drift) and which receives modelled absolute
    fixes (truth + N(0,sigma), seeded) every ``fix_interval`` keyframes -- the marginal value of
    bounding drift with an absolute channel."""
    truth = np.asarray(truth_xy, float); dr = np.asarray(dr_xy, float)
    n = min(len(truth), len(dr))
    idx = np.linspace(0, n - 1, n_keyframes).astype(int)
    T = truth[idx]; D = dr[idx]                    # keyframe truth + dead-reckoned tracks
    rng = np.random.default_rng(seed)

    out = {"baseline (odometry only)": {"ate_aligned_m": round(_align_ate(D, T), 4),
                                        "abs_max_err_m": round(float(np.max(np.linalg.norm(D - T, axis=1))), 4),
                                        "n_fixes": 0}}
    # +absolute fixes: graph with real DR deltas as between-factors, modelled fixes at the envelope sigma
    g = PoseGraphSE2()
    g.add_prior(0, (D[0, 0], D[0, 1], 0.0), sigma_xy=0.1, sigma_yaw=0.5)
    for k in range(1, n_keyframes):
        d = D[k] - D[k - 1]                        # the REAL dead-reckoned relative motion (carries drift)
        g.add_between(k - 1, k, (float(d[0]), float(d[1]), 0.0), sigma_xy=0.5, sigma_yaw=0.5)
    n_fix = 0
    for k in range(fix_interval, n_keyframes, fix_interval):
        fix = T[k] + rng.normal(0.0, fix_sigma_m, size=2)   # modelled absolute fix at the calibrated sigma
        g.add_absolute(k, (float(fix[0]), float(fix[1])), sigma=fix_sigma_m)
        n_fix += 1
    est = g.optimize()
    E = np.array([est[k][:2] for k in range(n_keyframes)])
    out["+absolute fixes (DEM/shadow)"] = {"ate_aligned_m": round(_align_ate(E, T), 4),
                                           "abs_max_err_m": round(float(np.max(np.linalg.norm(E - T, axis=1))), 4),
                                           "n_fixes": n_fix}
    return out
