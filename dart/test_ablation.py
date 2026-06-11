"""SN ablation: the add-one contribution-attribution core, on the REAL Katwijk baseline."""
import numpy as np

from dart.ablation import _align_ate, factor_ablation


def test_align_ate_zero_for_identical_tracks():
    t = np.cumsum(np.ones((20, 2)), axis=0)
    assert _align_ate(t, t) < 1e-9


def test_absolute_fixes_beat_the_dead_reckoning_baseline():
    """§6.3: adding modelled absolute fixes to the REAL dead-reckoned drift reduces aligned ATE."""
    from stewie.eval import katwijk_baseline as KB
    import os
    part = "/mnt/projects/datasets/katwijk/Part1"
    if not os.path.isdir(part):
        import pytest; pytest.skip("raw Katwijk not present")
    _t, truth = KB.load_rtk_track(part)
    _td, dr, _yaw = KB._dead_reckon(part, r_wheel=0.123025)
    # resample dr onto the truth length (both real tracks)
    dr_rs = dr[np.linspace(0, len(dr) - 1, len(truth)).astype(int)]
    res = factor_ablation(truth, dr_rs, n_keyframes=30, fix_interval=4, fix_sigma_m=2.0, seed=0)
    base_abs = res["baseline (odometry only)"]["abs_max_err_m"]
    fixed_abs = res["+absolute fixes (DEM/shadow)"]["abs_max_err_m"]
    # the contribution: an absolute channel BOUNDS the unbounded dead-reckoning global drift
    assert fixed_abs < base_abs, f"fixes must bound absolute drift: {fixed_abs} !< {base_abs}"
    assert base_abs > 10.0 and fixed_abs < 0.5 * base_abs   # a large, real reduction
    assert res["+absolute fixes (DEM/shadow)"]["n_fixes"] >= 5


def test_more_fixes_do_not_increase_error():
    from stewie.eval import katwijk_baseline as KB
    import os
    part = "/mnt/projects/datasets/katwijk/Part1"
    if not os.path.isdir(part):
        import pytest; pytest.skip("raw Katwijk not present")
    _t, truth = KB.load_rtk_track(part)
    _td, dr, _yaw = KB._dead_reckon(part, r_wheel=0.123025)
    dr_rs = dr[np.linspace(0, len(dr) - 1, len(truth)).astype(int)]
    sparse = factor_ablation(truth, dr_rs, fix_interval=8, fix_sigma_m=2.0, seed=1)["+absolute fixes (DEM/shadow)"]["abs_max_err_m"]
    dense = factor_ablation(truth, dr_rs, fix_interval=3, fix_sigma_m=2.0, seed=1)["+absolute fixes (DEM/shadow)"]["abs_max_err_m"]
    assert dense <= sparse + 1.0   # denser fixes do not make absolute drift worse (within slack)


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
