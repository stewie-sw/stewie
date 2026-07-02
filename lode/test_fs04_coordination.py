"""FS-04: multi-vehicle coordination as one umbrella -- per-vehicle allocation + health, shared-resource
reservations, space-time deconfliction, cross-vehicle precedence, a human-readable conflict-explanation
surface, and safe replan/fallback on infeasibility -- driven end-to-end on real missions.
"""
from __future__ import annotations

from lode import fleet_coordination as FC
from lode import mission_planner as MP


def _pairs_mission(sites, precedence=None, shared_resources=None):
    orders = []
    for i, (x, y) in enumerate(sites):
        orders += [{"action": f"cut{i}", "kind": "cut", "x": x, "y": y, "footprint_m2": 40, "depth_m": 0.05},
                   {"action": f"fill{i}", "kind": "fill", "x": x + 1, "y": y + 1, "footprint_m2": 40,
                    "depth_m": 0.05 * MP.SWELL}]
    payload = {"name": "p", "body": "moon", "charger": [0, 0], "orders": orders}
    if precedence:
        payload["precedence"] = precedence
    if shared_resources:
        payload["shared_resources"] = shared_resources
    return MP.mission_from_dict(payload)


def _eff_start_end(per_trip, detail, action):
    # the effective (delay-adjusted) window of a trip whose label contains `action`, using its rover's waits.
    pt = next(p for p in per_trip if action in p["trip"].get("label", ""))
    v = pt["trip"]["vehicle"]
    d = next(dd for dd in detail if dd["vehicle"] == v)
    wait = sum(float(d.get(k, 0.0)) for k in ("charger_wait_s", "crowd_wait_s", "precedence_wait_s"))
    return pt["t_start"] + wait, pt["t_end"] + wait


def test_fs04_umbrella_coordination_on_a_real_multipit_mission():  # [REQ:FS-04]
    # two independent precedence chains + a shared-resource pit, planned on two rovers.
    m = _pairs_mission([(40, 0), (80, 0), (0, 40), (0, 80)],
                       precedence=[["fill0", "cut1"], ["fill2", "cut3"]],
                       shared_resources=[{"id": "pit0", "kind": "pit", "capacity": 1, "sites": [[40, 0]]}])
    trips, _, per_trip, _, T = MP.plan_and_simulate(m, vehicles=2)

    # per-vehicle allocation + health
    assert T["vehicles"] == 2 and len(T["vehicles_detail"]) == 2
    for d in T["vehicles_detail"]:
        assert {"feasible", "min_batt_frac", "charges", "health"} <= set(d["health"])
        assert d["health"]["health"] in ("nominal", "low_margin", "stranded")

    # space-time deconfliction: site-exclusive allocation -> no co-occupation
    assert T["vehicle_conflicts"] == 0

    # shared-resource reservation admission is MODELED (concurrent admission capped at capacity)
    assert T.get("shared_resources_modeled") is True

    # cross-vehicle precedence honored: each chain's successor starts no earlier than its predecessor ends
    assert T["n_precedence"] >= 2
    a0s, a0e = _eff_start_end(per_trip, T["vehicles_detail"], "fill0")
    a1s, _ = _eff_start_end(per_trip, T["vehicles_detail"], "cut1")
    assert a1s >= a0e - 1e-6, "cross-vehicle precedence chain A not honored"

    # the consolidated human-readable conflict-explanation surface
    ex = FC.fleet_coordination_explanation(T)
    assert ex and any("deconflicted" in ln or "conflict" in ln for ln in ex)
    assert any(ln.startswith("rover ") for ln in ex), "no per-rover allocation line"
    assert any("reservation" in ln for ln in ex), "reservations not explained"


def test_fs04_safe_replan_fallback_feasible_is_a_noop():  # [REQ:FS-04]
    m = _pairs_mission([(40, 0), (-40, 5), (80, 0)])
    out = FC.fleet_replan_fallback(m, 2)
    assert out["feasible"] is True and out["replanned"] is False and out["vehicles"] == 2
    assert out["tried"] == [{"vehicles": 2, "feasible": True}]
    assert out["explanation"], "a feasible plan still gets an explanation surface"


def test_fs04_safe_replan_fallback_refuses_to_dispatch_a_stranding_plan():  # [REQ:FS-04]
    # pits 50 km out are beyond reachable range -> every rover strands at any fleet size. The safe fallback
    # must REFUSE (dispatch withheld), never return a plan that strands a rover.
    m = _pairs_mission([(50000, 0), (-50000, 50), (50000, 100)])
    stranded = MP.plan_and_simulate(m, vehicles=2)[-1]
    assert stranded["fleet_needs_replan"] is True                # the mission really is infeasible

    out = FC.fleet_replan_fallback(m, 2)
    assert out["feasible"] is False, "a range-infeasible mission cannot be made feasible by shedding rovers"
    assert [t["vehicles"] for t in out["tried"]] == [2, 1] and all(not t["feasible"] for t in out["tried"])
    assert "dispatch withheld" in out["reason"]
    assert any("REPLAN" in ln or "stranded" in ln for ln in out["explanation"])
