"""SN ablation: the add-one contribution-attribution core, on the REAL Katwijk baseline."""
import numpy as np

from dart.ablation import _align_ate


def test_align_ate_zero_for_identical_tracks():
    t = np.cumsum(np.ones((20, 2)), axis=0)
    assert _align_ate(t, t) < 1e-9



def test_shadow_yaw_improves_heading_controlled():
    """SN-03 §6.3: with REALISTIC gyro drift (15 deg accumulated over the leg), the shadow-yaw
    factor clearly bounds the absolute heading error -- we SEE the improvement."""
    from dart.ablation import controlled_drift_run, heading_ablation
    truth, gyro = controlled_drift_run(n=200, gyro_bias_deg=15.0, seed=0)
    res = heading_ablation(truth, gyro, n_keyframes=40, fix_interval=5, fix_sigma_deg=3.0, seed=0)
    base, aided = res["baseline (gyro only)"], res["+shadow yaw (SN-03)"]
    assert aided < 0.6 * base, f"shadow yaw must clearly improve heading at realistic drift: {aided} vs {base}"



def test_shadow_rejected_when_gyro_better_than_shadow():
    """§6.3 honesty: a cue is KEPT only if it improves the objective. With negligible gyro drift,
    a 3-deg shadow fix does NOT beat the gyro -- the factor must not be force-fit."""
    from dart.ablation import controlled_drift_run, heading_ablation
    truth, gyro = controlled_drift_run(n=200, gyro_bias_deg=0.3, seed=0)   # near-perfect gyro
    res = heading_ablation(truth, gyro, n_keyframes=40, fix_interval=5, fix_sigma_deg=3.0, seed=0)
    assert res["+shadow yaw (SN-03)"] >= res["baseline (gyro only)"]       # honest: shadow doesn't help here


