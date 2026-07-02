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


def test_sn13_preregistered_margin_gate():
    """[REQ:SN-13] SN-13 preregistered acceptance gate ([PROPOSED]): a solar-navigation claim is
    ACCEPTED only if (1) the MEDIAN yaw and/or pose error improves (solar-on vs solar-off) by at
    least its PREREGISTERED margin, (2) tip events do NOT increase, and (3) the energy AND time
    overhead are reported. Every input metric is REAL: yaw from heading_ablation on the documented
    controlled-drift characterization (multiple seeds -> median), pose from factor_ablation on the
    REAL Katwijk dead-reckoning baseline (multiple seeds -> median), tip events from stability()
    over an attitude sweep on the SAME terrain (a heading/pose aid does not reshape the ground), and
    the energy/time overhead from operational_cost (grounded drive + fix energy)."""
    import os

    import numpy as np

    from dart.ablation import (controlled_drift_run, factor_ablation, heading_ablation,
                               preregistered_margin_gate)
    from dart.comparison import operational_cost
    from stewie.physics.stability import stability
    from stewie.specs import ipex_specs as S

    # yaw axis: REAL controlled-drift characterization, median over the preregistered seed set
    yaw_off, yaw_on = [], []
    for seed in range(5):
        truth, gyro = controlled_drift_run(n=200, gyro_bias_deg=15.0, seed=seed)
        r = heading_ablation(truth, gyro, n_keyframes=40, fix_interval=5, fix_sigma_deg=3.0, seed=seed)
        yaw_off.append(r["baseline (gyro only)"]); yaw_on.append(r["+shadow yaw (SN-03)"])
    yaw_off_med, yaw_on_med = float(np.median(yaw_off)), float(np.median(yaw_on))

    # pose axis: REAL Katwijk dead-reckoning vs +absolute fixes, median over seeds
    part = "/mnt/projects/datasets/katwijk/Part1"
    have_katwijk = os.path.isdir(part)
    pose_off_med = pose_on_med = None
    if have_katwijk:
        from stewie.eval import katwijk_baseline as KB
        _t, truth_xy = KB.load_rtk_track(part)
        _td, dr, _yaw = KB._dead_reckon(part, r_wheel=0.123025)
        dr_rs = dr[np.linspace(0, len(dr) - 1, len(truth_xy)).astype(int)]
        pose_off, pose_on = [], []
        for seed in range(5):
            r = factor_ablation(truth_xy, dr_rs, n_keyframes=30, fix_interval=4, fix_sigma_m=2.0, seed=seed)
            pose_off.append(r["baseline (odometry only)"]["abs_max_err_m"])
            pose_on.append(r["+absolute fixes (DEM/shadow)"]["abs_max_err_m"])
        pose_off_med, pose_on_med = float(np.median(pose_off)), float(np.median(pose_on))

    # tip events: stability() over a real pitch sweep; identical solar-off/on (same terrain)
    pitches = np.linspace(0.0, 40.0, 20)
    tip_events = sum(stability(float(p), 0.0, gauge_m=0.57, wheelbase_m=0.40,
                               cg_height_m=0.30)["risk"] == "tip" for p in pitches)

    # energy/time overhead: grounded drive energy + the standstill-fix energy/time of the aid
    oc = operational_cost(n_fixes=10, traverse_m=100.0)
    drive_j = oc["_context"]["drive_energy_J_for_traverse"]
    drive_s = 100.0 / S.DRIVE_SPEED_MS
    extra_j = oc["Navigation"]["extra_mission_energy_J"]
    extra_s = oc["Navigation"]["extra_mission_time_s"]

    solar_off = {"yaw_err_deg": yaw_off_med, "tip_events": tip_events,
                 "energy_j": drive_j, "time_s": drive_s}
    solar_on = {"yaw_err_deg": yaw_on_med, "tip_events": tip_events,
                "energy_j": drive_j + extra_j, "time_s": drive_s + extra_s}
    margins = {"yaw_deg": 3.0}
    if have_katwijk:
        solar_off["pose_err_m"] = pose_off_med
        solar_on["pose_err_m"] = pose_on_med
        margins["pose_m"] = 10.0

    # (e) PASS on a qualifying delta: the real yaw improvement (~6.7 deg) clears the 3 deg margin,
    # tip events do not increase, and the overhead is reported.
    g = preregistered_margin_gate(solar_off, solar_on, margins)
    assert g["passed"] is True
    assert g["margin_met"] is True
    assert g["yaw_improvement"] >= margins["yaw_deg"]
    assert g["tip_events_increased"] is False
    assert g["overhead_reported"] is True
    assert g["energy_overhead"] > 0.0 and g["time_overhead"] > 0.0   # the aid costs real energy/time
    if have_katwijk:
        assert g["pose_improvement"] >= margins["pose_m"]

    # (f1) FAIL when the improvement misses the preregistered margin on every axis
    strict = {"yaw_deg": 100.0}
    if have_katwijk:
        strict["pose_m"] = 1.0e4
    g_miss = preregistered_margin_gate(solar_off, solar_on, strict)
    assert g_miss["passed"] is False
    assert g_miss["margin_met"] is False

    # (f2) FAIL when the aid increases tip events (traded stability for accuracy)
    solar_on_tip = dict(solar_on); solar_on_tip["tip_events"] = tip_events + 1
    g_tip = preregistered_margin_gate(solar_off, solar_on_tip, margins)
    assert g_tip["passed"] is False
    assert g_tip["tip_events_increased"] is True

    # (f3) FAIL when the energy/time overhead is not reported
    solar_on_no_energy = dict(solar_on); solar_on_no_energy.pop("energy_j")
    g_no = preregistered_margin_gate(solar_off, solar_on_no_energy, margins)
    assert g_no["passed"] is False
    assert g_no["overhead_reported"] is False
