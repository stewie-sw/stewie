"""EP-04: the mission clock enforces power/illumination/thermal/comms windows on actions and recharge.

Mission.mission_windows = {class: [[open_s, close_s], ...]} in mission-clock seconds, class in
{recharge, work, drive}. An action that would start outside every allowed interval idles the clock to the
next window (a "wait" leg, no battery drawn); if no future window remains the action is skipped/infeasible.
None (or a missing class) = unconstrained = byte-identical to an un-windowed plan."""
import math

import pytest

import lode.mission_planner as MP


def _mk(extra=None):
    p = {"name": "S", "body": "moon", "charger": [0, 0],
         "orders": [{"action": "cut", "kind": "cut", "x": 20.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2},
                    {"action": "fill", "kind": "fill", "x": 40.0, "y": 0.0, "footprint_m2": 9.0, "depth_m": 0.2}]}
    if extra:
        p.update(extra)
    return MP.mission_from_dict(p)


# ---- _window_gate unit behaviour ----
def test_window_gate_unconstrained_passthrough():
    assert MP._window_gate(None, "work", 50.0) == (50.0, 0.0, None)
    assert MP._window_gate({}, "work", 50.0) == (50.0, 0.0, None)
    assert MP._window_gate({"recharge": [[0, 10]]}, "work", 50.0) == (50.0, 0.0, None)  # other class unconstrained


def test_window_gate_idles_to_open():
    start, wait, reason = MP._window_gate({"work": [[100, 200]]}, "work", 40.0)
    assert start == 100.0 and wait == 60.0 and reason is None


def test_window_gate_inside_runs_now():
    assert MP._window_gate({"work": [[100, 200]]}, "work", 150.0) == (150.0, 0.0, None)


def test_window_gate_multi_interval_picks_next():
    start, wait, reason = MP._window_gate({"work": [[0, 10], [100, 200]]}, "work", 50.0)
    assert start == 100.0 and wait == 50.0 and reason is None      # past the first, before the second


def test_window_gate_closed_returns_reason():
    start, wait, reason = MP._window_gate({"work": [[0, 10]]}, "work", 50.0)
    assert start == 50.0 and wait == 0.0 and reason is not None and "closed" in reason


# ---- end-to-end through plan_and_simulate ----
def test_permissive_window_is_byte_identical():
    base = MP.plan_and_simulate(_mk())[4]
    perm = MP.plan_and_simulate(_mk({"mission_windows": {"work": [[0, 1e12]], "recharge": [[0, 1e12]]}}))[4]
    assert math.isclose(perm["makespan_s"], base["makespan_s"], rel_tol=0, abs_tol=1e-9)
    assert math.isclose(perm["energy_J"], base["energy_J"], rel_tol=0, abs_tol=1e-6)
    assert perm["charges"] == base["charges"]


def test_work_window_idles_clock_without_changing_energy():
    base = MP.plan_and_simulate(_mk())[4]
    _t, _f, _pt, tl, tot = MP.plan_and_simulate(_mk({"mission_windows": {"work": [[1000.0, 1e12]]}}))
    # the first dig was at ~66.7 s; gating work to [1000, inf) idles the clock to 1000 s exactly once
    assert any(e["kind"] == "wait" for e in tl)
    assert math.isclose(tot["makespan_s"], base["makespan_s"] + (1000.0 - 66.6666667), abs_tol=2.0)
    # idling draws no battery -> energy/mass/recharge count are conserved
    assert math.isclose(tot["energy_J"], base["energy_J"], rel_tol=0, abs_tol=1e-6)
    assert tot["charges"] == base["charges"]
    w = next(e for e in tl if e["kind"] == "wait")
    assert w["batt0"] == w["batt1"] and w["speed"] == 0.0


def test_recharge_window_idles_before_refilling():
    base = MP.plan_and_simulate(_mk())[4]
    # the baseline's first recharge begins at ~89 911 s; gating recharge to [130000, inf) idles it to 130000 s
    tot = MP.plan_and_simulate(_mk({"mission_windows": {"recharge": [[130000.0, 1e12]]}}))[4]
    assert tot["makespan_s"] > base["makespan_s"]
    assert math.isclose(tot["energy_J"], base["energy_J"], rel_tol=0, abs_tol=1e-6)


# ---- mission_from_dict validation ----
def test_mission_from_dict_validates_windows():
    m = _mk({"mission_windows": {"work": [[0, 100], [200, 300]]}})
    assert m.mission_windows == {"work": [[0.0, 100.0], [200.0, 300.0]]}
    with pytest.raises(ValueError):
        _mk({"mission_windows": {"bogus": [[0, 1]]}})              # unknown class
    with pytest.raises(ValueError):
        _mk({"mission_windows": {"work": [[100, 50]]}})            # close < open
    with pytest.raises(ValueError):
        _mk({"mission_windows": {"work": [[0]]}})                  # not a [open, close] pair


def test_no_windows_is_default_none():
    assert _mk().mission_windows is None
