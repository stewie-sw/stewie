"""FL-03: pit / dump / vantage / corridor modeled as capacity-k SHARED RESOURCES the multi-vehicle planner
contends for, beyond the charger queue.

Declared via mission.shared_resources = [{id, kind, capacity, sites}]; a trip whose work site lies on a
resource's sites occupies it for the trip window, and when more than `capacity` rovers would occupy it at
once the excess WAITS (k-server FCFS, the same discipline as the charger queue). Unset, or single-vehicle,
-> no contention -> byte-identical to the prior planner.
"""
import copy

import pytest

import lode.mission_planner as MP
from lode.fleet_resources import Reservation, ReservationLedger, SharedResource

_ORDERS = [
    {"action": "cutA", "kind": "cut", "x": 20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "cutB", "kind": "cut", "x": -20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "fillA", "kind": "fill", "x": 40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "fillB", "kind": "fill", "x": -40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
]


def _mk(extra=None):
    p = {"name": "S", "body": "moon", "charger": [0, 0], "orders": copy.deepcopy(_ORDERS)}
    if extra:
        p.update(extra)
    return MP.mission_from_dict(p)


def _pit(cap):
    # a single pit resource covering BOTH cut sites (so two vehicles digging contend on it)
    return {"shared_resources": [{"id": "pit1", "kind": "pit", "capacity": cap,
                                  "sites": [[20.0, 0.0], [-20.0, 0.0]]}]}


def test_resolve_none_is_zero_delay():
    pv = [{"per_trip": []}, {"per_trip": []}]
    delay, waits = MP._resolve_shared_resources(pv, None)
    assert delay == [0.0, 0.0] and waits == {}


def test_unset_multi_vehicle_is_byte_identical_surface():  # [REQ:FL-03]
    base = MP.plan_and_simulate(_mk(), vehicles=2)[4]
    # no declared resources -> no resource fields on totals (byte-identical surface to the prior planner)
    assert "resource_wait_s" not in base and "resource_waits" not in base
    assert "shared_resources_modeled" not in base


def test_capacity1_resource_serializes_and_extends_makespan():
    base = MP.plan_and_simulate(_mk(), vehicles=2)[4]
    wr = MP.plan_and_simulate(_mk(_pit(1)), vehicles=2)[4]
    # a capacity-1 pit covering BOTH vehicles' cut sites forces their digs to serialize -> wait + longer makespan
    assert wr["resource_wait_s"] > 0.0
    assert wr["resource_waits"]["pit1"] > 0.0
    assert wr["makespan_s"] > base["makespan_s"]
    assert wr["shared_resources_modeled"] is True


def test_capacity2_resource_fits_both_no_wait():
    base = MP.plan_and_simulate(_mk(), vehicles=2)[4]
    wr = MP.plan_and_simulate(_mk(_pit(2)), vehicles=2)[4]
    # capacity 2 holds both rovers at once -> no wait -> makespan unchanged from the unreserved fleet
    assert wr["resource_wait_s"] == 0.0
    assert abs(wr["makespan_s"] - base["makespan_s"]) < 1e-6


def test_single_vehicle_ignores_shared_resources():
    base = MP.plan_and_simulate(_mk())[4]
    wr = MP.plan_and_simulate(_mk(_pit(1)))[4]
    # a single vehicle never contends -> shared_resources is inert -> byte-identical
    assert abs(wr["makespan_s"] - base["makespan_s"]) < 1e-9
    assert wr["energy_J"] == base["energy_J"]


def test_mission_from_dict_validates_shared_resources():
    m = _mk(_pit(2))
    assert m.shared_resources == [{"id": "pit1", "kind": "pit", "capacity": 2,
                                   "sites": [[20.0, 0.0], [-20.0, 0.0]]}]
    bad = [
        {"shared_resources": [{"id": "x", "kind": "charger", "capacity": 1, "sites": [[0, 0]]}]},  # charger not allowed
        {"shared_resources": [{"id": "x", "kind": "blob", "capacity": 1, "sites": [[0, 0]]}]},      # unknown kind
        {"shared_resources": [{"id": "x", "kind": "pit", "capacity": 0, "sites": [[0, 0]]}]},        # capacity < 1
        {"shared_resources": [{"id": "x", "kind": "pit", "capacity": 1, "sites": []}]},              # empty sites
        {"shared_resources": [{"id": "x", "kind": "pit", "capacity": 1, "sites": [[0]]}]},           # bad [x,y] pair
        {"shared_resources": [{"id": "", "kind": "pit", "capacity": 1, "sites": [[0, 0]]}]},         # empty id
        {"shared_resources": [{"id": "d", "kind": "pit", "capacity": 1, "sites": [[0, 0]]},
                              {"id": "d", "kind": "dump", "capacity": 1, "sites": [[1, 1]]}]},        # duplicate id
    ]
    for b in bad:
        with pytest.raises(ValueError):
            _mk(b)


def test_no_shared_resources_is_default_none():
    assert _mk().shared_resources is None


# ---------------------------------------------------------------------------------------------------
# FL-03 X->D: the charger AND all declared resources are scheduled JOINTLY against ONE multi-server
# ledger with ONE per-vehicle delay clock (replacing the v1 per-server-independent clocks that
# double-counted a rover queued in two resources at once). These unit-test the joint resolver on the
# documented per_vehicle timeline contract -- the same direct-call idiom as test_resolve_none_is_zero_delay
# above; the end-to-end real-mission coverage lives in test_capacity1/test_capacity2.
# ---------------------------------------------------------------------------------------------------

_PIT_AT_ORIGIN = [{"id": "pit1", "kind": "pit", "capacity": 1, "sites": [[0.0, 0.0]]}]


def _replay_is_feasible(reservations, charger_capacity, resources):
    # rebuild a fresh combined ledger and re-admit every placed reservation; a feasible joint schedule
    # never exceeds any server's capacity at any instant, so each reserve() must succeed.
    servers = [SharedResource("charger", "charger", charger_capacity)]
    servers += [SharedResource(r["id"], r["kind"], r["capacity"]) for r in (resources or [])]
    led = ReservationLedger(servers)
    return all(led.reserve(Reservation(rv["server"], "replay", rv["t0"], rv["t1"]))
               for rv in sorted(reservations, key=lambda rv: rv["t0"]))


def test_joint_charger_only_is_byte_identical_to_the_charger_queue():  # [REQ:FL-03]
    # with NO declared resources the joint scheduler reduces to the charger-only FCFS queue, so a
    # multi-vehicle plan with no resources is byte-identical to the prior planner.
    pv = [{"per_trip": [], "tl": [{"kind": "charge", "t0": 0.0, "t1": 10.0}]},
          {"per_trip": [], "tl": [{"kind": "charge", "t0": 5.0, "t1": 15.0}]}]
    joint_delay, bd = MP._resolve_joint_resources(pv, charger_capacity=1, shared_resources=None)
    assert joint_delay == pytest.approx(MP._resolve_charger_queue(pv, capacity=1))   # == [0.0, 5.0]
    assert bd["resource_wait_s"] == 0.0 and bd["resource_waits"] == {}
    assert bd["charger_wait_s"] == pytest.approx(5.0)


def test_joint_equals_independent_when_only_one_server_couples():  # [REQ:FL-03]
    # two rovers contend ONLY the pit (no charges): the joint schedule equals the independent per-resource
    # FCFS exactly -- the joint scheduler tightens, it never under-counts a genuine single-server queue.
    pv = [{"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 0.0, "t_end": 10.0}], "tl": []},
          {"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 5.0, "t_end": 15.0}], "tl": []}]
    joint_delay, bd = MP._resolve_joint_resources(pv, charger_capacity=1, shared_resources=_PIT_AT_ORIGIN)
    ind_res, ind_waits = MP._resolve_shared_resources(pv, _PIT_AT_ORIGIN)
    assert joint_delay == pytest.approx(ind_res)               # == [0.0, 5.0]
    assert bd["resource_waits"] == pytest.approx(ind_waits)
    assert bd["charger_wait_s"] == 0.0


def test_joint_strictly_below_sum_when_a_pit_wait_relieves_the_charger():  # [REQ:FL-03]
    # the DIFFER case the PRD calls out: rover 1's pit wait pushes its recharge arrival PAST rover 0's
    # charge window, so on the coupled timeline it waits ONCE (the pit), not twice (pit + charger). The
    # v1 independent sum double-counts both waits; the joint schedule removes the over-estimate.
    pv = [{"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 0.0, "t_end": 10.0}],
           "tl": [{"kind": "charge", "t0": 12.0, "t1": 20.0}]},
          {"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 0.0, "t_end": 10.0}],
           "tl": [{"kind": "charge", "t0": 12.0, "t1": 20.0}]}]
    joint_delay, bd = MP._resolve_joint_resources(pv, charger_capacity=1, shared_resources=_PIT_AT_ORIGIN)
    ind_charger = MP._resolve_charger_queue(pv, capacity=1)
    ind_res, _ = MP._resolve_shared_resources(pv, _PIT_AT_ORIGIN)
    ind_total = [ind_charger[i] + ind_res[i] for i in range(2)]
    assert sum(ind_total) == pytest.approx(18.0)               # v1: rover1 charged 10 (pit) + 8 (charger)
    assert sum(joint_delay) == pytest.approx(10.0)             # joint: rover1 waits once (the pit only)
    assert sum(joint_delay) < sum(ind_total) - 1e-6            # the over-estimate is removed, not just bounded
    assert bd["charger_wait_s"] == 0.0                         # the charger conflict is gone after the pit shift
    assert bd["resource_waits"]["pit1"] == pytest.approx(10.0)
    # and the coupled schedule is FEASIBLE on every server at once (the real correctness property)
    assert _replay_is_feasible(bd["reservations"], 1, _PIT_AT_ORIGIN)


def test_oracle_refuses_declared_resources_rather_than_validating_a_loose_bound():  # [REQ:FL-03]
    # plan_multi_oracle scores candidates through the shared-charger queue only -- it does NOT model
    # declared resources, so it RAISES (the precedence pattern) rather than report an under-modelled optimum.
    with pytest.raises(ValueError, match="shared_resources"):
        MP.plan_multi_oracle(_mk(_pit(1)), vehicles=2)


def test_joint_schedule_respects_every_capacity_simultaneously():  # [REQ:FL-03]
    # three rovers, a cap-1 pit AND a cap-1 charger, overlapping on both: the placed reservations must
    # never exceed either server's capacity at any instant (one combined ledger, not two independent ones).
    pv = [{"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 0.0, "t_end": 6.0}],
           "tl": [{"kind": "charge", "t0": 7.0, "t1": 12.0}]},
          {"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 1.0, "t_end": 7.0}],
           "tl": [{"kind": "charge", "t0": 8.0, "t1": 13.0}]},
          {"per_trip": [{"trip": {"site": [0.0, 0.0]}, "t_start": 2.0, "t_end": 8.0}],
           "tl": [{"kind": "charge", "t0": 9.0, "t1": 14.0}]}]
    joint_delay, bd = MP._resolve_joint_resources(pv, charger_capacity=1, shared_resources=_PIT_AT_ORIGIN)
    assert _replay_is_feasible(bd["reservations"], 1, _PIT_AT_ORIGIN)
    assert all(d >= 0.0 for d in joint_delay) and len(joint_delay) == 3
    # the per-vehicle attribution slices sum to the reported scalars (the report columns stay consistent)
    assert sum(bd["charger_delay"]) == pytest.approx(bd["charger_wait_s"])
    assert sum(bd["resource_delay"]) == pytest.approx(bd["resource_wait_s"])
