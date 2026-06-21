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
# A global trips list whose elements are matched back to their global index by OBJECT IDENTITY
# (id(pt["trip"])), mirroring how plan_multi keys per_trip windows to global indices -- so the unit
# fixtures exercise the SAME identity mapping as the real planner (not a positional alloc/per_trip zip).
def _trips(n):
    """n distinct trip objects; the global list `trips[g]` has the trip with global index g."""
    return [{"_gid": g} for g in range(n)]


def _pv(trips, per_trip_windows):
    """A vehicle whose per_trip windows are (global_trip_idx, t_start, t_end). Each leg's trip is the
    ACTUAL global trip object trips[g], so the resolver recovers its global index by identity -- the
    per_trip list may be in any order (the sequencer reorders it), not necessarily alloc order."""
    return {"per_trip": [{"trip": trips[g], "t_start": t0, "t_end": t1}
                         for (g, t0, t1) in per_trip_windows]}


def test_no_cross_vehicle_edge_means_zero_delay():
    # an INTRA-vehicle edge (both trips on vehicle 0) is honored by the sequencer,
    # not by a cross-vehicle wait -> the resolver returns all-zero.
    trips = _trips(3)
    per_vehicle = [_pv(trips, [(0, 0.0, 100.0), (1, 100.0, 200.0)]), _pv(trips, [(2, 0.0, 50.0)])]
    alloc = [[0, 1], [2]]
    assert PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(0, 1)], trips) == [0.0, 0.0]
    # no precedence at all -> all zero
    assert PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [], trips) == [0.0, 0.0]


def test_dependent_leg_waits_for_predecessor_on_another_vehicle():
    # trip 0 on vehicle 0 (ends at t=120) must precede trip 1 on vehicle 1
    # (which would otherwise start at t=0). Vehicle 1 must be delayed so trip 1's
    # effective start >= trip 0's effective end.
    trips = _trips(2)
    per_vehicle = [_pv(trips, [(0, 0.0, 120.0)]), _pv(trips, [(1, 0.0, 80.0)])]
    alloc = [[0], [1]]
    delay = PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(0, 1)], trips)
    assert delay[0] == 0.0                      # the predecessor's vehicle never moves
    assert delay[1] >= 120.0 - 0.0             # vehicle 1 waits until trip 0 has finished
    # the effective start of trip 1 (0.0 + delay[1]) is now at/after trip 0's end (120.0)
    assert 0.0 + delay[1] >= 120.0 - 1e-9


def test_predecessor_not_first_leg_on_its_vehicle():
    # the predecessor (trip 2) is the SECOND leg on vehicle 0 (ends at t=200);
    # the dependent (trip 3) is the first leg on vehicle 1.
    trips = _trips(4)
    per_vehicle = [_pv(trips, [(0, 0.0, 90.0), (2, 90.0, 200.0)]), _pv(trips, [(3, 0.0, 60.0)])]
    alloc = [[0, 2], [3]]
    delay = PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(2, 3)], trips)
    assert delay[0] == 0.0
    assert 0.0 + delay[1] >= 200.0 - 1e-9      # trip 3 starts only after trip 2 ends


def test_per_trip_in_non_alloc_order_still_honors_precedence():
    # REGRESSION (cross-vehicle precedence mis-pairing): the per-vehicle sequencer reorders a vehicle's
    # trips before _simulate, so per_trip is in SIMULATION order, NOT alloc order. Here vehicle 0 is
    # ALLOCATED trips [4, 5] but the sequencer ran trip 5 FIRST (per_trip order = 5 then 4) -- so the
    # PREDECESSOR (trip 4) is NOT the first simulated leg on its vehicle. The dependent trip 6 (on
    # vehicle 1) must start only after trip 4's REAL end (t=300), not after the FIRST per_trip leg's end.
    #   alloc order  : v0 = [4, 5]            (4 is alloc-position 0)
    #   per_trip order: v0 = [5 @ 0..40, 4 @ 40..300]   (4 is the SECOND simulated leg, ending at 300)
    # The OLD positional zip(alloc, per_trip) pairs alloc[0]=4 with per_trip[0] (trip 5, end 40), so it
    # would let dependent trip 6 start at ~40 -- a SILENT precedence violation. Identity mapping pairs
    # trip 4 with its true window (end 300), so trip 6 must wait until 300.
    trips = _trips(7)
    per_vehicle = [
        _pv(trips, [(5, 0.0, 40.0), (4, 40.0, 300.0)]),   # per_trip in NON-alloc (simulation) order
        _pv(trips, [(6, 0.0, 50.0)]),
    ]
    alloc = [[4, 5], [6]]                                   # alloc order: predecessor 4 is FIRST in alloc
    delay = PM._resolve_cross_vehicle_precedence(per_vehicle, alloc, [(4, 6)], trips)
    assert delay[0] == 0.0                                  # predecessor's vehicle never moves
    # dependent trip 6's effective start (0.0 + delay[1]) must be >= predecessor trip 4's REAL end (300),
    # NOT the 40 the buggy positional zip would have used.
    assert 0.0 + delay[1] >= 300.0 - 1e-9, (
        f"dependent must wait for trip 4's real end (300), got effective start {delay[1]}")


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
