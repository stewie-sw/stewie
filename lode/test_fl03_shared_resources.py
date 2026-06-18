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
