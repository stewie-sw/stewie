"""Intern MVP items 1+2: Dijkstra route geometry preserved (waypoint polylines) + blocked routes
marked INFEASIBLE (no straight-line fallback). Real Haworth DEM only; no synthetic terrain."""
import math


from planet_browser import mission_planner as MP


def _dem():
    return MP.load_haworth_dem()


def test_route_leg_returns_waypoint_polyline():
    dem = _dem(); o = MP.flattest_anchor(dem)
    rm, _gs, reached, wp = MP.route_leg(dem, o, (0.0, 0.0), (40.0, 0.0), max_slope_deg=25.0)
    assert reached and len(wp) >= 2
    assert math.hypot(wp[0][0] - 0.0, wp[0][1] - 0.0) < 2 * dem[1]       # starts within a cell of a
    assert math.hypot(wp[-1][0] - 40.0, wp[-1][1] - 0.0) < 2 * dem[1]    # ends within a cell of b
    plen = sum(math.hypot(wp[i + 1][0] - wp[i][0], wp[i + 1][1] - wp[i][1]) for i in range(len(wp) - 1))
    assert abs(plen - rm) < 1.0                                          # polyline length == routed length


def test_route_leg_blocked_returns_no_waypoints():
    dem = _dem(); o = MP.flattest_anchor(dem)
    rm, _gs, reached, wp = MP.route_leg(dem, o, (0.0, 0.0), (40.0, 0.0),
                                        keepouts=[{"x": 40.0, "y": 0.0, "r": 20.0}])   # encloses the goal
    assert not reached and wp == []


def test_totals_carry_routes_and_feasible_clear():
    dem = _dem(); o = MP.flattest_anchor(dem)
    pay = {"name": "r", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
                      {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}]}
    _, _, _, _, T = MP.plan_and_simulate(MP.mission_from_dict(pay), dem=dem, dem_origin=o)
    assert T["feasible"] is True and T["routes"]
    assert any(len(rt["waypoints"]) >= 2 and rt["reached"] for rt in T["routes"])


def test_totals_infeasible_when_haul_blocked():
    dem = _dem(); o = MP.flattest_anchor(dem)
    pay = {"name": "b", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
                      {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}],
           "keepouts": [{"x": 40, "y": 0, "r": 18}]}                      # encloses the fill -> haul blocked
    _, _, _, _, T = MP.plan_and_simulate(MP.mission_from_dict(pay), dem=dem, dem_origin=o)
    assert T["feasible"] is False and T["blocked_legs"] >= 1
    assert any((not rt["reached"]) and rt["waypoints"] == [] for rt in T["routes"])


def test_plan_ir_goto_waypoints_mode_and_feasible():
    dem = _dem(); o = MP.flattest_anchor(dem)
    pay = {"name": "ir", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 20, "y": 15, "footprint_m2": 36, "depth_m": 0.1},
                      {"action": "fill", "kind": "fill", "x": 50, "y": 15, "footprint_m2": 36, "depth_m": 0.1}]}
    ir = MP.plan_ir(MP.mission_from_dict(pay), dem=dem, dem_origin=o)
    assert ir["mode"] == "DEM_KNOWN_POSE_MISSION_SIM" and ir["feasible"] is True
    gotos = [a for a in ir["actions"] if a["op"] == "GoTo"]
    assert gotos and all("waypoints" in g and g["reached"] for g in gotos)
    assert any(len(g["waypoints"]) >= 2 for g in gotos)                  # the charger->cut GoTo is non-trivial


def test_plan_ir_infeasible_when_blocked():
    dem = _dem(); o = MP.flattest_anchor(dem)
    pay = {"name": "irb", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
                      {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}],
           "keepouts": [{"x": 40, "y": 0, "r": 18}]}
    ir = MP.plan_ir(MP.mission_from_dict(pay), dem=dem, dem_origin=o)
    assert ir["feasible"] is False


def test_report_shows_mode_and_feasibility(tmp_path):
    dem = _dem(); o = MP.flattest_anchor(dem)

    def _md(pay):
        m = MP.mission_from_dict(pay)
        trips, flows, pt, tl, T = MP.plan_and_simulate(m, dem=dem, dem_origin=o)
        md = str(tmp_path / "r.md")
        MP.report(m, trips, flows, pt, tl, T, str(tmp_path / "r.pdf"), md)
        return open(md).read()

    clear = _md({"name": "c", "body": "moon", "charger": [0, 0],
                 "orders": [{"action": "cut", "kind": "cut", "x": 20, "y": 15, "footprint_m2": 36, "depth_m": 0.1},
                            {"action": "fill", "kind": "fill", "x": 50, "y": 15, "footprint_m2": 36, "depth_m": 0.1}]})
    assert "DEM_KNOWN_POSE_MISSION_SIM" in clear and "FEASIBLE" in clear and "INFEASIBLE" not in clear
    blocked = _md({"name": "b", "body": "moon", "charger": [0, 0],
                   "orders": [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
                              {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}],
                   "keepouts": [{"x": 40, "y": 0, "r": 18}]})
    assert "INFEASIBLE" in blocked


def test_plan_response_surfaces_terrain_source_and_mode():
    # item 4: the server must NEVER silently degrade to flat -- it surfaces which terrain it used + the mode.
    from fastapi.testclient import TestClient

    from planet_browser.server import app
    c = TestClient(app)
    base = {"charger": [0, 0],
            "orders": [{"action": "cut", "kind": "cut", "x": 20, "y": 15, "footprint_m2": 36, "depth_m": 0.1},
                       {"action": "fill", "kind": "fill", "x": 50, "y": 15, "footprint_m2": 36, "depth_m": 0.1}]}
    jm = c.post("/plan", json={"name": "m", "body": "moon", **base}).json()
    assert jm["mode"] == "DEM_KNOWN_POSE_MISSION_SIM" and jm["terrain_source"] == "haworth_dem"
    ja = c.post("/plan", json={"name": "a", "body": "mars", **base}).json()
    assert ja["terrain_source"] == "flat_fallback"      # no DEM bundle for mars -> SURFACED, not silent
