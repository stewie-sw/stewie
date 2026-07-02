"""FL-03 (PRD §7.10): chargers, pits, dumps, observation vantages, and constrained corridors are SHARED
RESOURCES with finite simultaneous capacity. The ReservationLedger admits a time-windowed reservation
only if it never pushes an instant over the resource's capacity -- preventive admission control, the
substrate the fleet coordinator (FL-04) plans against, generalizing the after-the-fact same-site/charger
conflict detectors. Half-open windows [t_start, t_end): adjacent reservations do NOT conflict.

Run: <venv>/bin/python -m pytest lode/test_fleet_resources.py -q
"""
import pytest

from lode.fleet_resources import ReservationLedger, Reservation, SharedResource


def _ledger(*resources):
    return ReservationLedger(resources)


def test_charger_capacity_one_blocks_overlap_admits_adjacent():
    led = _ledger(SharedResource("chg", "charger", capacity=1))
    assert led.reserve(Reservation("chg", "ipex", 0.0, 10.0)) is True
    assert led.reserve(Reservation("chg", "rassor2", 5.0, 15.0)) is False     # overlaps -> refused
    assert led.reserve(Reservation("chg", "rassor2", 10.0, 20.0)) is True     # half-open: t=10 is free


def test_pit_capacity_two_admits_two_blocks_third():
    led = _ledger(SharedResource("pit", "pit", capacity=2))
    assert led.reserve(Reservation("pit", "a", 0.0, 10.0)) is True
    assert led.reserve(Reservation("pit", "b", 0.0, 10.0)) is True
    assert led.reserve(Reservation("pit", "c", 0.0, 10.0)) is False           # 3rd over capacity 2


def test_corridor_is_one_way_capacity_one():
    led = _ledger(SharedResource("cor", "corridor", capacity=1))
    assert led.reserve(Reservation("cor", "a", 0.0, 5.0)) is True
    assert led.reserve(Reservation("cor", "b", 4.0, 9.0)) is False            # two in the corridor at once


def test_release_frees_the_slot():
    led = _ledger(SharedResource("chg", "charger", capacity=1))
    led.reserve(Reservation("chg", "a", 0.0, 10.0))
    assert led.release("chg", "a") == 1
    assert led.reserve(Reservation("chg", "b", 5.0, 15.0)) is True            # slot freed


def test_occupancy_is_half_open():
    led = _ledger(SharedResource("v", "vantage", capacity=1))
    led.reserve(Reservation("v", "a", 0.0, 10.0))
    assert led.occupancy("v", 5.0) == 1
    assert led.occupancy("v", 10.0) == 0          # half-open: end is not occupied
    assert led.occupancy("v", -1.0) == 0


def test_would_admit_does_not_mutate():
    led = _ledger(SharedResource("chg", "charger", capacity=1))
    req = Reservation("chg", "a", 0.0, 10.0)
    assert led.would_admit(req) is True
    assert led.would_admit(req) is True           # idempotent, no state change
    assert led.reserve(req) is True               # still admissible


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        ReservationLedger([SharedResource("x", "teleporter", capacity=1)])     # unknown kind
    with pytest.raises(ValueError):
        ReservationLedger([SharedResource("x", "charger", capacity=0)])        # capacity < 1
    led = _ledger(SharedResource("chg", "charger", capacity=1))
    with pytest.raises(KeyError):
        led.reserve(Reservation("nope", "a", 0.0, 1.0))                        # unknown resource
    with pytest.raises(ValueError):
        led.reserve(Reservation("chg", "a", 5.0, 5.0))                         # empty window


# ------------------------------------------------------------------------------------------------
# FL-07: raised Solar/Meerkat observation sites are reservable fleet resources (vantage kind), with
# an occlusion/collision exclusion radius, so two rovers never hold overlapping raised observations
# at conflicting vantages -- the loser waits, and the wait folds into the fleet makespan.
# ------------------------------------------------------------------------------------------------

_FL07_ORDERS = [
    {"action": "cutA", "kind": "cut", "x": 20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
    {"action": "cutB", "kind": "cut", "x": -20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
]


def _fl07_mission(extra=None):
    import copy

    import lode.mission_planner as MP
    p = {"name": "F7", "body": "moon", "charger": [0, 0], "orders": copy.deepcopy(_FL07_ORDERS)}
    if extra:
        p.update(extra)
    return MP.mission_from_dict(p)


def test_fl07_raised_observation_reserves_vantage_no_occlusion():
    """[REQ:FL-07] Solar/Meerkat observation sites are reservable fleet resources: a raised observation
    declares a time-windowed capacity-1 VANTAGE reservation with an occlusion/collision exclusion radius,
    so two rovers whose raised observations overlap in time at conflicting vantages (sites within the
    exclusion radius of each other) can NOT hold them simultaneously -- the loser WAITS until the winner's
    window clears -- and that wait folds into the fleet makespan."""
    import lode.mission_planner as MP
    # resolver: rover 0 raises MEERKAT at (0,0) over [0,600); rover 1 raises a solar sight at (4,3) --
    # 5 m away, INSIDE the 10 m exclusion -> the vantages conflict (occlusion/collision) -> ONE
    # capacity-1 vantage -> rover 1 (the later arrival) waits the full 500 s until rover 0 clears.
    obs = [{"vehicle": 0, "x": 0.0, "y": 0.0, "t_start": 0.0, "t_end": 600.0, "kind": "meerkat"},
           {"vehicle": 1, "x": 4.0, "y": 3.0, "t_start": 100.0, "t_end": 700.0, "kind": "solar"}]
    delay, bd = MP._resolve_observation_vantages(2, obs, exclusion_radius_m=10.0)
    assert delay == pytest.approx([0.0, 500.0])               # the loser waits; the winner is untouched
    r0, r1 = sorted(bd["reservations"], key=lambda r: r["t0"])
    assert r0["server"] == r1["server"]                       # conflicting vantages -> the SAME resource
    assert r1["t0"] >= r0["t1"]                               # serialized: no overlapping raised holds
    led = _ledger(SharedResource(r0["server"], "vantage", capacity=1))
    assert all(led.reserve(Reservation(r["server"], f"v{r['vehicle']}", r["t0"], r["t1"]))
               for r in bd["reservations"])                   # replay: the schedule fits capacity 1
    # an observation OUTSIDE the exclusion radius is its own vantage -> admitted with no wait
    far = obs + [{"vehicle": 2, "x": 200.0, "y": 0.0, "t_start": 100.0, "t_end": 700.0, "kind": "meerkat"}]
    delay3, _ = MP._resolve_observation_vantages(3, far, exclusion_radius_m=10.0)
    assert delay3 == pytest.approx([0.0, 500.0, 0.0])
    # end-to-end: declared on the mission, the observation wait folds into the fleet MAKESPAN
    base = MP.plan_and_simulate(_fl07_mission(), vehicles=2)[4]
    assert "observation_wait_s" not in base                   # undeclared -> byte-identical surface
    both = [{"vehicle": 0, "x": 5.0, "y": 0.0, "t_start": 0.0, "t_end": 300.0, "kind": "meerkat"},
            {"vehicle": 1, "x": 8.0, "y": 4.0, "t_start": 0.0, "t_end": 300.0, "kind": "solar"}]
    wr = MP.plan_and_simulate(_fl07_mission({"observations": both}), vehicles=2)[4]
    assert wr["observation_wait_s"] == pytest.approx(300.0)   # the loser waited out a full window
    assert wr["observation_vantages_modeled"] is True
    assert wr["makespan_s"] > base["makespan_s"]              # ...and the wait folds into the makespan
    assert wr["makespan_s"] == pytest.approx(base["makespan_s"] + 300.0)   # by exactly the loser's wait


def test_fl07_mission_from_dict_validates_observations():
    import lode.mission_planner as MP
    ok = _fl07_mission({"observations": [
        {"vehicle": 0, "x": 1.0, "y": 2.0, "t_start": 0.0, "t_end": 60.0}]})   # kind defaults to meerkat
    assert ok.observations == [{"vehicle": 0, "x": 1.0, "y": 2.0,
                                "t_start": 0.0, "t_end": 60.0, "kind": "meerkat"}]
    assert _fl07_mission().observations is None                                 # undeclared -> None
    bad = [
        [{"vehicle": -1, "x": 0, "y": 0, "t_start": 0, "t_end": 1}],            # negative vehicle
        [{"vehicle": True, "x": 0, "y": 0, "t_start": 0, "t_end": 1}],          # bool is not a vehicle index
        [{"vehicle": 0, "x": 0, "y": 0, "t_start": 5, "t_end": 5}],             # empty window
        [{"vehicle": 0, "x": 0, "y": 0, "t_start": 0, "t_end": 1, "kind": "periscope"}],   # unknown kind
        [{"vehicle": 0, "y": 0, "t_start": 0, "t_end": 1}],                     # missing x
    ]
    for b in bad:
        with pytest.raises(ValueError):
            _fl07_mission({"observations": b})
    # the resolver refuses a vehicle index beyond the fleet rather than silently dropping it
    with pytest.raises(ValueError):
        MP._resolve_observation_vantages(
            2, [{"vehicle": 5, "x": 0.0, "y": 0.0, "t_start": 0.0, "t_end": 1.0, "kind": "solar"}])
