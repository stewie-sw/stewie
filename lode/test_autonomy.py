"""TDD for the closed-loop autonomy estimator (P12) — the AutoNav "OD" analog.

A recursive belief-state estimator with uncertainty: `predict` is the dead-reckoning/process step
(uncertainty GROWS with distance/energy spent), `update_*` fuse a measurement via a scalar Kalman update
(uncertainty SHRINKS). The loop replans against this ESTIMATE, not assumed-perfect state. Measurements in
these tests come from the real drum-sensor uncertainty model + a real conserved-authority cut — not fabricated.
"""

from __future__ import annotations

import math

import pytest

from lode import mission_planner as MP


def _mission():
    return MP.mission_from_dict({"name": "a", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
        {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]})


def test_initial_belief_starts_at_charger_full_and_known():
    from lode import autonomy as A
    b = A.initial_belief(_mission(), tasks_total=2)
    assert (b.x, b.y) == (0.0, 0.0)
    assert math.isclose(b.soc_frac(), 1.0) and b.drum_kg == 0.0
    assert b.tasks_done == 0 and b.tasks_total == 2
    assert b.pos_sigma_m >= 0.0 and b.energy_sigma_J == 0.0


def test_kf_update_reduces_variance_and_weights_by_precision():
    from lode import autonomy as A
    mu, var = A._kf_update(10.0, 4.0, 20.0, 4.0)              # equal precision -> midpoint, variance halves
    assert math.isclose(mu, 15.0) and var < 4.0
    mu2, var2 = A._kf_update(10.0, 100.0, 20.0, 1.0)          # trust the precise measurement
    assert mu2 > 19.0 and var2 < 1.0
    assert A._kf_update(5.0, math.inf, 7.0, 2.0) == (7.0, 2.0)  # no prior -> take the measurement


def test_predict_grows_uncertainty_and_moves_state():
    from lode import autonomy as A
    b = A.initial_belief(_mission(), 2)
    b2 = A.predict(b, moved_to=(200.0, 0.0), drive_m=200.0, energy_spent_J=0.6e6)
    assert (b2.x, b2.y) == (200.0, 0.0)
    assert b2.pos_sigma_m > b.pos_sigma_m                     # odometry drift grows pose uncertainty
    assert b2.energy_J < b.energy_J and b2.energy_sigma_J > 0.0   # spent energy + model uncertainty


def test_drum_measurement_shrinks_uncertainty_and_brackets_truth():
    from lode import autonomy as A
    import numpy as np
    from stewie.physics.column_state import ColumnState
    # true drum mass from a REAL cut of real-density regolith (no fabricated value)
    cs = ColumnState(width=10, height=10, cell_m=0.5, mass_areal=np.full((10, 10), 1920.0 * 10.0))
    mask = np.zeros((10, 10), bool); mask[5, 5] = True
    true_kg = cs.cut_to_inventory(mask, 0.05 * 1920.0)
    assert true_kg > 0.0
    reading_sigma = MP.RM.FDC_MPE_HALF_FULL * true_kg         # real published sensor uncertainty (2.56%)
    b = A.initial_belief(_mission(), 2)
    b = A.predict(b, drum_delta_kg=true_kg, drum_process_sigma_kg=MP.DRUM_KG)  # process: large drum uncertainty
    s0 = b.drum_sigma_kg
    b = A.update_drum(b, reading_kg=true_kg, reading_sigma_kg=reading_sigma)
    assert b.drum_sigma_kg < s0                               # measurement shrinks uncertainty
    assert abs(b.drum_kg - true_kg) <= 2.0 * b.drum_sigma_kg  # estimate brackets truth (AutoNav consistency)


def test_pose_fix_shrinks_position_uncertainty():
    from lode import autonomy as A
    b = A.initial_belief(_mission(), 2)
    b = A.predict(b, moved_to=(300.0, 0.0), drive_m=300.0)    # pose uncertainty grew with distance
    s0 = b.pos_sigma_m
    b = A.update_pose(b, fix_xy=(298.0, 1.0), fix_sigma_m=1.0)  # a 1 m pose fix (e.g. landmark/map match)
    assert b.pos_sigma_m < s0 and abs(b.x - 298.0) < s0        # fix pulls the estimate + shrinks sigma


# ---- executor + controller: the closed loop (plan -> execute -> sense -> estimate -> replan) -----
def _spread():
    return MP.mission_from_dict({"name": "c", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut A", "kind": "cut", "x": 120, "y": 0, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "cut B", "kind": "cut", "x": -110, "y": 10, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "fill C", "kind": "fill", "x": 0, "y": 130, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "fill D", "kind": "fill", "x": 140, "y": 30, "footprint_m2": 16, "depth_m": 0.05}]})


def test_execute_leg_truth_is_at_least_the_nominal_plan():
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    m = _spread()
    trips, _, _, _ = MP._build_trips(m, dem, o, 25.0)
    b = A.initial_belief(m, len(trips))
    leg = trips[0]
    t = A.execute_leg(b, leg, dem=dem, dem_origin=o, body="moon")
    nom = A.nominal_leg_energy_J((b.x, b.y), leg)
    assert t["drive_m"] > 0.0
    assert t["true_energy_J"] >= nom - 1e-6                    # slip + gravity climb only ADD to the flat plan
    assert 0.0 <= t["slip"] < 1.0


def test_closed_loop_completes_and_manages_the_battery():
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o, algorithm="nearest", objective="time")
    assert r["completed"] is True
    assert r["belief"].tasks_done == r["belief"].tasks_total == r["n_trips"]
    assert r["belief"].energy_J >= 0.0                         # never depleted — recharges before reserve
    assert r["recharges"] >= 1                                 # the loop actually managed the battery
    assert all(-1e-9 <= L["soc"] <= 1.0001 for L in r["legs"])


def test_closed_loop_reports_the_map_channel_reward():
    # P6 / LAC section 10: the loop now closes the map-channel reward -- the executed route's worksite
    # coverage + residual map uncertainty are fed back, and digs are gated on local map coverage.
    from lode import autonomy as A
    from dart import map_channel as MC
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o, algorithm="nearest", objective="time")
    mc = r["map_channel"]
    assert 0.0 < mc["coverage"] <= 1.0                        # the route observed some of the worksite
    assert MC.ONBOARD_STEREO_SIGMA_M <= mc["mean_uncertainty_m"] <= MC.PRIOR_SIGMA_M
    assert isinstance(r["map_observe_more"], int) and r["map_observe_more"] >= 0
    assert mc["dense_rmse_available"] is False                # dense reconstruction RMSE is the gated tier


def test_true_drain_never_below_nominal_and_uncertainty_grows():
    # AutoNav model-vs-truth: the slip-adjusted truth is never cheaper than the flat nominal plan, and the
    # estimate carries growing uncertainty (the loop replans against the estimate, not assumed-perfect state).
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o)
    tot_true = sum(L["true_J"] for L in r["legs"])
    tot_nom = sum(L["nominal_J"] for L in r["legs"])
    assert tot_true >= tot_nom - 1e-6
    # pose uncertainty grows monotonically with travel (dead-reckoning, never reset); energy sigma is
    # legitimately reset to 0 by a full recharge, so it's not a reliable end-of-run signal.
    assert r["belief"].pos_sigma_m > 0.0
    assert max(L["energy_sigma_J"] for L in r["legs"]) > 0.0    # energy uncertainty WAS carried in the loop


def test_perception_in_the_loop_bounds_pose_uncertainty():
    # with a per-leg map/landmark pose fix, the dead-reckoning drift is BOUNDED (vs growing without it),
    # and the result stays below the dig-ready gate. Perception is now folded into the loop.
    from lode import autonomy as A
    dem = MP.load_haworth_dem()
    o = MP.flattest_anchor(dem)
    off = A.run_closed_loop(_spread(), dem=dem, dem_origin=o)                      # perception OFF (dead-reckoning)
    on = A.run_closed_loop(_spread(), dem=dem, dem_origin=o,                       # perception ON
                           perception_sigma_m=0.10, dig_sigma_gate_m=0.20)
    assert on["belief"].pos_sigma_m < off["belief"].pos_sigma_m                    # fixes bound the drift
    assert on["belief"].pos_sigma_m <= 0.20 + 1e-6                                 # below the dig-ready gate
    assert on["perception_fixes"] >= 1 and on["observe_more"] >= 0
    assert on["completed"] is True


def test_pose_fix_corrects_the_mean_not_just_sigma():
    # Bug #2 fix: with an INDEPENDENT true-pose fix the corrected belief MEAN moves toward truth -- the old
    # code fused the estimate against itself (measurement == estimate -> mean unchanged, only sigma shrank).
    # A-03: the canonical plant drives HOME at mission end (consistent location), so the observable mean
    # correction is the charger DOCK fix: with perception the believed end mean collapses onto the true
    # charger AND its sigma shrinks far below the dead-reckoning run. Both effects (mean + sigma) are real.
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    m = MP.mission_from_dict({"name": "t", "body": "moon", "charger": [0, 0],
                              "orders": [{"action": "c", "kind": "cut", "x": 6, "y": 0,
                                          "footprint_m2": 9, "depth_m": 0.02}]})
    off = A.run_closed_loop(m, dem=dem, dem_origin=o)
    on = A.run_closed_loop(m, dem=dem, dem_origin=o, perception_sigma_m=0.05)
    assert off["recharges"] == 0 and on["recharges"] == 0                          # tiny mission, no recharge
    assert (on["belief"].x, on["belief"].y) != (off["belief"].x, off["belief"].y)  # the fix moved the mean
    # the dock fix pulls the believed end mean onto the TRUE charger (0,0); dead-reckoning drifts off it
    assert abs(on["belief"].x - 0.0) < abs(off["belief"].x - 0.0)                  # ...toward the truth
    assert on["belief"].pos_sigma_m < off["belief"].pos_sigma_m                    # ...and shrinks sigma


def test_map_channel_gate_is_an_action_not_just_a_counter():
    # Bug #1 fix: an under-mapped dig triggers a survey dwell that COSTS real mission time (not only a
    # counter). survey_time_s == map_observe_more * OBSERVE_DWELL_S, and it is > 0 on a spread mission.
    from lode import autonomy as A
    from dart import map_channel as MC
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o, algorithm="nearest", objective="time")
    assert r["map_observe_more"] >= 1                                              # under-mapped digs surveyed
    assert r["survey_time_s"] == pytest.approx(r["map_observe_more"] * MC.OBSERVE_DWELL_S)
    assert r["survey_time_s"] > 0.0


# ---- A-03: the closed loop is ONE executive, consistent with the canonical planner --------------------
def test_closed_loop_uses_the_canonical_plan_order_and_context():
    # A-03 remediation: the closed loop must NOT re-derive the plan with its own globals. It must drive
    # the SAME canonical trip order the planner produced, and surface the canonical Plan IR so the two are
    # provably the same plan (no second inconsistent mission simulator).
    from lode import autonomy as A
    m = _spread()
    trips, _flows, _per, _tl, _tot = MP.plan_and_simulate(m, algorithm="nearest", objective="time")
    canonical_labels = [t["label"] for t in trips]
    r = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time")
    # the loop executed exactly the canonical visit order (same trips, same sequence)
    assert [L["leg"] for L in r["legs"]] == canonical_labels
    # and it reports the canonical Plan IR / provenance so consumers see one plan, not two
    assert "plan_ir" in r and r["plan_ir"]["actions"], "closed loop must surface the canonical Plan IR"
    assert r["plan_ir"]["provenance"]["input_sha256"], "Plan IR must carry the canonical provenance hash"


def test_closed_loop_agrees_with_planner_simulation_zero_noise():
    # A-03 VERIFICATION: for deterministic zero-noise inputs (flat / no-DEM -> slip 0, no elevation gain,
    # no perception noise), the closed-loop execution must AGREE with the canonical planner simulation
    # within a declared tolerance on energy, time, and recharge count -- it is the same plant, not a
    # second simulator. The OLD code disagreed (free recharge travel made the loop ~0.6% too cheap and it
    # tracked zero mission time), so this test is RED until the loop is driven from the canonical services.
    from lode import autonomy as A
    m = _spread()
    _trips, _flows, _per, _tl, totals = MP.plan_and_simulate(m, algorithm="nearest", objective="time")
    r = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time")
    assert r["completed"] is True
    # energy: the closed loop's TOTAL accounted plant energy (drive + recharge round-trips + work) must
    # match the canonical reserve-aware ledger to a tight tolerance. A loop that recharges for free is
    # systematically CHEAPER than the canonical sim and fails this.
    assert r["plant_energy_J"] == pytest.approx(totals["energy_J"], rel=1e-6)
    # time: the closed loop must accumulate the same mission time the canonical sim does (the old loop
    # reported t_s == 0). recharges add the charger round-trip drive + the refill duration.
    assert r["plant_time_s"] == pytest.approx(totals["time_s"], rel=1e-6)
    # recharge count agrees with the canonical battery-aware schedule (no impossible extra/missing charges)
    assert r["recharges"] == totals["charges"]


def test_closed_loop_recharge_travel_is_not_free():
    # A-03: "remove the knowingly-free recharge travel and account for return-to-site travel." A recharge
    # is a real round trip: drive to the charger (costs energy + time), refill, drive back to resume work.
    # The canonical sim charges all of that. A free-teleport recharge would make plant energy/time UNDER
    # the canonical ledger; assert the loop's recharge accounting is energy-consistent leg by leg.
    from lode import autonomy as A
    m = _spread()
    _t, _f, _p, _tl, totals = MP.plan_and_simulate(m, algorithm="nearest", objective="time")
    r = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time")
    assert r["recharges"] >= 1
    # the recharge travel energy is strictly positive (sites are far from the charger -> the return trip
    # costs real energy); a free teleport would report zero recharge-travel energy.
    assert r["recharge_travel_J"] > 0.0
    # energy conservation of the accounted plant: drive + recharge-travel + work + refill-free-energy must
    # reconcile with the canonical total (refill restores the pack, it is not a CONSUMED term).
    assert r["plant_energy_J"] == pytest.approx(totals["energy_J"], rel=1e-6)


def test_closed_loop_belief_is_an_overlay_not_a_separate_plant():
    # A-03: belief estimation is an OVERLAY on the canonical plant, not a duplicate plant. With zero
    # measurement noise and no DEM the believed end state must coincide with the canonical plant end
    # state: the rover ends at the charger (the canonical sim drives home), pack full after the final
    # charge or with the canonical remaining SoC, and all tasks done. The belief must not invent a
    # location/energy the plant never had.
    from lode import autonomy as A
    m = _spread()
    _t, _f, _p, _tl, totals = MP.plan_and_simulate(m, algorithm="nearest", objective="time")
    # dead-reckoning (no perception): the believed end pose brackets the TRUE plant end pose (the charger)
    # within the pose uncertainty -- the overlay estimate is consistent with the plant, not a separate one.
    r = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time")
    b = r["belief"]
    assert abs(b.x - m.charger[0]) <= 2.0 * b.pos_sigma_m + 1e-6
    assert abs(b.y - m.charger[1]) <= 2.0 * b.pos_sigma_m + 1e-6
    assert b.tasks_done == b.tasks_total == r["n_trips"]
    # the believed mission time equals the canonical plant time (overlay does not alter the plant)
    assert b.t_s == pytest.approx(totals["time_s"], rel=1e-6)
    # with a perception dock fix the believed end pose collapses onto the charger (known landmark): the
    # Kalman fusion pulls the mean to within a few perception-sigma of truth and shrinks its uncertainty.
    on = A.run_closed_loop(m, dem=None, dem_origin=(0.0, 0.0), algorithm="nearest", objective="time",
                           perception_sigma_m=0.05)
    assert abs(on["belief"].x - m.charger[0]) <= 3.0 * 0.05
    assert abs(on["belief"].y - m.charger[1]) <= 3.0 * 0.05
    assert on["belief"].pos_sigma_m < b.pos_sigma_m       # dock fix shrinks uncertainty vs dead-reckoning


def _veh_mission(name):
    return MP.mission_from_dict({"name": "v", "body": "moon", "charger": [0, 0], "vehicle": name,
                                 "orders": [{"action": "cut", "kind": "cut", "x": 20, "y": 0,
                                             "footprint_m2": 20, "depth_m": 0.05}]})


def test_execute_leg_caps_haul_at_the_selected_vehicles_drum():
    """MODEL-01: a 60 kg haul is capped at the SELECTED vehicle's drum -- 30 kg on ipex, the full 60 kg
    on rassor2 (80 kg drum). The closed-loop overlay must price the leg with the vehicle's
    PlanningContext, not the global IPEx DRUM_KG (which would cap every vehicle at 30)."""
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    leg = {"site": (5.0, 0.0), "mass": 60.0, "kind": "cutfill"}
    b = A.initial_belief(_veh_mission("ipex"), 1)
    t_ipex = A.execute_leg(b, leg, dem=dem, dem_origin=o, body="moon",
                           ctx=MP.plan_context(_veh_mission("ipex")))
    t_rassor = A.execute_leg(b, leg, dem=dem, dem_origin=o, body="moon",
                             ctx=MP.plan_context(_veh_mission("rassor2")))
    assert math.isclose(t_ipex["haul_mass_capped_kg"], 30.0), t_ipex["haul_mass_capped_kg"]
    assert math.isclose(t_rassor["haul_mass_capped_kg"], 60.0), t_rassor["haul_mass_capped_kg"]


def test_initial_belief_threads_the_vehicle_pack_into_soc():
    """MODEL-01: the SOC denominator is the SELECTED vehicle's pack (via PlanningContext), not the global
    IPEx BATTERY_J. A fresh belief is full (soc 1.0) and its energy equals the vehicle's battery."""
    from lode import autonomy as A
    for name in ("ipex", "rassor2"):
        ctx = MP.plan_context(_veh_mission(name))
        b = A.initial_belief(_veh_mission(name), 1)
        assert math.isclose(b.energy_J, ctx.battery_j)
        assert math.isclose(b.soc_frac(), 1.0)


def test_perception_fix_is_real_deterministic_terrain_match():
    """The perception fix is now REAL terrain-relative localization (dem_position_fix scan-match) + the
    charger-dock known-landmark fix -- NOT the old `true_pose + N(0,sigma)` seeded stand-in. So it is
    DETERMINISTIC (no measurement-noise RNG): different seeds give the SAME corrected belief. And it is a
    real fix: perception-on bounds the drift below the perception-off dead-reckoning run. (This replaces
    test_perception_fix_injects_seeded_measurement_noise, which asserted the removed truth+noise fake.)"""
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    m = _spread()
    a = A.run_closed_loop(m, dem=dem, dem_origin=o, perception_sigma_m=0.10, seed=1)
    b = A.run_closed_loop(m, dem=dem, dem_origin=o, perception_sigma_m=0.10, seed=2)
    off = A.run_closed_loop(m, dem=dem, dem_origin=o)                          # perception OFF
    assert (a["belief"].x, a["belief"].y) == (b["belief"].x, b["belief"].y)   # deterministic real fix, not seeded noise
    assert a["perception_fixes"] >= 1                                          # real dem-fix and/or the dock fix
    assert a["belief"].pos_sigma_m < off["belief"].pos_sigma_m                 # the fix bounds the drift


def test_dem_terrain_fix_recovers_drifted_pose_and_abstains_on_flat():
    """The new _dem_terrain_fix: on the REAL Haworth DEM a drifted guess is pulled back toward the true
    cell by matching the observed patch (terrain-relative localization, NOT being told the truth); a flat
    synthetic patch returns None (a featureless region must not manufacture a fix -- odometry carries)."""
    import numpy as np

    from lode import autonomy as A
    dem = MP.load_haworth_dem(); cell = dem[1]
    o = MP.flattest_anchor(dem)                                # order-frame origin in DEM metres
    # pick a true pose a few cells off the anchor in a feature-bearing direction; drift the guess by ~3 cells
    true_xy = (40.0, 30.0)
    guess_xy = (true_xy[0] + 3.0 * cell, true_xy[1] - 2.0 * cell)
    fix = A._dem_terrain_fix(dem, o, true_xy, guess_xy, 2.0)
    if fix is not None:                                        # confident match -> recovered nearer the truth
        err_fix = np.hypot(fix["xy"][0] - true_xy[0], fix["xy"][1] - true_xy[1])
        err_guess = np.hypot(guess_xy[0] - true_xy[0], guess_xy[1] - true_xy[1])
        assert err_fix <= err_guess                            # the scan-match corrected the drift
    # a perfectly flat DEM is unregisterable -> None (no manufactured fix)
    flat = (np.zeros((400, 400)), float(cell))
    assert A._dem_terrain_fix(flat, (0.0, 0.0), (100.0, 100.0), (100.0 + 2 * cell, 100.0), 2.0) is None


def test_beacon_fix_recovers_in_range_grows_with_range_and_abstains_far():
    """Slice 1b: the lander/charger AprilTag BEACON fix gives a real feature-based fix on the FLAT work
    area where terrain scan-match abstains. Near-truth + tight close, sigma grows with range, deterministic
    (no seed), and None beyond fiducial-detection range (then odometry carries)."""
    from lode import autonomy as A
    beacon = (0.0, 0.0)
    close = A._beacon_fix(beacon, (10.0, 0.0))
    far = A._beacon_fix(beacon, (50.0, 0.0))
    assert close is not None and far is not None
    assert abs(close["xy"][0] - 10.0) < 1.0 and abs(close["xy"][1]) < 1.0    # recovers near the true pose
    assert far["sigma"] > close["sigma"]                                     # AprilTag accuracy degrades with range
    assert A._beacon_fix(beacon, (10.0, 0.0)) == close                       # deterministic (no seeded RNG)
    assert A._beacon_fix(beacon, (5000.0, 0.0)) is None                      # out of detection range -> no fix
    # NON-COLLAPSE: prove the recovered mean is NOT the exact truth (the docstring's claim). On-axis nice
    # ranges land on the pixel grid (r_q == rng) and pass through truth exactly, so assert off-axis where
    # the quantization carries a real sub-pixel detection error.
    import math as _m
    off = A._beacon_fix(beacon, (23.7, 11.1))
    err = _m.hypot(off["xy"][0] - 23.7, off["xy"][1] - 11.1)
    assert 0.0 < err < 0.5, f"beacon fix mean must carry a real (non-zero, bounded) detection error, got {err}"


def test_closed_loop_falls_back_to_lander_beacon_when_terrain_abstains(monkeypatch):
    """Slice 1b INTEGRATION: when the DEM scan-match abstains (forced None, i.e. the flat work area),
    run_closed_loop falls back to the lander BEACON fix -- honoring mission.lander over the charger -- and
    the believed pose stays bounded. Pins the live _dem_terrain_fix->None -> line-346 lander selection ->
    _beacon_fix -> belief chain that the offline suite never reaches (Haworth's anchor always returns a fix)."""
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    monkeypatch.setattr(A, "_dem_terrain_fix", lambda *a, **k: None)            # force the flat-area branch
    seen, real_beacon = [], A._beacon_fix
    monkeypatch.setattr(A, "_beacon_fix",
                        lambda beacon, tp, **k: (seen.append(beacon), real_beacon(beacon, tp, **k))[1])
    m = MP.mission_from_dict({"name": "t", "body": "moon", "charger": [0, 0], "lander": [5, 5],
                              "orders": [{"action": "c", "kind": "cut", "x": 8, "y": 2,
                                          "footprint_m2": 9, "depth_m": 0.02}]})
    r = A.run_closed_loop(m, dem=dem, dem_origin=o, perception_sigma_m=0.10)
    assert seen and all(b == (5.0, 5.0) for b in seen)                         # beacon fired; lander beat the charger
    assert r["perception_fixes"] >= 1                                          # arrived via the beacon path
    assert r["belief"].pos_sigma_m <= 0.20 + 1e-6                              # drift bounded below the dig gate


def test_perception_fixes_count_is_exact_not_just_nonzero():
    """Pin the perception_fixes KPI exactly (plan.py surfaces it as BOTH perception_fixes and map_fixes).
    On _spread()+Haworth perception-on, the deterministic count is the confident per-leg DEM fixes plus the
    one charger dock; a >=1 floor can't catch an off-by-one / double-count in the accounting (autonomy.py
    per-leg + dock increments). Pinned so a future change to fix-counting fails loudly."""
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o, perception_sigma_m=0.10)
    assert r["perception_fixes"] == 5, f"expected 4 DEM fixes + 1 dock = 5, got {r['perception_fixes']}"


def test_closed_loop_legs_carry_localization_trace_for_the_cockpit():
    """Frontend tie-in: run_closed_loop's per-leg records carry the est-vs-truth localization trace the
    cockpit Navigation pane renders -- believed (bx,by) vs true (tx,ty) pose, pos_sigma_m, and which real
    fix corrected the leg (dem / beacon / none). Pins the contract /plan's perception.localization is built
    from."""
    from lode import autonomy as A
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o, perception_sigma_m=0.10)
    assert r["legs"], "no legs"
    for leg in r["legs"]:
        for k in ("bx", "by", "tx", "ty", "pos_sigma_m", "fix"):
            assert k in leg, f"leg missing localization field {k!r}"
        assert leg["fix"] in ("dem", "beacon", "none")
    assert any(leg["fix"] == "dem" for leg in r["legs"])      # the Haworth anchor has terrain -> real DEM fixes


def test_legs_carry_classified_faults_for_the_watchdog():
    """#269 WMDT-L4: run_closed_loop must attach a `faults` list to every leg (classify_faults of that
    leg's executed slip / soc / pos_sigma_m), so run_sim_execution's watchdog can reach SAFED on a real
    entrapment / low-energy / localization-divergence event. Pre-#269 NO leg carried a `faults` key, so
    leg.get('faults') was always [] and the cascade could never fire. Real Haworth mission, no synthetic."""
    from lode import autonomy as A
    from lode.faults import classify_faults
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    r = A.run_closed_loop(_spread(), dem=dem, dem_origin=o, algorithm="nearest", objective="time")
    assert r["legs"], "no legs produced"
    for leg in r["legs"]:
        assert isinstance(leg.get("faults"), list), "leg missing the classified faults list (#269)"
        # the attached faults must reflect THIS leg's own executed telemetry (slip / soc / pos_sigma_m)
        exp = classify_faults(slip=float(leg["slip"]), battery_frac=float(leg["soc"]),
                              loc_sigma_m=float(leg["pos_sigma_m"]))
        assert sorted(f["fault"] for f in leg["faults"]) == sorted(f["fault"] for f in exp), \
            f"attached faults inconsistent with leg telemetry: {leg['faults']} vs {exp}"
