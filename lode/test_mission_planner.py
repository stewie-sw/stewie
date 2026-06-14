"""P1 round-trip tests (TDD): build-order queue -> mission_planner adapter -> mission-control report,
and the local /plan server that wires the browser to it.

planet_browser/ is standalone; these run under the runtime venv (numpy + matplotlib). They use the REAL
bodies.json + the real grounded planner (no synthetic constants) and a small REAL mission fixture
(two orders on the Moon). Host-runnable via pytest:

    cd planet_browser && PYTHONPATH=. <venv>/bin/python -m pytest test_mission_planner.py -q
"""
from __future__ import annotations

import math
import os

import pytest
from fastapi.testclient import TestClient

from lode import mission_planner as MP
from stewie.server import server as SRV

HERE = os.path.dirname(os.path.abspath(__file__))


def _payload(orders=None, body="moon", name="Test Site"):
    if orders is None:
        orders = [
            {"action": "Level pad", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
            {"action": "Build berm", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10},
        ]
    return {"name": name, "body": body, "charger": [0, 0], "orders": orders}


# ---- mission_from_dict (the browser-queue -> Mission adapter) ------------------------------------
def test_mission_from_dict_roundtrips():
    m = MP.mission_from_dict(_payload())
    assert isinstance(m, MP.Mission)
    assert m.body == "moon" and m.name == "Test Site" and m.charger == (0.0, 0.0)
    assert [o.kind for o in m.orders] == ["cut", "fill"]
    assert m.orders[0].footprint_m2 == 36.0 and m.orders[0].depth_m == 0.04


def test_mission_from_dict_rejects_unknown_body():
    with pytest.raises(ValueError, match="body"):
        MP.mission_from_dict(_payload(body="pluto"))


def test_mission_from_dict_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        MP.mission_from_dict(_payload(orders=[
            {"action": "x", "kind": "teleport", "x": 1, "y": 1, "footprint_m2": 1, "depth_m": 0.1}]))


def test_mission_from_dict_requires_fields():
    with pytest.raises(ValueError, match="missing"):
        MP.mission_from_dict(_payload(orders=[{"action": "x", "kind": "cut", "x": 1, "y": 1}]))


def test_mission_from_dict_requires_orders():
    with pytest.raises(ValueError, match="orders"):
        MP.mission_from_dict({"name": "x", "body": "moon", "orders": []})


def test_mission_from_dict_rejects_bad_physical_domains():
    # [REQ:CT-01] public numeric inputs enforce finiteness + physical domains
    # RB-01: this public input boundary rejects NaN/Inf coords and non-positive footprint/depth
    # (float() alone accepts NaN/Inf; a negative depth or zero area is physically meaningless).
    def _o(**kw):
        base = {"action": "x", "kind": "cut", "x": 1.0, "y": 1.0, "footprint_m2": 10.0, "depth_m": 0.1}
        base.update(kw)
        return [base]
    for bad in (_o(x=float("nan")), _o(y=float("inf")), _o(depth_m=-0.1),
                _o(depth_m=0.0), _o(footprint_m2=0.0), _o(footprint_m2=-5.0)):
        with pytest.raises(ValueError):
            MP.mission_from_dict(_payload(orders=bad))
    with pytest.raises(ValueError):                       # NaN charger coordinate
        MP.mission_from_dict({**_payload(), "charger": [float("nan"), 0.0]})


# ---- run() on a queued mission writes a REAL pdf + md, balanced ----------------------------------
def test_queued_mission_balances_and_writes_pdf():
    # [REQ:CP-02] cut/fill balanced by mass under drum/capacity constraints
    m = MP.mission_from_dict(_payload())
    pdf, md, totals = MP.run(m, stem="pytest-roundtrip")
    assert os.path.isfile(pdf) and os.path.isfile(md)
    with open(pdf, "rb") as f:
        assert f.read(5) == b"%PDF-"                       # a real PDF, not an empty/placeholder file
    assert totals["cut_kg"] > 0 and totals["fill_kg"] > 0  # both order classes present
    assert abs(totals["cut_kg"] - totals["fill_kg"]) < totals["cut_kg"]  # fill drawn from cut, balanced-ish


def test_run_unique_stem_no_overwrite():
    p1, _, _ = MP.run(MP.mission_from_dict(_payload(name="A")), stem="pytest-A")
    p2, _, _ = MP.run(MP.mission_from_dict(_payload(name="B")), stem="pytest-B")
    assert p1 != p2 and os.path.isfile(p1) and os.path.isfile(p2)


# ---- sinter stays gated through the adapter ------------------------------------------------------
def test_sinter_order_still_refused():
    # [REQ:CP-10] sinter unavailable for baseline IPEx (gated, capability-qualified only)
    sinter_order = [{"action": "Sinter apron", "kind": "sinter", "x": 10, "y": 10,
                     "footprint_m2": 9, "depth_m": 0.01}]
    # capability gate: the default IPEx drum excavator has no sinter tool -> refused at mission_from_dict
    with pytest.raises(ValueError, match="GATED OFF"):
        MP.mission_from_dict(_payload(orders=sinter_order))
    # numbers gate: with the separate sinter tool mounted the capability is satisfied, but plan_and_simulate
    # still refuses while constants.SINTER_ENABLED is False ([CALIB] energy/density not sourced)
    m = MP.mission_from_dict(_payload(orders=sinter_order) | {"tools": ["sinter"]})
    with pytest.raises(RuntimeError, match="GATED OFF"):
        MP.plan_and_simulate(m)


# ---- I8: validate the plan on the conserved authority (column_state) ----------------------------
def test_validate_plan_conserves_mass_and_is_feasible():
    from leap import structures as ST
    m = MP.mission_from_dict({"name": "Pad", "body": "moon", "charger": [0, 0],
                              "orders": ST.decompose("landing_pad", 40.0, 30.0)})
    v = MP.validate_plan(m)
    assert v["mass_conserved"] is True and v["feasible"] is True
    # the conserved authority actually moves ~ the planned bank cut and loose fill (material available)
    assert math.isclose(v["executed_cut_kg"], v["planned_cut_kg"], rel_tol=0.05)
    assert math.isclose(v["executed_fill_kg"], v["planned_fill_kg"], rel_tol=0.05)


def test_validate_plan_small_footprint_not_falsely_infeasible():
    # a small fill (6 m^2) the drum can easily supply must read feasible; feasibility means material-
    # limited, NOT that a sub-meter footprint under-covers the 0.5 m grid. (Regression: I8 compared an
    # analytic planned mass to a rasterized executed mass, so small footprints tripped the gate falsely.)
    m = MP.mission_from_dict({"name": "small", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 16.0, "depth_m": 0.04},
        {"action": "fill", "kind": "fill", "x": 10.0, "y": 10.0, "footprint_m2": 6.0, "depth_m": 0.05}]})
    v = MP.validate_plan(m)                       # flat scene, no DEM -> only the mass/feasibility check
    assert v["mass_conserved"] is True and v["feasible"] is True


def test_validate_plan_flags_drum_undersupply():
    # the gate must still fire for a GENUINE under-supply: a big fill drawing on a tiny cut empties the
    # drum far short of the plan -> infeasible (distinct from the small-footprint discretization case).
    m = MP.mission_from_dict({"name": "starved", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 4.0, "depth_m": 0.04},
        {"action": "fill", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 100.0, "depth_m": 0.30}]})
    v = MP.validate_plan(m)
    assert v["feasible"] is False and v["drum_remaining_kg"] < 1.0      # drum ran dry, fill far short


def test_validate_plan_flags_infeasible_deep_cut():
    # a cut deeper than the regolith mantle floors at the datum -> the authority cannot move it -> infeasible
    m = MP.mission_from_dict({"name": "deep", "body": "moon", "charger": [0, 0],
                              "orders": [{"action": "too deep", "kind": "cut", "x": 0.0, "y": 0.0,
                                          "footprint_m2": 9.0, "depth_m": 50.0}]})
    v = MP.validate_plan(m, regolith_depth_m=10.0)
    assert v["feasible"] is False


def test_validate_plan_slope_gate_on_real_haworth_dem():
    # I6: against the REAL Haworth DEM, a pad on a flat spot is feasible; on a steep crater wall it is
    # rejected for slope. Uses the rare-flattest and steepest real cells (no synthetic terrain).
    import numpy as np
    dem = MP.load_haworth_dem()                       # (Z, cell_m) — real LOLA Haworth 5 m
    Z, cell = dem
    smap = MP.slope_deg_map(Z, cell)
    flat_rc = np.unravel_index(int(np.argmin(smap)), smap.shape)
    steep_rc = np.unravel_index(int(np.argmax(smap)), smap.shape)

    def pad_at(rc):
        x, y = rc[1] * cell, rc[0] * cell             # col -> x, row -> y (DEM meters)
        return MP.mission_from_dict({"name": "p", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "pad", "kind": "cut", "x": x, "y": y, "footprint_m2": 36, "depth_m": 0.05}]})

    vf = MP.validate_plan(pad_at(flat_rc), dem=dem, max_slope_deg=15.0)
    vs = MP.validate_plan(pad_at(steep_rc), dem=dem, max_slope_deg=15.0)
    assert vf["feasible"] is True and not vf["slope_violations"]
    assert vs["feasible"] is False and vs["slope_violations"]


def test_flattest_anchor_finds_a_buildable_spot():
    # M11: auto-find a flat buildable region on the (mostly-steep) Haworth DEM
    import numpy as np
    dem = MP.load_haworth_dem()
    Z, cell = dem
    ax, ay = MP.flattest_anchor(dem, window_m=20.0)
    smap = MP.slope_deg_map(Z, cell)
    col, row = int(ax / cell), int(ay / cell)
    assert smap[row, col] < float(np.median(smap))    # anchor is flatter than typical Haworth


def test_validate_plan_anchored_to_dem_origin():
    # M11: the order LOCAL frame is anchored to a DEM site via dem_origin -> the slope gate fires on the
    # actual anchored terrain. Same pad: feasible at the flat anchor, rejected at the steepest cell.
    import numpy as np
    dem = MP.load_haworth_dem()
    Z, cell = dem
    pad = MP.mission_from_dict({"name": "p", "body": "moon", "charger": [0, 0],
        "orders": [{"action": "pad", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 16.0, "depth_m": 0.04}]})
    flat = MP.flattest_anchor(dem, window_m=20.0)
    vf = MP.validate_plan(pad, dem=dem, dem_origin=flat, max_slope_deg=15.0)
    sr = np.unravel_index(int(np.argmax(MP.slope_deg_map(Z, cell))), Z.shape)
    vs = MP.validate_plan(pad, dem=dem, dem_origin=(sr[1] * cell, sr[0] * cell), max_slope_deg=15.0)
    assert vf["feasible"] is True
    assert vs["feasible"] is False and vs["slope_violations"]


def test_h12_planner_refuses_microgravity_soil_override():
    """Audit H-12 (2026-06-13): the planner's quantitative soil path must REFUSE a microgravity soil
    override (Bennu/Phobos) -- it would otherwise silently use lunar analog Bekker moduli as if they were
    predictive. A gravity-loaded soil resolves normally."""
    import pytest
    m = MP.mission_from_dict({"name": "m", "body": "moon", "soil": "bennu", "charger": [0, 0],
        "orders": [{"action": "cut", "kind": "cut", "x": 10, "y": 10, "footprint_m2": 9, "depth_m": 0.02}]})
    with pytest.raises(ValueError, match="OUT OF REGIME"):
        MP.mission_soil_params(m)
    ok = MP.mission_from_dict({"name": "m", "body": "moon", "soil": "mars", "charger": [0, 0],
        "orders": [{"action": "cut", "kind": "cut", "x": 10, "y": 10, "footprint_m2": 9, "depth_m": 0.02}]})
    assert MP.mission_soil_params(ok) is not None                   # gravity-loaded soil resolves


def test_h08_off_dem_order_footprint_fails_acceptance():
    """Audit H-08 (2026-06-13): an order whose footprint leaves the DEM bounds must be REJECTED (validate
    the full footprint against DEM bounds), not silently clipped to edge cells / skipped. On a flat DEM
    (so slope is never the cause), an off-tile order reads infeasible with an explicit off_dem reason; an
    in-bounds order on the same DEM is not flagged off_dem."""
    import numpy as np
    dem = (np.zeros((40, 40)), 5.0); origin = (0.0, 0.0)   # flat 200 m tile
    off = MP.Mission("off", "moon", [MP.BuildOrder("offmap pad", "cut", 100000.0, 100000.0, 36.0, 0.05)])
    res = MP.validate_plan(off, dem=dem, dem_origin=origin)
    assert res["feasible"] is False and res["off_dem_orders"]      # rejected with an explicit reason
    inb = MP.Mission("in", "moon", [MP.BuildOrder("inmap pad", "cut", 100.0, 100.0, 36.0, 0.05)])
    res2 = MP.validate_plan(inb, dem=dem, dem_origin=origin)
    assert not res2["off_dem_orders"]                              # an in-bounds footprint is not flagged


def test_h07_acceptance_scope_is_honest_not_full_validation():
    """Audit H-07 (2026-06-13): validate_plan is MATERIAL realizability + siting + as-built, NOT full plan
    validation. The result must declare its honest scope (covers vs defers) and surface the drum capacity +
    shuttle-cycle count its pooled single-drum execution abstracts -- so a consumer cannot read it as a
    capacity-bounded, route/battery/sequence-aware validation (those axes are the totals / Plan IR path)."""
    m = MP.mission_from_dict({"name": "p", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 0.0, "y": 0.0, "footprint_m2": 36.0, "depth_m": 0.05},
        {"action": "fill", "kind": "fill", "x": 10.0, "y": 10.0, "footprint_m2": 14.0, "depth_m": 0.10}]})
    v = MP.validate_plan(m)
    sc = v["acceptance_scope"]
    assert "mass_conservation" in sc["covers"] and "as_built_flatness" in sc["covers"]
    assert {"route_feasibility", "battery_reserve", "sequence_precedence"} <= set(sc["defers_to_totals"])
    assert v["drum_capacity_kg"] > 0.0                             # the bounded-drum reality is surfaced
    assert v["shuttle_cycles_est"] >= 1                            # ceil(cut_mass / drum_cap), summed over cuts


# ---- AL2: infeasible precedence fails loud, not a silent 0-trip "success" -------------------------
def test_precedence_feasibility_unit():
    assert MP._precedence_is_feasible(3, [(0, 1), (1, 2)]) is True       # a chain: feasible
    assert MP._precedence_is_feasible(2, [(0, 1), (1, 0)]) is False      # a 2-cycle: infeasible
    assert MP._precedence_is_feasible(1, []) is True                     # trivial


def test_cyclic_precedence_fails_loud_not_silent():
    # two separated cut->fill builds whose cross-precedence forms a cycle (A before B and B before A)
    m = MP.mission_from_dict({"name": "cyc", "body": "moon", "charger": [0, 0],
        "orders": [
            {"action": "cutA", "kind": "cut", "x": 5, "y": 5, "footprint_m2": 40, "depth_m": 0.3},
            {"action": "fillA", "kind": "fill", "x": 5, "y": 5, "footprint_m2": 40, "depth_m": 0.3},
            {"action": "cutB", "kind": "cut", "x": 60, "y": 60, "footprint_m2": 40, "depth_m": 0.3},
            {"action": "fillB", "kind": "fill", "x": 60, "y": 60, "footprint_m2": 40, "depth_m": 0.3}],
        "precedence": [["fillA", "cutB"], ["fillB", "cutA"]]})
    with pytest.raises(RuntimeError, match="precedence"):
        MP.plan_and_simulate(m)


def test_optimality_flag_reported_and_exact_for_small_plan():
    # AL1: a small plan is solved exactly (brute) and the optimality is reported, not silent
    m = MP.mission_from_dict({"name": "small", "body": "moon", "charger": [0, 0],
        "orders": [{"action": "cut_pad", "kind": "cut", "x": 5, "y": 5, "footprint_m2": 40, "depth_m": 0.3},
                   {"action": "fill_low", "kind": "fill", "x": 12, "y": 8, "footprint_m2": 40, "depth_m": 0.3}]})
    _, _, _, _, totals = MP.plan_and_simulate(m, algorithm="auto")
    assert totals["optimality"] == "exact"                  # 2 trips <= BRUTE_MAX_TRIPS -> brute = exact
    assert totals["resolved_algorithm"] == "brute"
    # and the default heuristic path is honestly labelled, not silently "exact"
    _, _, _, _, t_nn = MP.plan_and_simulate(m, algorithm="nearest")
    assert t_nn["optimality"] == "heuristic"


# ---- P4: non-polar DEM ingest (reproject a cylindrical lat/lon product to the local metric grid) -
def test_ingest_nonpolar_cylindrical_dem_relief_round_trips(tmp_path):
    import os
    import numpy as np
    from dart import dem_import as di
    _fx = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "stewie", "server", "fixtures")   # fixtures ride with the server pkg (M1)
    heights, geom = di.load_cylindrical_fixture(
        os.path.join(_fx, "ldem4_equator_dn.npy"), os.path.join(_fx, "ldem4_equator.json"))
    assert abs(0.5 * (geom["lat_top_deg"] + geom["lat_bottom_deg"])) < 60.0      # genuinely NON-polar
    Z, cell = di.reproject_cylindrical(
        heights, lat_top=geom["lat_top_deg"], lat_bottom=geom["lat_bottom_deg"],
        lon_left=geom["lon_left_deg"], lon_right=geom["lon_right_deg"], radius_m=geom["radius_m"],
        target_cell_m=2000.0)                                                     # fine metric grid (proves fidelity)
    assert cell == 2000.0                                                         # a metric grid (m)
    rin, rout = float(heights.max() - heights.min()), float(Z.max() - Z.min())
    assert 0.95 * rin <= rout <= rin * 1.001         # relief round-trips at fine sampling (bilinear ≤ source range)
    # and it round-trips through the sim bundle format -> read_dem_window reads the ingested non-polar map
    out = str(tmp_path / "ldem4_bundle")
    di.ingest_to_bundle(Z, cell, out, source=geom["source"])
    win, wcell = MP.read_dem_window(0, 0, Z.shape[0], Z.shape[1], bundle_dir=out)
    assert wcell == cell and np.allclose(win, Z, atol=1.0)                        # rf32 (float32) round-trip


# ---- P4: streaming a km-scale DEM without holding it in RAM -------------------------------------
def test_dem_grid_info_reads_without_loading_data():
    info = MP.dem_grid_info()
    assert info["width"] == 2000 and info["height"] == 2000 and info["cell_m"] == 5.0


def test_read_dem_window_matches_full_load_crop():
    import numpy as np
    Z, cell = MP.load_haworth_dem()
    win, wcell = MP.read_dem_window(800, 1600, 80, 80)
    assert wcell == cell and win.shape == (80, 80)
    assert np.array_equal(win, Z[800:880, 1600:1680])                # bit-exact vs the full-load crop
    # a window at the far corner proves random access (not a prefix read)
    far, _ = MP.read_dem_window(1980, 1980, 20, 20)
    assert np.array_equal(far, Z[1980:2000, 1980:2000])


def test_read_dem_window_holds_a_memory_ceiling():
    # streaming: reading a window allocates ~window bytes, NOT the full 2000^2 (32 MB float64) map
    import tracemalloc
    full_dem_bytes = 2000 * 2000 * 8
    tracemalloc.start()
    win, _ = MP.read_dem_window(500, 500, 128, 128)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < full_dem_bytes // 8                                # comfortably under an eighth of the full map


def test_flattest_anchor_streamed_finds_buildable_site_within_memory_ceiling():
    import numpy as np
    import tracemalloc
    Z, cell = MP.load_haworth_dem()
    median_slope = float(np.median(MP.slope_deg_map(Z, cell)))
    tracemalloc.start()
    ax, ay = MP.flattest_anchor_streamed(window_m=20.0, tile=400)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    smap = MP.slope_deg_map(Z, cell)
    col, row = int(round(ax / cell)), int(round(ay / cell))
    assert smap[row, col] < median_slope                            # found a genuinely flat (buildable) site
    assert peak < 2000 * 2000 * 8                                   # never held the full DEM in RAM


# ---- I10: hazard + slope/slip-aware haul routing on a DEM costmap -------------------------------
def _haworth_routing_crop():
    Z, cell = MP.load_haworth_dem()
    return Z[800:880, 1600:1680].copy(), cell      # real window: 75% passable @25 deg, hazards to 61 deg


def test_slope_costmap_marks_steep_cells_impassable():
    import numpy as np
    crop, cell = _haworth_routing_crop()
    cost, passable = MP.slope_costmap(crop, cell, max_slope_deg=25.0)
    smap = MP.slope_deg_map(crop, cell)
    assert passable.any() and (~passable).any()                    # both buildable corridor and hazards
    assert np.array_equal(passable, smap <= 25.0)
    assert np.all(cost >= 1.0) and np.all(np.isfinite(cost[passable]))
    # cost rises monotonically with slope (slip penalty): steepest passable cell costs more than flattest
    pc = cost[passable]
    assert pc.max() > pc.min()


def test_route_least_cost_avoids_hazards_and_is_at_least_straight_line():
    import numpy as np
    crop, cell = _haworth_routing_crop()
    cost, passable = MP.slope_costmap(crop, cell, max_slope_deg=25.0)
    smap = MP.slope_deg_map(crop, cell)
    H, W = smap.shape
    left, right = smap[:, :W // 3], smap[:, 2 * W // 3:]
    sr = np.unravel_index(int(np.argmin(left)), left.shape)
    gr = np.unravel_index(int(np.argmin(right)), right.shape)
    gr = (gr[0], gr[1] + 2 * W // 3)
    path, length_m, reached = MP.route_least_cost(cost, passable, cell, sr, gr)
    assert reached and path[0] == sr and path[-1] == gr
    assert all(passable[r, c] for r, c in path)                    # routed AROUND every hazard cell
    straight = math.hypot((gr[1] - sr[1]) * cell, (gr[0] - sr[0]) * cell)
    assert length_m >= straight - 1e-6                             # detour is never shorter than the line


def test_route_least_cost_blocked_when_endpoint_impassable():
    import numpy as np
    crop, cell = _haworth_routing_crop()
    cost, passable = MP.slope_costmap(crop, cell, max_slope_deg=25.0)
    smap = MP.slope_deg_map(crop, cell)
    steep = np.unravel_index(int(np.argmax(smap)), smap.shape)     # a real hazard cell (>25 deg)
    flat = np.unravel_index(int(np.argmin(smap)), smap.shape)
    path, length_m, reached = MP.route_least_cost(cost, passable, cell, steep, flat)
    assert reached is False and math.isinf(length_m) and path == []


def test_h04_route_does_not_corner_cut_between_blocked_orthogonals():
    """Audit H-04 (2026-06-13): an 8-connected route must not squeeze diagonally between two
    orthogonally-blocked cells. On a 2x2 where the only step (0,0)->(1,1) corner-cuts both blocked
    orthogonals it must be refused; a fully-open diagonal is still allowed."""
    import numpy as np
    cell = 1.0
    # both orthogonals around the (0,0)->(1,1) diagonal blocked -> the corner-cut is the ONLY step -> refuse
    passable = np.ones((2, 2), bool); passable[0, 1] = False; passable[1, 0] = False
    _, length_m, reached = MP.route_least_cost(np.ones((2, 2)), passable, cell, (0, 0), (1, 1))
    assert reached is False and math.isinf(length_m)
    # control: a fully-open diagonal IS legal (we block corner-cuts, not all diagonals)
    _, _, reached_open = MP.route_least_cost(np.ones((2, 2)), np.ones((2, 2), bool), cell, (0, 0), (1, 1))
    assert reached_open is True
    # control: with the center blocked, an orthogonal detour still reaches the far corner
    p3 = np.ones((3, 3), bool); p3[1, 1] = False
    _, _, reached_detour = MP.route_least_cost(np.ones((3, 3)), p3, cell, (0, 0), (2, 2))
    assert reached_detour is True


def test_h05_route_leg_finds_a_detour_beyond_the_initial_bbox_margin():
    """Audit H-05 (2026-06-13): a valid corridor that leaves the endpoint bounding box by far more
    than the initial 20 m margin must still be found via adaptive window expansion, not declared
    unreachable. A keep-out wall blocks the direct corridor and the only gap is ~80 m north of the
    endpoints -- well outside the 20 m crop the old fixed margin searched."""
    import numpy as np
    cell = 5.0; n = 80
    dem = (np.zeros((n, n)), cell); origin = (0.0, 0.0)
    a = (100.0, 200.0); b = (160.0, 200.0)               # endpoints at row 40, cols 20 and 32
    wall = [{"x": 130.0, "y": float(yy), "r": 12.0} for yy in range(120, 400, 16)]  # blocks col 26 for rows ~22..79
    routed, _, reached, wpts = MP.route_leg(dem, origin, a, b, keepouts=wall)
    assert reached is True and wpts and math.isfinite(routed)
    assert min(y for _, y in wpts) < 140.0               # the corridor detours north past the wall, beyond 20 m


def test_routed_distance_detours_around_a_crater_on_real_haworth():
    # I10 end to end: between two buildable LOCAL sites on opposite sides of a hazardous window, the routed
    # haul distance exceeds the Euclidean line (it goes around the steep ground). Anchored to a DEM origin
    # (M11). Endpoints are the flattest cell in each third, so both are guaranteed passable real terrain.
    import numpy as np
    dem = MP.load_haworth_dem()
    Z, cell = dem
    r0, c0 = 800, 1600
    origin = (c0 * cell, r0 * cell)
    crop = Z[r0:r0 + 80, c0:c0 + 80]
    smap = MP.slope_deg_map(crop, cell)
    W = smap.shape[1]
    sl = np.unravel_index(int(np.argmin(smap[:, :W // 3])), smap[:, :W // 3].shape)
    gl = np.unravel_index(int(np.argmin(smap[:, 2 * W // 3:])), smap[:, 2 * W // 3:].shape)
    a_local = (sl[1] * cell, sl[0] * cell)                          # local meters within the window
    b_local = ((gl[1] + 2 * W // 3) * cell, gl[0] * cell)
    dist, grid_straight, reached = MP.routed_distance(dem, origin, a_local, b_local, max_slope_deg=25.0, margin_m=10.0)
    assert reached
    assert dist >= grid_straight - 1e-6                            # routed >= grid baseline (consistent)
    assert dist > grid_straight + 1.0                              # a real hazard detour, not a straight line


# ---- pluggable sequencer x objective (run different algorithms, sort by any metric) -------------
def _spread_mission():
    # several cuts + fills spread around the charger so the VISIT ORDER actually changes the metrics
    return MP.mission_from_dict({"name": "spread", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut A", "kind": "cut", "x": 120, "y": 0, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "cut B", "kind": "cut", "x": -110, "y": 10, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "fill C", "kind": "fill", "x": 0, "y": 130, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "fill D", "kind": "fill", "x": 10, "y": -120, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "fill E", "kind": "fill", "x": 140, "y": 30, "footprint_m2": 16, "depth_m": 0.05}]})


def test_optimize_sequence_each_algorithm_returns_a_valid_permutation():
    m = _spread_mission()
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    n = len(trips)
    assert n >= 3                                                   # the mission must actually have choices
    for algo in MP.SEQUENCERS:
        order = MP.optimize_sequence(trips, m, algorithm=algo, objective="distance")
        assert sorted(order) == list(range(n))                     # a permutation of all trips


def test_brute_force_is_at_least_as_good_as_nearest():
    m = _spread_mission()
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)

    def dist(order):
        return MP._simulate(m, [trips[i] for i in order])[2]["distance_m"]

    nn = dist(MP.optimize_sequence(trips, m, algorithm="nearest", objective="distance"))
    bf = dist(MP.optimize_sequence(trips, m, algorithm="brute", objective="distance"))
    two = dist(MP.optimize_sequence(trips, m, algorithm="two_opt", objective="distance"))
    assert bf <= nn + 1e-6 and two <= nn + 1e-6                     # exhaustive/local search >= the heuristic


def test_objective_choice_drives_the_optimum():
    # each objective's optimal plan is best in ITS metric -> the objective genuinely steers the optimizer
    m = _spread_mission()
    _, _, _, _, Td = MP.plan_and_simulate(m, algorithm="brute", objective="distance")
    _, _, _, _, Te = MP.plan_and_simulate(m, algorithm="brute", objective="energy")
    assert Td["distance_m"] <= Te["distance_m"] + 1e-6
    assert Te["energy_J"] <= Td["energy_J"] + 1e-6
    assert Td["algorithm"] == "brute" and Td["objective"] == "distance"


def test_compare_algorithms_sorts_by_objective():
    m = _spread_mission()
    res = MP.compare_algorithms(m, objective="distance")
    assert {r["algorithm"] for r in res["rows"]} == {a for a in MP.SEQUENCERS if a != "auto"}
    vals = [r["objective_value"] for r in res["rows"] if "objective_value" in r]
    assert vals == sorted(vals)                                    # ascending for a min objective (best first)
    assert any(r.get("pareto") for r in res["rows"] if "error" not in r)   # a frontier is marked


def test_multivehicle_is_enabled_and_single_is_the_default():
    # MV: vehicles>1 now plans a fleet (was gated off); vehicles=1 stays the single-vehicle default.
    m = _spread_mission()
    _, _, _, _, T1 = MP.plan_and_simulate(m)
    assert T1["vehicles"] == 1
    _, _, _, _, T2 = MP.plan_and_simulate(m, vehicles=2)
    assert T2["vehicles"] == 2 and T2["makespan_s"] <= T1["time_s"] + 1e-6


def test_unknown_algorithm_or_objective_raises():
    m = _spread_mission()
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    with pytest.raises(ValueError):
        MP.optimize_sequence(trips, m, algorithm="bogus", objective="time")
    with pytest.raises(ValueError):
        MP.optimize_sequence(trips, m, algorithm="nearest", objective="bogus")


def _pairs_mission(sites, precedence=None):
    # co-located cut+fill pairs -> one trip per site (a pure TSP/SOP over the sites). The fill is deepened
    # by SWELL so it consumes the FULL bulked cut (mass-balanced, no surplus spoil) -> exactly one trip.
    orders = []
    for i, (x, y) in enumerate(sites):
        orders += [{"action": f"cut{i}", "kind": "cut", "x": x, "y": y, "footprint_m2": 40, "depth_m": 0.05},
                   {"action": f"fill{i}", "kind": "fill", "x": x + 1, "y": y + 1, "footprint_m2": 40,
                    "depth_m": 0.05 * MP.SWELL}]
    p = {"name": "p", "body": "moon", "charger": [0, 0], "orders": orders}
    if precedence:
        p["precedence"] = precedence
    return MP.mission_from_dict(p)


def _dist(m, trips, order):
    return MP._simulate(m, [trips[i] for i in order])[2]["distance_m"]


def test_held_karp_finds_the_optimal_driving_tour():
    # Held-Karp's guarantee is the EXACT minimum additive driving tour (charger -> sites -> charger).
    # Verify against a direct min over all permutations of the pure tour length.
    import itertools
    import math as _m
    m = _pairs_mission([(40, 0), (-40, 3), (80, 0), (-80, 3), (0, 120)])    # 5 trips, NN-suboptimal
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    n = len(trips)
    pts = [tuple(m.charger)] + [tuple(t["site"]) for t in trips]
    dd = lambda a, b: _m.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
    tour = lambda o: dd(0, o[0] + 1) + sum(dd(o[k] + 1, o[k + 1] + 1) for k in range(n - 1)) + dd(o[-1] + 1, 0)
    hk = MP.optimize_sequence(trips, m, algorithm="held_karp", objective="distance")
    true_min = min(itertools.permutations(range(n)), key=tour)
    assert abs(tour(hk) - tour(true_min)) < 1e-6                            # exact optimal driving tour


def test_held_karp_scales_past_brute_and_auto_dispatches():
    sites = [(40 * i - 220, (i % 3) * 55) for i in range(10)]               # 10 trips (> brute's 7 cap)
    m = _pairs_mission(sites)
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    assert 8 <= len(trips) <= 16
    hk = MP.optimize_sequence(trips, m, algorithm="held_karp", objective="distance")
    assert sorted(hk) == list(range(len(trips)))
    nn = MP.optimize_sequence(trips, m, algorithm="nearest", objective="distance")
    assert _dist(m, trips, hk) <= _dist(m, trips, nn) + 1e-6
    _, _, _, _, Ta = MP.plan_and_simulate(m, algorithm="auto", objective="distance")
    _, _, _, _, Thk = MP.plan_and_simulate(m, algorithm="held_karp", objective="distance")
    assert Ta["resolved_algorithm"] == "held_karp_lk"                       # 8-16 trips -> HK seed + LK polish
    assert Ta["distance_m"] <= Thk["distance_m"] + 1e-6                     # the LK polish never hurts


def test_or_opt_and_lk_are_valid_and_no_worse_than_nearest():
    m = _pairs_mission([(40, 0), (-40, 3), (80, 0), (-80, 3), (0, 120)])
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    nn = _dist(m, trips, MP.optimize_sequence(trips, m, algorithm="nearest", objective="distance"))
    for a in ("or_opt", "lk"):
        o = MP.optimize_sequence(trips, m, algorithm=a, objective="distance")
        assert sorted(o) == list(range(len(trips))) and _dist(m, trips, o) <= nn + 1e-6


def test_auto_dispatch_picks_brute_for_small():
    _, _, _, _, T = MP.plan_and_simulate(_pairs_mission([(40, 0), (-40, 3), (80, 0)]), algorithm="auto")
    assert T["resolved_algorithm"] == "brute"                               # <= 7 trips -> exact brute


def test_precedence_is_respected_by_every_algorithm():
    # fill3 must precede fill0 (a constraint the unconstrained optimum would violate)
    m = _pairs_mission([(40, 0), (-40, 3), (80, 0), (-80, 3)], precedence=[["fill3", "fill0"]])
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    prec = MP.trip_precedence(trips, m)
    assert prec                                                             # the constraint lifted to trips
    pred = MP._prec_masks(len(trips), prec)
    for a in ("nearest", "greedy", "two_opt", "or_opt", "lk", "brute", "held_karp", "auto"):
        order = MP.optimize_sequence(trips, m, algorithm=a, objective="distance", precedence=prec)
        assert sorted(order) == list(range(len(trips)))
        assert MP._respects(order, pred), f"{a} violated precedence"


def test_weighted_objective_parses_and_runs():
    assert MP.parse_objective("time") == {"time": 1.0}
    w = MP.parse_objective("time:3,energy:1")
    assert abs(w["time"] - 0.75) < 1e-9 and abs(w["energy"] - 0.25) < 1e-9
    _, _, _, _, T = MP.plan_and_simulate(_spread_mission(), algorithm="two_opt", objective="time:0.5,energy:0.5")
    assert T["objective"] == "time:0.5,energy:0.5"
    with pytest.raises(ValueError):
        MP.parse_objective("time:1,bogus:1")


# ---- architecture-review bug fixes (2026-06-05) ------------------------------------------------
def test_cut_only_mission_plans_the_dominant_dig_cost():
    # HIGH-1: a borrow pit / trench / grade is excavation-ONLY (no paired fill). The dig cost (4151 J/kg,
    # the dominant term) must still enter the plan -- a cut with no fill previously planned ZERO trips.
    m = MP.mission_from_dict({"name": "pit", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "Dig borrow pit", "kind": "cut", "x": 10, "y": 10, "footprint_m2": 36, "depth_m": 0.20}]})
    cut_kg = m.orders[0].mass_kg(m.density * MP.SWELL)
    trips, _, _, _, totals = MP.plan_and_simulate(m)
    assert len(trips) >= 1                                       # excavation is a real trip, not invisible
    assert totals["surplus_kg"] == pytest.approx(cut_kg, rel=1e-6)   # all cut mass is spoil (no fill)
    assert totals["time_s"] > 0.0 and totals["energy_J"] > 0.0
    # the dig energy (mass * DIG_J_PER_KG) is the dominant, certain cost and must be accounted
    assert totals["energy_J"] >= cut_kg * MP.DIG_J_PER_KG * 0.999


def test_distance_m_includes_the_haul_shuttle():
    # HIGH-2: charger AT the cut site -> zero inter-site drive; the only driving is the cut<->fill haul
    # shuttle. distance_m previously summed only inter-site drive legs (haul omitted, ~9x under-report).
    m = MP.mission_from_dict({"name": "haul", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.20},
        {"action": "fill", "kind": "fill", "x": 50, "y": 0, "footprint_m2": 36, "depth_m": 0.20}]})
    trips, _, _, _, totals = MP.plan_and_simulate(m)
    haul_total = sum(tr.get("haul_m", 0.0) for tr in trips)
    assert haul_total > 0.0                                      # there IS a shuttle to count
    assert totals["distance_m"] >= haul_total - 1e-6            # and distance_m now counts it


def test_held_karp_raises_on_cyclic_precedence():
    # MED: a cyclic / unsatisfiable precedence DAG used to make Held-Karp silently return a 0-trip plan;
    # every other sequencer raises. optimize_sequence is public (autonomy.run_closed_loop calls it).
    m = _pairs_mission([(40, 0), (-40, 3), (80, 0)])
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)
    assert len(trips) >= 2
    with pytest.raises(ValueError):
        MP.optimize_sequence(trips, m, algorithm="held_karp", precedence=[(0, 1), (1, 0)])


# ---- discrete keep-out obstacle layer (boulders / no-go zones) ----------------------------------
def test_mission_from_dict_parses_and_validates_keepouts():
    base = {"name": "k", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "c", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 9, "depth_m": 0.1}]}
    m = MP.mission_from_dict({**base, "keepouts": [{"x": 5, "y": 6, "r": 3}]})
    assert m.keepouts == ({"x": 5.0, "y": 6.0, "r": 3.0},)
    assert MP.mission_from_dict(base).keepouts == ()                       # optional -> empty by default
    with pytest.raises(ValueError):
        MP.mission_from_dict({**base, "keepouts": [{"x": 1, "y": 2}]})     # missing r
    with pytest.raises(ValueError):
        MP.mission_from_dict({**base, "keepouts": [{"x": 1, "y": 2, "r": 0}]})  # non-positive radius


def test_keepout_forces_a_strict_detour_on_real_terrain():
    # deterministic: route on a REAL Haworth-DEM crop, then drop a keep-out exactly on a cell of the
    # optimal path -> the new optimum must avoid it and is strictly longer (or blocked). No synthetic terrain.
    dem = MP.load_haworth_dem(); ox, oy = MP.flattest_anchor(dem)
    Z, cell = dem
    r0, c0 = int(oy / cell), int(ox / cell)
    crop = Z[r0:r0 + 40, c0:c0 + 40]
    cost, passable = MP.slope_costmap(crop, cell, max_slope_deg=25.0)
    start, goal = (5, 5), (5, 34)
    if not (passable[start] and passable[goal]):
        pytest.skip("anchor crop corners not both passable")
    path, base_m, reached = MP.route_least_cost(cost, passable, cell, start, goal)
    assert reached and len(path) > 2
    passable[path[len(path) // 2]] = False                                # == a keep-out on the optimal path
    _, det_m, reached2 = MP.route_least_cost(cost, passable, cell, start, goal)
    assert (not reached2) or det_m > base_m + 1e-9                        # blocking an optimum strictly worsens it


def test_plan_accounts_keepouts_end_to_end():
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    pay = {"name": "ko", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
                      {"action": "fill", "kind": "fill", "x": 50, "y": 0, "footprint_m2": 36, "depth_m": 0.1}],
           "keepouts": [{"x": 25, "y": 0, "r": 10}]}                       # straddles the cut->fill haul line
    _, _, _, _, T = MP.plan_and_simulate(MP.mission_from_dict(pay), dem=dem, dem_origin=o)
    assert T["n_keepouts"] == 1
    assert T["haul_detour_frac"] > 0.0 or T["blocked_legs"] > 0           # the keep-out altered the routing
    # an order placed INSIDE a keep-out is flagged as a conflict (you cannot build on the obstacle)
    pay2 = {"name": "onrock", "body": "moon", "charger": [0, 0],
            "orders": [{"action": "on_rock", "kind": "cut", "x": 25, "y": 0, "footprint_m2": 9, "depth_m": 0.1}],
            "keepouts": [{"x": 25, "y": 0, "r": 10}]}
    _, _, _, _, T2 = MP.plan_and_simulate(MP.mission_from_dict(pay2), dem=dem, dem_origin=o)
    assert T2["keepout_conflicts"] == 1


# ---- K11c: continuous idle/heater/survival power (the likely-dominant multi-day term) -----------
def test_survival_power_default_off_then_folds_in_when_set(monkeypatch):
    m = MP.mission_from_dict(_payload())
    _, _, _, _, T0 = MP.plan_and_simulate(m)
    assert T0["idle_power_w"] == 0.0 and T0["survival_energy_J"] == 0.0   # default: not modelled, no inflation
    base_energy = T0["energy_J"]
    monkeypatch.setattr(MP, "IDLE_POWER_W", 50.0)                          # [ASSUMPTION] 50 W survival load
    _, _, _, _, T1 = MP.plan_and_simulate(m)
    assert T1["survival_energy_J"] == pytest.approx(50.0 * T1["time_s"])   # = idle power * mission duration
    assert T1["energy_J"] == pytest.approx(base_energy + T1["survival_energy_J"])   # folded into the headline
    assert T1["avg_power_w"] == pytest.approx(T1["energy_J"] / T1["time_s"])


# ---- P0 as-built acceptance: verify the level pad on the REAL terrain, not a flat mantle --------
def test_as_built_acceptance_on_real_terrain():
    import numpy as np
    dem = MP.load_haworth_dem(); Z, cell = dem
    # a 50 m pad (spans several 5 m DEM cells so the terrain's real relief shows in the as-built surface)
    pay = {"name": "pad", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "Level pad", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 2500.0, "depth_m": 0.05}]}
    m = MP.mission_from_dict(pay)
    # flat mantle (no DEM): the executed surface is trivially flat -> passes, but the flag says it's NOT real
    v_flat = MP.validate_plan(m)
    assert v_flat["as_built_on_real_dem"] is False
    assert v_flat["as_built_flatness_rmse_m"] < 1e-6 and v_flat["as_built_pass"] is True
    # real DEM, flattest anchor vs a steep site: a uniform-depth cut leaves the slope, so the steep site is
    # rougher and fails the +/-2 cm acceptance (the check the flat-mantle path structurally could not give).
    v_flatsite = MP.validate_plan(m, dem=dem, dem_origin=MP.flattest_anchor(dem))
    assert v_flatsite["as_built_on_real_dem"] is True
    smap = MP.slope_deg_map(Z, cell)
    interior = smap[200:-200, 200:-200]
    sr, sc = np.unravel_index(int(np.argmax(interior)), interior.shape)
    o_steep = ((sc + 200) * cell, (sr + 200) * cell)
    v_steep = MP.validate_plan(m, dem=dem, dem_origin=o_steep)
    assert v_steep["as_built_flatness_rmse_m"] > v_flatsite["as_built_flatness_rmse_m"]   # slope shows up
    assert v_steep["as_built_pass"] is False                                              # not flat to +/-2 cm


# ---- MV1-7: multi-vehicle fleet planning (allocation + parallel makespan + deconfliction) -------
def test_multi_vehicle_parallelises_and_deconflicts():
    sites = [(40, 0), (-40, 5), (80, 0), (-80, 5), (0, 90), (0, -90)]      # 6 distinct sites
    m = _pairs_mission(sites)
    _, _, _, _, T1 = MP.plan_and_simulate(m, vehicles=1)
    _, _, pt2, _, T2 = MP.plan_and_simulate(m, vehicles=2)
    assert T2["vehicles"] == 2 and len(T2["vehicles_detail"]) == 2
    assert T2["vehicle_conflicts"] == 0                       # site-exclusive allocation -> no co-occupation
    assert T2["makespan_s"] < T1["time_s"]                    # two rovers finish sooner than one (parallel)
    assert T2["mass_kg"] == pytest.approx(T1["mass_kg"], rel=1e-6)   # same total work, split across the fleet
    # allocation IS site-exclusive: every site's trips belong to exactly ONE vehicle
    by_site = {}
    for pt in pt2:
        s = tuple(pt["trip"]["site"]); by_site.setdefault(s, set()).add(pt["trip"]["vehicle"])
    assert by_site and all(len(vs) == 1 for vs in by_site.values())
    # each vehicle's detail is a real share of the work
    assert sum(d["n_trips"] for d in T2["vehicles_detail"]) == len(pt2)


def test_multi_vehicle_refuses_precedence_v1():
    m = _pairs_mission([(40, 0), (-40, 5), (80, 0)], precedence=[["fill0", "fill1"]])
    with pytest.raises(RuntimeError, match="precedence"):
        MP.plan_and_simulate(m, vehicles=2)


def test_single_vehicle_still_has_uniform_fleet_schema():
    _, _, _, _, T = MP.plan_and_simulate(MP.mission_from_dict(_payload()))
    assert T["vehicles"] == 1 and T["vehicle_conflicts"] == 0
    assert T["makespan_s"] == pytest.approx(T["time_s"]) and T["vehicles_detail"] == []


# ---- negative-obstacle (hole / cliff) detection + avoidance ("don't fall in a hole") -----------
def test_negative_obstacle_flags_the_flat_lip_a_slope_cap_misses():
    import numpy as np
    # a flat plateau that drops off a cliff: the lip cell is FLAT (passable by slope) but overlooks a 5 m
    # drop -> the drop-off detector flags it while the slope cap does not. (Real-terrain crater rims are
    # this pattern; this is a controlled cliff to assert the additive value, not fabricated survey data.)
    Z = np.zeros((5, 6), dtype=float)
    Z[:, 3:] = -4.0                                            # a 4 m drop at col 2->3; over 5 m cells the
    #                                                           centered-gradient lip slope is ~21.8 deg (< 25 cap)
    drop = MP.negative_obstacle_mask(Z, max_drop_m=2.0)
    _, passable = MP.slope_costmap(Z, 5.0, max_slope_deg=25.0)            # slope cap only
    assert drop[0, 2]                                          # the lip (col 2) overlooks a 4 m drop -> flagged
    assert passable[0, 2]                                      # ...yet the slope cap (21.8 deg there) calls it passable
    _, passable_drop = MP.slope_costmap(Z, 5.0, max_slope_deg=25.0, max_drop_m=2.0)
    assert not passable_drop[0, 2]                             # with the drop layer the lip is impassable (kept off)


def test_negative_obstacle_present_on_real_haworth():
    dem = MP.load_haworth_dem(); Z, _cell = dem
    mask = MP.negative_obstacle_mask(Z, max_drop_m=MP.MAX_DROP_M)
    assert mask.any()                                         # the real DEM has crater-rim / scarp drop-offs
    assert mask.mean() < 0.5                                  # but they are localized hazards, not most of the map


# ---- the executable Plan IR (how plans are OUTPUT for a rover / ROS executive) ------------------
def test_plan_ir_is_a_versioned_executable_artifact():
    m = MP.mission_from_dict(_payload())
    ir = MP.plan_ir(m, algorithm="auto", objective="time")
    assert ir["schema_version"] == MP.PLAN_IR_VERSION and len(ir["plan_id"]) == 16
    assert ir["actions"] and all({"op", "expect", "pre"} <= set(a) for a in ir["actions"])
    ops = {a["op"] for a in ir["actions"]}
    assert ops <= {"GoTo", "Excavate", "CutHaulFill", "Import", "Sinter", "Work"} and "GoTo" in ops
    ids = [a["id"] for a in ir["actions"]]
    assert ids == list(range(len(ids)))                                   # sequential, executable order
    assert all(0 <= i < len(ids) and 0 <= j < len(ids) for i, j in ir["precedence"])
    for a in ir["actions"]:                                                # digs carry the real preconditions
        if a["op"] in ("Excavate", "CutHaulFill"):
            assert "map_coverage_min" in a["pre"] and "drum_kg_max" in a["pre"]
        assert a["pre"]["battery_J_min"] > 0
    assert ir["expect"]["energy_J"] > 0 and ir["expect"]["duration_s"] > 0
    assert ir["acceptance"]["recharge_is_precondition_driven"] is True     # recharges aren't positional
    assert MP.plan_ir(m, algorithm="auto", objective="time")["plan_id"] == ir["plan_id"]   # deterministic


def test_plan_ir_lowers_precedence_to_action_ids():
    m = _pairs_mission([(40, 0), (-40, 5), (80, 0)], precedence=[["fill0", "fill1"]])
    ir = MP.plan_ir(m, algorithm="nearest", objective="distance")
    assert ir["precedence"]                                                # order-level precedence lifted
    work_ids = {a["id"] for a in ir["actions"] if a["op"] != "GoTo"}
    assert all(i in work_ids and j in work_ids for i, j in ir["precedence"])   # over WORK actions


def test_plan_ir_emitted_for_multi_vehicle():
    m = _pairs_mission([(40, 0), (-40, 5), (80, 0), (0, 90)])
    ir = MP.plan_ir(m, vehicles=2)
    assert ir["vehicles"] == 2
    assert {a["vehicle"] for a in ir["actions"]} == {0, 1}                 # actions tagged per rover


def test_compare_with_weighted_objective_marks_pareto():
    res = MP.compare_algorithms(_spread_mission(), objective="time:0.5,distance:0.5")
    vals = [r["objective_value"] for r in res["rows"] if "objective_value" in r]
    assert vals == sorted(vals)                                             # weighted score, best first
    assert any(r.get("pareto") for r in res["rows"] if "error" not in r)


# ---- I10 energy: exact gravity lift for uphill hauls -------------------------------------------
def test_haul_energy_is_slip_adjusted_when_the_haul_climbs():
    # #1 slip-loss: a cut->fill haul over sloped ground costs more than the flat 135 J/m (the wheel travels
    # 1/(1-slip) per metre). Place the cut at a low cell and the fill at a high cell so the haul has slope.
    import numpy as np
    dem = MP.load_haworth_dem()
    Z, cell = dem
    win = Z[0:40, 0:40]
    lo = np.unravel_index(int(np.argmin(win)), win.shape)
    hi = np.unravel_index(int(np.argmax(win)), win.shape)
    m = MP.mission_from_dict({"name": "h", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": lo[1] * cell, "y": lo[0] * cell, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "fill", "kind": "fill", "x": hi[1] * cell, "y": hi[0] * cell, "footprint_m2": 16, "depth_m": 0.05}]})
    trips, _, _, _ = MP._build_trips(m, dem, (0.0, 0.0), 25.0)
    cf = next(t for t in trips if t["kind"] == "cutfill")
    assert cf["haul_e"] > cf["haul_m"] * MP.DRIVE_J_PER_M     # slip raises the haul energy above flat


def test_no_dem_haul_energy_is_near_flat_135():
    m = MP.mission_from_dict({"name": "f", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
        {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]})
    trips, _, _, _ = MP._build_trips(m, None, (0.0, 0.0), 25.0)          # no DEM -> no slope (flat)
    cf = next(t for t in trips if t["kind"] == "cutfill")
    # no slope -> ~flat 135/m, apart from the small baseline wheel slip the conserved ladder reports
    # even on level ground (a few tenths of a percent); no large slope/gravity inflation.
    assert cf["haul_e"] >= cf["haul_m"] * MP.DRIVE_J_PER_M
    assert math.isclose(cf["haul_e"], cf["haul_m"] * MP.DRIVE_J_PER_M, rel_tol=0.02)


def test_dem_plan_energy_at_least_the_flat_plan():
    # integration: the slip+lift+routing-aware DEM plan never costs less than the flat plan
    m = MP.mission_from_dict({"name": "i", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "Borrow pit", "kind": "cut", "x": -120, "y": -90, "footprint_m2": 60, "depth_m": 0.08},
        {"action": "Landing pad", "kind": "fill", "x": 140, "y": 110, "footprint_m2": 40, "depth_m": 0.10}]})
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    _, _, _, _, t_flat = MP.plan_and_simulate(m)
    _, _, _, _, t_dem = MP.plan_and_simulate(m, dem=dem, dem_origin=o)
    assert t_dem["energy_J"] >= t_flat["energy_J"] - 1e-6


def test_h06_haul_lift_uses_cumulative_ascent_not_net_endpoints():
    """Audit H-06 (2026-06-13): haul lift energy must integrate POSITIVE elevation gain along the routed
    polyline (cumulative ascent), not the net endpoint difference. A polyline that dips into a trench and
    climbs back to the same elevation has net gain ~0 but real cumulative ascent (> 0)."""
    import numpy as np
    cell = 5.0; n = 20
    Z = np.zeros((n, n)); Z[10, 6:12] = -6.0               # a trench crossing one row
    dem = (Z, cell); origin = (0.0, 0.0)
    a = (10.0, 50.0); b = (90.0, 50.0)                     # both endpoints at z = 0 (cols 2 and 18, row 10)
    assert abs(MP.haul_elevation_gain_m(dem, origin, a, b)) < 1e-9   # net endpoint gain is ~0
    wpts = [(float(c) * cell, 50.0) for c in range(2, 19)]          # straight across: 0 -> -6 -> 0
    assert MP.haul_cumulative_ascent_m(dem, origin, wpts) >= 6.0 - 1e-9   # climbed +6 m out of the trench


def test_uphill_haul_adds_exact_gravity_lift_energy():
    import numpy as np
    dem = MP.load_haworth_dem()
    Z, cell = dem
    win = Z[0:40, 0:40]                                   # a small real-Haworth window with relief
    lo = np.unravel_index(int(np.argmin(win)), win.shape)
    hi = np.unravel_index(int(np.argmax(win)), win.shape)
    dh = float(Z[hi] - Z[lo])
    assert dh > 0.0                                       # the window has real relief
    cut_lo = {"action": "cut", "kind": "cut", "x": lo[1] * cell, "y": lo[0] * cell, "footprint_m2": 40, "depth_m": 0.05}
    fill_hi = {"action": "fill", "kind": "fill", "x": hi[1] * cell, "y": hi[0] * cell, "footprint_m2": 16, "depth_m": 0.05}
    m_up = MP.mission_from_dict({"name": "up", "body": "moon", "charger": [0, 0], "orders": [cut_lo, fill_hi]})
    _, _, _, _, t_up = MP.plan_and_simulate(m_up, dem=dem)        # haul cut(low) -> fill(high) = uphill
    _, _, _, _, t_flat = MP.plan_and_simulate(m_up)               # no DEM -> no lift term
    assert t_flat["lift_energy_J"] == 0.0
    # exact: lift = hauled regolith mass * g * dh
    g = MP.body_gravity("moon")
    flows, _ = MP.balance(m_up)
    hauled = sum(mass for co, fo, mass, d in flows if co is not None and fo is not None)  # true cut->fill hauls
    assert t_up["lift_energy_J"] > 0.0
    # H-06: lift integrates CUMULATIVE positive ascent along the routed polyline, so it is AT LEAST the
    # net-endpoint-gain lift (m*g*dh); a route that also dips and re-climbs adds strictly more.
    assert t_up["lift_energy_J"] >= hauled * g * dh - 1.0
    # downhill (swap): a net-descent haul lifts LESS than the net-ascent haul over the same relief. It is
    # no longer forced to zero -- the routed path can still climb intermediate rises (the H-06 correction).
    m_dn = MP.mission_from_dict({"name": "dn", "body": "moon", "charger": [0, 0], "orders": [
        {**cut_lo, "x": hi[1] * cell, "y": hi[0] * cell}, {**fill_hi, "x": lo[1] * cell, "y": lo[0] * cell}]})
    _, _, _, _, t_dn = MP.plan_and_simulate(m_dn, dem=dem)
    assert 0.0 <= t_dn["lift_energy_J"] < t_up["lift_energy_J"]


# ---- endurance / single-charge range ("true distance before recharge") -------------------------
def _tiny_mission():
    return MP.mission_from_dict({"name": "e", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "c", "kind": "cut", "x": 1, "y": 1, "footprint_m2": 9, "depth_m": 0.02}]})


def test_endurance_flat_range_is_grounded():
    e = MP.endurance(_tiny_mission())
    # ~4.795 MJ / 134.6 J/m -> ~35.6 km full pack, ~32 km to the 10% reserve
    assert 34.0 < e["range_flat_full_km"] < 37.0
    assert 30.0 < e["range_flat_reserve_km"] < 34.0
    assert e["range_flat_reserve_km"] < e["range_flat_full_km"]   # reserve cuts range
    assert e["duration_flat_h"] > 20.0


def test_endurance_slope_slip_and_dem_reach():
    e = MP.endurance(_tiny_mission(), dem=MP.load_haworth_dem(), dem_origin=(5000.0, 5000.0))
    assert e["range_slopeslip_km"] <= e["range_flat_reserve_km"] + 1e-6   # slope+slip never raises range
    assert e["work_area_median_slope_deg"] > 0.0
    r = e["reach"]
    assert r["radius_m"] > 0.0 and r["tile_fully_reachable"] is True       # 32 km range >> 10 km Haworth tile
    assert 0.0 < r["worst_cell_pack_frac"] < 1.0                           # crossing the tile costs < a full pack


def test_power_regime_psr_tower_vs_sunlit_solar():
    # [REQ:EP-03] PSR lander/tower power distinguished from sunlit solar
    # #2 power model: a PSR (e.g. Haworth) has NO sun -> lander/tower power, available anytime, duty 1.0.
    # A sunlit site recharges from solar, duty-limited to the body's daylight fraction (< 1).
    m = _tiny_mission()
    psr = MP.power_regime(m, kind="psr_tower")
    assert psr["duty_frac"] == 1.0 and psr["effective_charge_w"] == psr["charge_power_w"]
    assert "tower" in psr["availability"].lower() or "lander" in psr["availability"].lower()
    sun = MP.power_regime(m, kind="sunlit_solar")
    assert 0.0 < sun["duty_frac"] < 1.0                      # only the daylight fraction of the body-day
    assert sun["effective_charge_w"] < sun["charge_power_w"]
    with pytest.raises(ValueError):
        MP.power_regime(m, kind="bogus")


def test_thermal_derating_cold_cuts_usable_pack():
    assert MP.thermal_derate(None) == 1.0 and MP.thermal_derate(25.0) == 1.0   # warm -> full pack
    assert MP.thermal_derate(-35.0) < 1.0 and MP.thermal_derate(-200.0) >= 0.5  # cold derates, floored
    m = _tiny_mission()
    cold = MP.power_regime(m, kind="psr_tower", temp_c=-35.0)
    assert cold["usable_pack_J"] < MP.BATTERY_J                # cold reduces usable capacity


def test_endurance_carries_power_regime():
    e = MP.endurance(_tiny_mission())                          # default = PSR tower (the Haworth demo site)
    assert e["power"]["kind"] == "psr_tower" and e["power"]["duty_frac"] == 1.0


def test_endurance_conops_reconciliation_drums_dominate():
    c = MP.endurance(_tiny_mission())["conops"]
    assert c["traverse_km"] == 70.0 and c["mission_days"] == 11.0          # SCHULER24 ConOps
    assert 1.5 < c["drive_packs"] < 2.5                                    # 70 km drive ~ 2 packs
    assert c["dig_packs"][0] > c["drive_packs"]                            # digging 5-10 t > driving
    assert c["drums_dominate"] is True


def test_timescale_is_body_dependent():
    # Moon: a 30 h sortie fits easily in the ~9-11 day sun window; Mars: it spans multiple sols
    moon = MP.endurance(_tiny_mission())["timescale"]
    assert moon["day_label"] == "lunar day" and moon["solar_day_h"] > 700
    assert moon["fits_in_window"] is True and moon["sorties_per_window"] > 5
    mars_m = MP.mission_from_dict({"name": "m", "body": "mars", "charger": [0, 0],
                                   "orders": [{"action": "c", "kind": "cut", "x": 1, "y": 1, "footprint_m2": 9, "depth_m": 0.02}]})
    mars = MP.endurance(mars_m)["timescale"]
    assert mars["day_label"] == "sol" and mars["solar_day_h"] < 25
    assert mars["fits_in_window"] is False and mars["spans_days"] > 1.0    # 30 h drive spans >1 sol


def test_single_charge_range_monotone_in_slope_and_slip():
    g = MP.body_gravity("moon")
    flat = MP.single_charge_range_m(g)
    assert MP.single_charge_range_m(g, slope_deg=20.0) < flat              # climbing shortens range
    assert MP.single_charge_range_m(g, slip=0.3) < flat                    # slip shortens range
    assert MP.single_charge_range_m(g, full_pack=True) > flat              # full pack > to-reserve


def test_h01_planning_context_propagates_selected_vehicle():
    """Audit H-01 (2026-06-13): the planner resolves ONE PlanningContext from the SELECTED vehicle, so a
    non-IPEx vehicle's mass / drum / energy actually drive the plan instead of the IPEx globals. ipex
    resolves to EXACTLY the module globals (byte-identical); rassor2 (65 kg, 80 kg drum) differs and its
    heavier mass shortens range on a grade and surfaces in the endurance report."""
    order = {"action": "c", "kind": "cut", "x": 1, "y": 1, "footprint_m2": 9, "depth_m": 0.02}
    ipex = MP.plan_context(MP.mission_from_dict(
        {"name": "i", "body": "moon", "vehicle": "ipex", "charger": [0, 0], "orders": [order]}))
    assert (ipex.dig_j_per_kg, ipex.drive_j_per_m, ipex.battery_j, ipex.rover_mass_kg, ipex.drum_kg) == \
           (MP.DIG_J_PER_KG, MP.DRIVE_J_PER_M, MP.BATTERY_J, MP.ROVER_MASS_KG, MP.DRUM_KG)   # ipex == globals
    r2_mission = MP.mission_from_dict(
        {"name": "r", "body": "moon", "vehicle": "rassor2", "charger": [0, 0], "orders": [order]})
    r2 = MP.plan_context(r2_mission)
    assert r2.rover_mass_kg == 65.0 and r2.drum_kg == 80.0          # the heavier RASSOR-2, bigger drum
    assert r2.rover_mass_kg != ipex.rover_mass_kg                   # the vehicle is propagated, not an IPEx global
    g = MP.body_gravity("moon")                                    # the heavier rover ranges less on a grade
    assert MP.single_charge_range_m(g, slope_deg=15.0, rover_mass_kg=r2.rover_mass_kg) < \
           MP.single_charge_range_m(g, slope_deg=15.0, rover_mass_kg=ipex.rover_mass_kg)
    assert MP.endurance(r2_mission)["rover_mass_kg"] == 65.0        # endurance reads the selected vehicle's mass


def test_h02_simulate_scores_routed_inter_site_geometry_not_straight_line():
    """Audit H-02 (2026-06-13): the optimizer/timeline simulation scores the ROUTED inter-site geometry --
    the SAME legs the executable Plan IR drives -- via one cache routed ONCE (_make_routes), not a straight
    line. On the real Haworth DEM the routed inter-site drive exceeds the straight-line drive."""
    dem = MP.load_haworth_dem(); origin = MP.flattest_anchor(dem)
    m = MP.mission_from_dict({"name": "h", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut", "kind": "cut", "x": -120, "y": -90, "footprint_m2": 60, "depth_m": 0.08},
        {"action": "fill", "kind": "fill", "x": 140, "y": 110, "footprint_m2": 40, "depth_m": 0.10}]})
    trips, _, _, _ = MP._build_trips(m, dem, origin, 25.0)
    rd = MP._make_routes(m, dem, origin, 25.0)
    a, b = (-120.0, -90.0), (140.0, 110.0)
    assert rd(a, b) >= math.hypot(b[0] - a[0], b[1] - a[1]) - 1e-6  # routed never shorter than the line
    assert rd(a, b) == rd(b, a) and rd(a, a) == 0.0                 # routed ONCE: symmetric + same-point
    tl_r, _, _ = MP._simulate(m, trips, rd)                         # sim WITH the routed cache
    tl_f, _, _ = MP._simulate(m, trips, None)                       # sim with straight-line legs
    drive_r = sum((p["t1"] - p["t0"]) * p["speed"] for p in tl_r if p["kind"] == "drive")
    drive_f = sum((p["t1"] - p["t0"]) * p["speed"] for p in tl_f if p["kind"] == "drive")
    assert drive_r >= drive_f - 1e-6 and drive_r > drive_f          # the sim consumes the routed (longer) legs
    # no-DEM mission: routes is None -> straight-line, byte-identical
    assert MP._make_routes(m, None, (0.0, 0.0), 25.0) is None


def test_c04_no_negative_soc_and_far_site_flagged_infeasible():
    """Audit C-04 (2026-06-13): a route leg the pack cannot make must be FLAGGED infeasible, never driven
    on negative state-of-charge. (The bug: transit ran the battery to ~-14 MJ and still 'completed'.)
    Reachable mission -> feasible AND the timeline never dips SoC below 0; a site beyond a single charge's
    reach -> feasible=False with an explicit reason, and STILL never goes negative."""
    g = MP.body_gravity("moon")
    reach = MP.single_charge_range_m(g)                        # to-reserve one-way range = drive()'s threshold
    # (1) a reachable two-site mission (the known-feasible fixture): feasible, batt1 never negative anywhere
    near = _pairs_mission([(40, 0), (-40, 3)])
    _, _, _, tl, totals = MP.plan_and_simulate(near)
    assert totals["feasible"] is True and not totals["infeasible_reasons"]
    assert any(f["kind"] == "charge" for f in tl)              # the dig forces real mid-mission recharges
    assert min(f["batt1"] for f in tl) >= -1e-6               # C-04 invariant: SoC floored at 0
    # (2) a site well beyond a full charge's reach: cannot be driven to -> infeasible, explicit reason, >= 0
    far = _pairs_mission([(reach * 1.5, 0.0)])
    _, _, _, tlf, tf = MP.plan_and_simulate(far)
    assert tf["feasible"] is False
    assert tf["infeasible_reasons"] and any("reach" in r or "stranded" in r for r in tf["infeasible_reasons"])
    assert min(f["batt1"] for f in tlf) >= -1e-6              # never the -14 MJ the audit found


# ---- P5: execute + watch — animatable timeline -------------------------------------------------
def test_build_timeline_is_animatable():
    m = MP.demo_mission()
    tlj = MP.build_timeline(m)
    fr = tlj["frames"]
    assert tlj["duration_s"] > 0 and tlj["battery_J"] > 0 and len(fr) >= len(m.orders)
    assert (fr[0]["x0"], fr[0]["y0"]) == tuple(m.charger)              # starts parked at the charger
    assert (fr[-1]["x1"], fr[-1]["y1"]) == tuple(m.charger)            # returns to the charger
    assert fr[0]["t0"] == 0.0
    assert all(abs(fr[i]["t1"] - fr[i + 1]["t0"]) < 1e-6 for i in range(len(fr) - 1))   # contiguous time
    assert all(-1e-9 <= f["batt0_frac"] <= 1 + 1e-6 and -1e-9 <= f["batt1_frac"] <= 1 + 1e-6 for f in fr)
    cum = [f["cum_mass_kg"] for f in fr]
    assert all(cum[i] <= cum[i + 1] + 1e-6 for i in range(len(cum) - 1)) and cum[-1] > 0   # mass monotonic
    assert {f["phase"] for f in fr} >= {"drive", "dig"}               # the rover drives and digs
    assert any(f["phase"] == "charge" for f in fr)                    # the demo needs mid-mission recharges


def test_build_timeline_routes_with_dem():
    # P5 + I10: with a DEM the timeline's hauls reflect the routed plan (still a valid animatable timeline)
    m = MP.demo_mission()
    dem = MP.load_haworth_dem()
    tlj = MP.build_timeline(m, dem=dem, dem_origin=MP.flattest_anchor(dem))
    assert tlj["duration_s"] > 0 and tlj["frames"][-1]["t1"] == tlj["frames"][-1]["t1"]   # finite, no NaN
    assert (tlj["frames"][-1]["x1"], tlj["frames"][-1]["y1"]) == tuple(m.charger)


# ---- /plan server endpoint (the FastAPI app via TestClient) -------------------------------------
@pytest.fixture()
def base():
    return TestClient(SRV.app)


def _post(base, route, obj):
    r = base.post(route, json=obj)
    return r.status_code, r.json()


def test_plan_endpoint_returns_fetchable_pdf(base):
    code, body = _post(base, "/plan", _payload())
    assert code == 200 and body["ok"] is True
    assert body["pdf"].startswith("/reports/") and body["totals"]["cut_kg"] > 0
    pr = base.get(body["pdf"])                                          # the report is actually served back
    assert pr.status_code == 200 and pr.content[:5] == b"%PDF-"
    assert body["validation"]["mass_conserved"] is True                 # I8: plan validated on the authority


def test_plan_endpoint_returns_executable_plan_ir(base):
    code, body = _post(base, "/plan", _payload())
    assert code == 200 and body["ok"] is True
    ir = body["plan_ir"]
    assert ir["schema_version"] and len(ir["plan_id"]) == 16
    assert ir["actions"] and {"op", "expect", "pre"} <= set(ir["actions"][0])
    assert ir["expect"]["energy_J"] > 0


def test_plan_endpoint_includes_autonomy_and_perception(base):
    # the closed-loop autonomy + the AutoNav onboard-estimate (perception) uncertainty, folded into /plan
    code, body = _post(base, "/plan", _payload())
    assert code == 200 and body["ok"] is True
    au = body["autonomy"]
    assert au is not None and au["recharges"] >= 0 and au["replans"] >= 0
    assert 0.0 <= au["final_soc"] <= 1.0 and isinstance(au["completed"], bool)
    pc = body["perception"]
    assert pc is not None and pc["pose_sigma_m"] >= 0.0 and pc["drum_fill_uncertainty_pct"] > 0.0


def test_plan_endpoint_returns_animatable_timeline(base):
    # P5: /plan returns the execute+watch timeline the browser animates (frames + duration)
    code, body = _post(base, "/plan", _payload())
    tl = body["timeline"]
    assert code == 200 and tl["duration_s"] > 0 and len(tl["frames"]) >= 1
    f0 = tl["frames"][0]
    assert {"t0", "t1", "x0", "y0", "x1", "y1", "phase", "batt0_frac", "cum_mass_kg"} <= set(f0)


def test_plan_endpoint_moon_slope_gates_on_real_dem(base):
    # I6/M11 wired live: a Moon plan is validated against the real Haworth DEM, anchored to the
    # auto-selected flattest site -> the validation carries the slope-gate fields (not the flat check).
    code, body = _post(base, "/plan", _payload())
    v = body["validation"]
    assert code == 200
    assert v["max_slope_deg"] == 15.0 and isinstance(v["slope_violations"], list)


def test_plan_endpoint_honors_algorithm_and_objective(base):
    code, body = _post(base, "/plan", _payload(orders=[
        {"action": "cut A", "kind": "cut", "x": 120, "y": 0, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "cut B", "kind": "cut", "x": -110, "y": 10, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "fill C", "kind": "fill", "x": 0, "y": 130, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "fill D", "kind": "fill", "x": 10, "y": -120, "footprint_m2": 16, "depth_m": 0.05}],
        ) | {"algorithm": "brute", "objective": "energy"})
    assert code == 200 and body["ok"] is True
    assert body["totals"]["algorithm"] == "brute" and body["totals"]["objective"] == "energy"


def test_compare_endpoint_returns_sorted_rows(base):
    payload = _payload(orders=[
        {"action": "cut A", "kind": "cut", "x": 120, "y": 0, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "cut B", "kind": "cut", "x": -110, "y": 10, "footprint_m2": 40, "depth_m": 0.05},
        {"action": "fill C", "kind": "fill", "x": 0, "y": 130, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "fill D", "kind": "fill", "x": 10, "y": -120, "footprint_m2": 16, "depth_m": 0.05}])
    code, body = _post(base, "/compare", payload | {"objective": "distance"})
    assert code == 200 and body["ok"] is True and body["objective"] == "distance"
    vals = [r["objective_value"] for r in body["rows"] if "objective_value" in r]
    assert vals == sorted(vals) and len(vals) >= 2


def test_plan_endpoint_rejects_sinter(base):
    code, body = _post(base, "/plan", _payload(orders=[
        {"action": "Sinter", "kind": "sinter", "x": 1, "y": 1, "footprint_m2": 9, "depth_m": 0.01}]))
    assert code == 400 and body["ok"] is False and "GATED OFF" in body["error"]


def test_plan_endpoint_rejects_unknown_body(base):
    code, body = _post(base, "/plan", _payload(body="pluto"))
    assert code == 400 and "body" in body["error"]


def test_plan_endpoint_rejects_bad_json(base):
    r = base.post("/plan", content=b"{not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["ok"] is False and "bad JSON" in r.json()["error"]


def test_sense_endpoint_noise_off_and_on(base):
    # noise OFF (default): inference is faithful + deterministic
    code, a = _post(base, "/sense", {"true_mass_kg": 25.0})
    assert code == 200 and a["ok"] is True
    assert abs(a["inferred_kg"] - 25.0) < 0.5 and a["noise_frac"] == 0.0
    assert a["offload"] is False and a["current_a"] > 0
    _, a2 = _post(base, "/sense", {"true_mass_kg": 25.0})
    assert a2["inferred_kg"] == a["inferred_kg"]                          # deterministic when noise off
    # near capacity -> offload fires, and fill is in the best-known (>half full) regime
    _, full = _post(base, "/sense", {"true_mass_kg": 30.0})
    assert full["offload"] is True and full["uncertainty_frac"] < 0.03
    # noise ON: reading is perturbed (seeded server-side)
    _, n = _post(base, "/sense", {"true_mass_kg": 25.0, "noise_frac": 0.15, "seed": 3})
    assert n["inferred_kg"] != a["inferred_kg"]


def test_sense_endpoint_rejects_bad_input(base):
    code, body = _post(base, "/sense", {"nope": 1})
    assert code == 400 and "true_mass_kg" in body["error"]


def test_structure_endpoint_returns_plannable_orders(base):
    code, body = _post(base, "/structure", {"name": "landing_pad", "x": 40, "y": 30})
    assert code == 200 and body["ok"] is True
    assert len(body["orders"]) == 2 and sorted(o["kind"] for o in body["orders"]) == ["cut", "fill"]
    # the structure's orders must plan through /plan unchanged
    code2, plan = _post(base, "/plan", {"name": "Pad", "body": "moon", "orders": body["orders"]})
    assert code2 == 200 and plan["ok"] is True and plan["totals"]["cut_kg"] > 0


def test_structure_endpoint_rejects_unknown(base):
    code, body = _post(base, "/structure", {"name": "death_star", "x": 0, "y": 0})
    assert code == 400 and body["ok"] is False and "death_star" in body["error"]


def test_static_index_and_bodies_served(base):
    r = base.get("/")
    assert r.status_code == 200 and b"<" in r.content[:2048]    # serves some HTML
    d = base.get("/bodies.json").json()
    assert "moon" in d and "_ipex" in d                        # the py-generated bodies + ipex mirror


# ---- engineer/developer/intern panes: validation figures, config, API docs --------------------
def test_figures_list_and_serve(base):
    # the Validation pane: /figures lists the real on-disk figures, /figure/{key} serves the PNG
    d = base.get("/figures").json()
    assert d["ok"] and isinstance(d["figures"], list) and len(d["figures"]) > 0   # real figures present
    f0 = d["figures"][0]
    assert f0["key"] and f0["url"] == "/figure/" + f0["key"] and "/" in f0["key"]  # 'category/file.png'
    img = base.get(f0["url"])
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"      # a real PNG
    # allowlist -> path traversal is refused (only listed keys serve)
    assert base.get("/figure/../server.py").status_code == 404
    assert base.get("/figure/nope/missing.png").status_code == 404


def test_config_pane_endpoint(base):
    # the Config pane: the runtime overlay state (PRD N15)
    d = base.get("/config").json()
    assert d["ok"] and "config_file" in d and "overrides" in d and "applied" in d


def test_api_docs_not_shadowed_by_catchall(base):
    # the API explorer pane embeds FastAPI's auto Swagger UI; the catch-all (registered last) must not eat it
    assert base.get("/openapi.json").status_code == 200
    assert base.get("/docs").status_code == 200


# ---- N8 server hardening (a 0.0.0.0-capable service) --------------------------------------------
def test_oversized_body_is_rejected_413(base):
    big = "x" * (SRV._MAX_BODY_BYTES + 1)
    r = base.post("/plan", data=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["ok"] is False


def test_metrics_by_route_is_bounded_by_templates_not_raw_paths(base):
    # hammering distinct attacker-controlled paths must NOT grow the by_route dict unboundedly:
    # they all collapse to the catch-all template, so the key set stays tiny.
    for i in range(40):
        base.get(f"/nonexistent/path/{i}")
    by_route = base.get("/metrics").json()["by_route"]
    assert len(by_route) < 25                                   # bounded by registered routes, not by hits
    assert not any(f"/nonexistent/path/{i}" in by_route for i in range(40))   # raw paths not keyed


def test_structure_rejects_too_many_params(base):
    code, body = _post(base, "/structure", {"name": "landing_pad", "x": 0, "y": 0,
                                            "params": {f"k{i}": 1 for i in range(40)}})
    assert code == 400 and body["ok"] is False and "params" in body["error"]


def test_api_key_auth_constant_time_compare(base, monkeypatch):
    # with a key set, a wrong key is 401 and the right key passes (compare is hmac.compare_digest)
    monkeypatch.setenv("DUSTGYM_API_KEY", "s3cret")
    assert base.post("/plan", json=_payload(), headers={"X-API-Key": "wrong"}).status_code == 401
    ok = base.post("/plan", json=_payload(), headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200 and ok.json()["ok"] is True


def test_algorithm_choice_actually_changes_the_plan():
    """Aaron (#46 Step E): "are these even wired in correctly?" -- the algorithm dropdown must
    CHANGE the result. A crafted asymmetric mission where greedy-nearest is suboptimal: brute
    must find a different (and no-worse) visit order."""
    doc = {"name": "wiring", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "a", "kind": "cut", "x": 10, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "b", "kind": "fill", "x": 11, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "c", "kind": "cut", "x": 60, "y": 40, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "d", "kind": "fill", "x": 12, "y": 1, "footprint_m2": 16, "depth_m": 0.05},
    ]}
    m = MP.mission_from_dict(doc)
    _, _, t_near = MP.run(m, stem="wire_near", algorithm="nearest", objective="duration")
    _, _, t_brute = MP.run(m, stem="wire_brute", algorithm="brute", objective="duration")
    assert t_near["algorithm"].startswith("nearest") and t_brute["algorithm"].startswith("brute")
    assert t_brute["time_s"] <= t_near["time_s"] + 1e-6              # the solver can not be worse


def test_plan_math_worksheet_shows_every_equation_with_numbers():
    """#74 [REQ:PM-08] (Aaron: never assume): the plan emits a per-trip MATH worksheet -- each
    energy/time term as the equation form, the substituted numbers, and the result. No bare
    outputs; the reviewer can re-derive every figure."""
    doc = {"name": "m", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "cut a", "kind": "cut", "x": 20, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "fill b", "kind": "fill", "x": 40, "y": 10, "footprint_m2": 16, "depth_m": 0.05}]}
    m = MP.mission_from_dict(doc)
    sheet = MP.plan_math(m)
    assert sheet["constants"]["DIG_J_PER_KG"] > 0 and sheet["constants"]["DRIVE_J_PER_M"] > 0
    assert sheet["legs"], "every trip is a worksheet entry"
    leg = sheet["legs"][0]
    assert "label" in leg and isinstance(leg["terms"], list)
    for t in leg["terms"]:
        assert {"name", "formula", "substituted", "value", "unit"} <= set(t)
        # the substituted string must contain the numbers, not just symbols
        assert any(ch.isdigit() for ch in t["substituted"])
    # a dig term re-derives exactly: mass * DIG_J_PER_KG
    dig = next((t for lg in sheet["legs"] for t in lg["terms"] if t["name"] == "dig energy"), None)
    if dig:
        assert abs(eval(dig["substituted"].split("=")[-1]) - dig["value"]) < 1.0


def test_assumptions_register_surfaces_real_tagged_values():
    """#75 (mission brief packet): the register is built from the ACTUAL [CALIB]/[ASSUMPTION] tags
    in the specs source -- every assumption surfaced, none fabricated, each with its note."""
    reg = MP.assumptions_register()
    assert len(reg) >= 8, "the specs carry many tagged assumptions"
    names = {r["name"] for r in reg}
    assert "RECHARGE_POWER_W" in names and "DRIVETRAIN_EFFICIENCY" in names
    for r in reg:
        assert r["tag"] in ("[CALIB]", "[ASSUMPTION]")
        assert r["value"] and r["note"]                    # value + provenance note present
    rech = next(r for r in reg if r["name"] == "RECHARGE_POWER_W")
    assert rech["tag"] == "[CALIB]" and "700" in str(rech["value"])


def test_mission_brief_packet_has_cover_register_and_vehicle(tmp_path):
    """#75: the report is now a packet -- cover + 3 plan pages + assumptions register (>=5 PDF
    pages), and the markdown carries the Assumptions Register + Vehicle Configuration sections."""
    m = MP.mission_from_dict({"name": "Brief Test", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "pad", "kind": "cut", "x": 20, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "berm", "kind": "fill", "x": 40, "y": 10, "footprint_m2": 16, "depth_m": 0.05}]})
    pdf, md, _ = MP.run(m, stem=str(tmp_path / "brief"))
    n_pages = open(pdf, "rb").read().count(b"/Type /Page")  # PdfPages writes one /Type /Page per page
    assert n_pages >= 5, f"the packet should have cover + plan pages + register (got {n_pages})"
    text = open(md).read()
    assert "## Assumptions Register" in text and "## Vehicle Configuration" in text
    assert "[CALIB]" in text and "RECHARGE_POWER_W" in text


def test_load_site_dem_honors_the_sites_registry():
    """#77 REG-01: the planner can load ANY imported site, not just Haworth -- Shackleton/Nobile
    are reachable (they were unplannable: _moon_dem hard-targeted Haworth)."""
    haw = MP.load_site_dem("haworth")
    sha = MP.load_site_dem("shackleton_rim")
    assert haw[1] == 5.0 and sha[1] == 5.0                 # both 5 m bundles
    import numpy as np
    assert not np.allclose(haw[0][:50, :50], sha[0][:50, :50])   # genuinely different terrain
    # an un-imported site fails honestly (no fabricated DEM)
    import pytest
    with pytest.raises((FileNotFoundError, KeyError, ValueError)):
        MP.load_site_dem("malapert_massif")


def test_cp01_plan_result_produced_once_and_consumed_by_views():
    """CP-01 [REQ:CP-01] (RB-03): plan() produces ONE immutable PlanResult; the views (Plan IR,
    timeline, run) consume that SAME artifact via result= without re-solving, and the totals they
    read match it exactly. This is the keystone the matrix marked stale-N."""
    import dataclasses
    m = MP.mission_from_dict({"name": "rb03", "body": "moon", "charger": [0, 0], "orders": [
        {"action": "a", "kind": "cut", "x": 20, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
        {"action": "b", "kind": "fill", "x": 40, "y": 10, "footprint_m2": 16, "depth_m": 0.05}]})
    result = MP.plan(m)
    # immutable: a frozen dataclass -- a view cannot mutate the shared artifact
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.totals = {}
    # the SAME result flows into the views (no recompute): Plan IR + timeline read it
    ir = MP.plan_ir(m, result=result)
    tl = MP.build_timeline(m, result=result)
    assert ir["plan_id"]                                       # the IR derives from the shared artifact
    assert tl["frames"] and tl["duration_s"] > 0
    # totals consumed by the views equal the artifact's totals (one source of truth)
    assert abs(tl["duration_s"] - result.totals["time_s"]) < 0.5   # agree to frame rounding (1 ms/frame), not a re-solve
