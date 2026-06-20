"""FS-05 end-to-end: the navigation spine that CONNECTS the contract's nav stages into one running drive.

These acceptance tests are the V-column evidence for FS-05: not "each seam imports" (that is the
navigation_contract's job) but "the stages, chained, drive a REAL DEM corridor to the goal." The DEM is the
real LOLA Haworth tile (MP.load_haworth_dem); keep-outs/start/goal are mission INPUTS, not fabricated data;
slip comes from the sourced ladder and the executed pose from the exact unicycle integral -- nothing
synthetic.
"""
from __future__ import annotations

import math

import numpy as np

from lode import mission_planner as MP
from lode import nav_pipeline as NP
from lode.local_planner import DEFAULT_OMEGA_MAX
from stewie.specs import ipex_specs as S

_NAV_STAGES = {"global_route", "local_trajectory", "tracker", "recovery", "deviation"}


def _flat_dem():
    """The real Haworth tile + a flat-region LOCAL origin (the same fixture the routing tests use)."""
    dem = MP.load_haworth_dem()
    ox, oy = MP.flattest_anchor(dem)
    return dem, (ox, oy)


def test_navigation_runs_end_to_end_on_real_haworth():  # [REQ:FS-05]
    dem, origin = _flat_dem()
    start, goal = (4.0, 4.0), (44.0, 36.0)
    res = NP.run_navigation(dem, origin, start, goal, dt=2.0, max_ticks=600)

    # Stage 1 found a real corridor and the drive followed it to the goal.
    assert res["reached"] is True
    assert res["arrived"] is True and res["reason"] == "arrived"
    assert len(res["waypoints"]) >= 2 and res["routed_m"] > 0.0

    # ALL FS-05 on-host nav stages were actually exercised in one connected run (not merely importable).
    assert _NAV_STAGES <= set(res["stages"]), res["stages"]

    # the executed pose finished at the REQUESTED goal (the spine drove there, the integral is real).
    end = res["trajectory"][-1]
    assert math.hypot(end[0] - goal[0], end[1] - goal[1]) <= 2.0
    assert len(res["trajectory"]) == res["n_ticks"] + 1   # one pose per executed control tick + the start

    # the drive tracked the planned corridor closely (cross-track deviation is small on a clear route).
    assert res["deviation"]["max_m"] < 8.0

    # local_trajectory and tracker ran together every tick (a true chain, not one without the other).
    assert res["local_calls"] == res["track_calls"] == res["n_ticks"] > 10


def test_executed_twists_are_the_bounded_cmd_vel_egress():  # [REQ:FS-05]
    # the per-tick twist stream IS the ROS cmd_vel egress; every command respects the kinematic caps
    # (bounded_twist), so a downstream ROS bridge can publish them verbatim.
    dem, origin = _flat_dem()
    res = NP.run_navigation(dem, origin, (4.0, 4.0), (44.0, 36.0), dt=2.0, max_ticks=600)
    assert res["twists"], "the drive produced no cmd_vel commands"
    for t in res["twists"]:
        assert 0.0 <= t["v"] <= S.DRIVE_SPEED_MS + 1e-9
        assert abs(t["omega"]) <= DEFAULT_OMEGA_MAX + 1e-9
        assert 0.0 < t["speed_scale"] <= 1.0     # the real slope-derived derate, never fabricated > 1


def test_recovery_stage_fires_and_escapes_a_blocking_keepout():  # [REQ:FS-05]
    # Drive a straight 2-point route at a keep-out that fully blocks the head-on fan. The recovery stage
    # must FIRE (planner failure) -- proving it is live in the loop, not dead -- back up + reorient, route
    # AROUND the obstacle (never entering r+clearance), and still arrive. This is the spine's NV-06 leg.
    start, goal = (0.0, 0.0), (30.0, 0.0)
    block = (14.0, 0.0, 5.0)              # keep-out circle squarely on the straight path
    res = NP.drive_route([start, goal], keepouts=[block], dt=2.0, horizon_m=8.0, lookahead_m=6.0,
                         clearance_m=1.0, goal_tol_m=2.0, max_ticks=400)
    assert res["n_recoveries"] >= 1, "recovery never fired on a fully blocking obstacle"
    assert any(e["reason"] == "planner_failure" for e in res["recovery_events"])
    assert res["arrived"] is True and res["reason"] == "arrived"
    # the executed path never entered the physical keep-out and respected the 1 m clearance to within the
    # arc-sampling resolution (plan_local checks 12 points/arc; the integrated pose lands between them, so it
    # can graze sub-mm past the checked boundary -- the clearance buffer exists for exactly this slop).
    d = np.hypot(res["trajectory"][:, 0] - block[0], res["trajectory"][:, 1] - block[1])
    assert d.min() > block[2]                       # never entered the physical obstacle (5.0 m), ~1 m to spare
    assert d.min() >= block[2] + 1.0 - 0.05         # honored the clearance to within arc-sampling resolution


def test_no_global_corridor_reports_honest_infeasible():  # [REQ:FS-05]
    # A goal off the mapped tile has no corridor: the pipeline reports reached=False rather than driving a
    # straight line through unmapped/hazard terrain (NV-01 discipline, surfaced at the route stage).
    dem, origin = _flat_dem()
    Z, cell = dem
    off_tile_local = (Z.shape[1] * cell + 500.0, Z.shape[0] * cell + 500.0)   # well past the tile extent
    res = NP.run_navigation(dem, origin, (4.0, 4.0), off_tile_local, dt=2.0, max_ticks=50)
    assert res["reached"] is False
    assert res["arrived"] is False
    assert res["trajectory"].shape == (0, 2) and res["twists"] == []


def test_drive_route_core_is_pure_geometry_and_reaches_a_clear_goal():
    # the spine core (no DEM, no obstacles) drives a clear straight route to the goal with ~zero cross-track
    # deviation -- the decoupled, injected-predicate form (mirrors how plan_local is unit-tested).
    res = NP.drive_route([(0.0, 0.0), (20.0, 0.0)], dt=2.0, goal_tol_m=1.0, max_ticks=200)
    assert res["arrived"] is True and res["n_recoveries"] == 0
    end = res["trajectory"][-1]
    assert math.hypot(end[0] - 20.0, end[1] - 0.0) <= 1.0
    assert abs(end[1]) < 0.5                       # stayed on the straight line (no lateral wander)
    assert set(res["stages"]) >= {"local_trajectory", "tracker", "recovery"}
