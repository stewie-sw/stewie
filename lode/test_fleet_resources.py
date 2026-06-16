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
