"""FL-04 cross-vehicle precedence chain-splitting: a precedence chain
(before_action -> after_action) that today must live WHOLE on one vehicle
(`_allocate_components`) is instead SPLIT across vehicles -- the dependent leg
waits for its predecessor regardless of which rover does it.

The wait is the SAME FCFS-style per-vehicle delay the shared charger
(`_resolve_charger_queue`) and the space-time crowding resolver
(`_resolve_spacetime_crowding`) already use, so it folds into the makespan
identically. With NO cross-vehicle edge the returned delays are all zero and the
single-vehicle + crowding behavior is byte-identical.

The integration test drives a REAL multi-pit/multi-site Haworth layout through
plan_multi (no fabricated terrain): a 2-rover plan where rover A's dig must
precede rover B's dump completes with the precedence honored across vehicles AND
the makespan beats forcing the whole chain onto one rover.
"""
from __future__ import annotations

import copy

import lode.mission_planner as MP
import lode.planner_multivehicle as PM


# ---------------------------------------------------------------------------
# unit: the cross-vehicle precedence resolver on hand-built per-vehicle state
# ---------------------------------------------------------------------------
def _pv(per_trip_windows):
    """A vehicle whose per_trip windows are (global_trip_idx, t_start, t_end).
    The resolver only needs the trip identity (via alloc) + each leg's window."""
    return {"per_trip": [{"trip": {"_gid": g}, "t_start": t0, "t_end": t1}
                         for (g, t0, t1) in per_trip_windows]}


def test_no_cross_vehicle_edge_means_zero_delay():
    # an INTRA-vehicle edge (both trips on vehicle 0) is honored by the sequencer,
    # not by a cross-vehicle wait -> the resolver returns all-zero.
    per_vehicle = [_pv([(0, 0.0, 100.0), (1, 100.0, 200.0)]), _pv([(2, 0.0, 50.0)])]
    alloc = [[0, 1], [2]]
    assert PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(0, 1)]) == [0.0, 0.0]
    # no precedence at all -> all zero
    assert PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, []) == [0.0, 0.0]


def test_dependent_leg_waits_for_predecessor_on_another_vehicle():
    # trip 0 on vehicle 0 (ends at t=120) must precede trip 1 on vehicle 1
    # (which would otherwise start at t=0). Vehicle 1 must be delayed so trip 1's
    # effective start >= trip 0's effective end.
    per_vehicle = [_pv([(0, 0.0, 120.0)]), _pv([(1, 0.0, 80.0)])]
    alloc = [[0], [1]]
    delay = PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(0, 1)])
    assert delay[0] == 0.0                      # the predecessor's vehicle never moves
    assert delay[1] >= 120.0 - 0.0             # vehicle 1 waits until trip 0 has finished
    # the effective start of trip 1 (0.0 + delay[1]) is now at/after trip 0's end (120.0)
    assert 0.0 + delay[1] >= 120.0 - 1e-9


def test_predecessor_not_first_leg_on_its_vehicle():
    # the predecessor (trip 2) is the SECOND leg on vehicle 0 (ends at t=200);
    # the dependent (trip 3) is the first leg on vehicle 1.
    per_vehicle = [_pv([(0, 0.0, 90.0), (2, 90.0, 200.0)]), _pv([(3, 0.0, 60.0)])]
    alloc = [[0, 2], [3]]
    delay = PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(2, 3)])
    assert delay[0] == 0.0
    assert 0.0 + delay[1] >= 200.0 - 1e-9      # trip 3 starts only after trip 2 ends


# ---------------------------------------------------------------------------
# allocation: a cross-vehicle chain is SPLIT, parallelism preserved
# ---------------------------------------------------------------------------
def _real_dem():
    dem = MP.load_haworth_dem()
    ox, oy = MP.flattest_anchor(dem)
    return dem, (ox, oy)


# Two work clusters on the real flat Haworth region (both reachable from the charger):
#   * worksite A at (10,10): a self-balanced cut->fill (cutA/fillA) PLUS a tiny extra dig (digA) --
#     this is the PREDECESSOR site (rover A's dig).
#   * dump site B at (60,60): a big imported fill (bigB) PLUS a tiny dependent dump (dumpB) -- the
#     dependent site (rover B's dump). bigB is rover B's INDEPENDENT work; it parallelizes with rover A.
# Each cluster is a single work SITE, so site-exclusive allocation keeps it whole on one rover and the
# two clusters land on the two rovers. The precedence chain digA -> dumpB then STRADDLES the two rovers.
# (digA2 is the matching fill that lets digA become a real conserved dig leg, not surplus.)
_ORDERS = [
    {"action": "cutA", "kind": "cut", "x": 10.0, "y": 10.0, "footprint_m2": 16.0, "depth_m": 0.3},
    {"action": "fillA", "kind": "fill", "x": 10.0, "y": 10.0, "footprint_m2": 16.0, "depth_m": 0.3},
    {"action": "digA", "kind": "cut", "x": 10.0, "y": 10.0, "footprint_m2": 0.5, "depth_m": 0.02},
    {"action": "digA2", "kind": "fill", "x": 10.0, "y": 10.0, "footprint_m2": 0.5, "depth_m": 0.02},
    {"action": "bigB", "kind": "fill", "x": 60.0, "y": 60.0, "footprint_m2": 16.0, "depth_m": 0.3},
    {"action": "dumpB", "kind": "fill", "x": 60.0, "y": 60.0, "footprint_m2": 0.5, "depth_m": 0.02},
]
_PREC = [["digA", "dumpB"]]   # rover A's dig must precede rover B's dump (across vehicles)


def _mk(precedence=None):
    payload = {"name": "S", "body": "moon", "charger": [0, 0], "orders": copy.deepcopy(_ORDERS)}
    if precedence is not None:
        payload["precedence"] = precedence
    return MP.mission_from_dict(payload)


def test_cross_vehicle_chain_is_split_not_collapsed_to_one_vehicle():
    dem, origin = _real_dem()
    # digA (cluster A) must precede dumpB (cluster B): a chain that SPANS two work clusters -- the OLD
    # _allocate_components forces both onto one vehicle; _allocate_precedence_split keeps them parallel.
    m = _mk(precedence=_PREC)
    trips, _f, _s, _meta = MP._build_trips(m, dem, origin, 25.0)
    gp = MP.trip_precedence(trips, m)
    assert gp, "expected a real trip-index precedence edge"
    # the OLD policy collapses the whole chain onto one vehicle (one list empty):
    old = PM._allocate_components(trips, 2, gp)
    assert sum(1 for a in old if a) == 1, f"baseline _allocate_components should collapse, got {old}"
    # the NEW split policy uses both rovers:
    alloc = PM._allocate_precedence_split(trips, 2, gp)
    used = [a for a in alloc if a]
    assert len(used) == 2, f"the chain must be SPLIT across both rovers, got {alloc}"
    # site-exclusivity preserved: no two vehicles share a work site
    sites_per_v = [{tuple(trips[i]["site"]) for i in a} for a in alloc]
    assert sites_per_v[0].isdisjoint(sites_per_v[1])


# ---------------------------------------------------------------------------
# integration: real Haworth, precedence honored AND makespan beats one-rover
# ---------------------------------------------------------------------------
def test_precedence_honored_across_vehicles_on_real_haworth():  # [REQ:FL-04]
    dem, origin = _real_dem()
    m = _mk(precedence=_PREC)
    # plan_multi returns (all_trips, flows, all_per_trip, all_tl, totals)
    all_trips, _flows, all_per_trip, _tl, totals = MP.plan_multi(m, dem=dem, dem_origin=origin)

    # both vehicles were used (the chain was split, not collapsed onto one rover)
    used_vehicles = {tr["vehicle"] for tr in all_trips}
    assert used_vehicles == {0, 1}, f"both rovers should work; got {used_vehicles}"

    # the precedence is HONORED across vehicles: every dependent leg's EFFECTIVE
    # start is at/after its predecessor's EFFECTIVE end, where the per-vehicle
    # cross-precedence wait shifts the dependent rover's whole schedule.
    detail = {d["vehicle"]: d for d in totals["vehicles_detail"]}
    pre_delay = {v: detail[v].get("precedence_wait_s", 0.0) for v in detail}
    assert totals["precedence_wait_s"] > 0.0          # a real cross-vehicle wait was applied
    # locate the predecessor (touches pitA) and dependent (touches siteB) legs
    def _eff_window(action):
        for pt in all_per_trip:
            if action in pt["trip"]["actions"]:
                v = pt["trip"]["vehicle"]
                return pt["t_start"] + pre_delay[v], pt["t_end"] + pre_delay[v], v
        raise AssertionError(f"no leg touches {action}")
    pre_start, pre_end, pre_v = _eff_window("digA")
    dep_start, dep_end, dep_v = _eff_window("dumpB")
    assert pre_v != dep_v, "the chain must straddle two vehicles for this to be a cross-vehicle test"
    assert dep_start >= pre_end - 1e-6, (
        f"dependent dumpB start {dep_start} must be >= predecessor digA end {pre_end}")


def test_split_makespan_beats_forcing_the_chain_onto_one_rover():  # [REQ:FL-04]
    dem, origin = _real_dem()
    # the SPLIT plan (new behavior): the chain runs across two rovers in parallel.
    _t, _f, _p, _tl, split = MP.plan_multi(_mk(precedence=_PREC), dem=dem, dem_origin=origin)
    # "forcing the chain onto one rover": the old _allocate_components policy keeps the whole chain on
    # ONE vehicle (the other idle), which is identical in makespan to running the whole mission on a
    # single rover -- so the one-rover plan is the faithful baseline to beat.
    _t2, _f2, _p2, _tl2, single = MP.plan_multi(_mk(precedence=_PREC),
                                                dem=dem, dem_origin=origin, vehicles=1)
    assert split["makespan_s"] < single["time_s"] - 1e-6, (
        f"split makespan {split['makespan_s']} should beat one-rover {single['time_s']}")
    assert split["precedence_split"] is True       # a chain was genuinely split across vehicles


def test_no_precedence_is_byte_identical_to_site_only_allocation():
    dem, origin = _real_dem()
    m_no = _mk(precedence=None)
    trips, _f, _s, _meta = MP._build_trips(m_no, dem, origin, 25.0)
    gp = MP.trip_precedence(trips, m_no)
    assert gp == []                                   # no precedence
    # with no precedence the split allocator falls back to the site-only allocator exactly
    assert PM._allocate_precedence_split(trips, 2, gp) == PM._allocate_trips(trips, 2)
    # and plan_multi exposes a zero precedence wait (no key drift, just 0.0)
    _t, _f2, _p, _tl, tot = MP.plan_multi(m_no, dem=dem, dem_origin=origin)
    assert tot["precedence_wait_s"] == 0.0
