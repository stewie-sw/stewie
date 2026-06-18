"""CP-08: planner objectives support HARD CONSTRAINTS + a risk term, not only weighted metrics. A
candidate ordering overshooting a budget is penalized below any feasible one; risk_weight adds a
recharge-exposure cost. Default (no constraints) = weighted-only = byte-identical."""
import pytest

import lode.mission_planner as MP


def test_penalty_zero_when_unset():
    core = {"time_s": 100.0, "energy_J": 1e6, "charges": 2, "distance_m": 50.0}
    assert MP._constraint_penalty(core, None) == 0.0
    assert MP._constraint_penalty(core, {}) == 0.0


def test_overshoot_is_penalized_and_monotone():  # [REQ:CP-08]
    cons = {"max_time_s": 100.0}
    assert MP._constraint_penalty({"time_s": 50.0}, cons) == 0.0       # within budget -> no penalty
    p_bad = MP._constraint_penalty({"time_s": 150.0}, cons)
    assert p_bad >= 1e6                                                # infeasible pushed far down
    assert MP._constraint_penalty({"time_s": 300.0}, cons) > p_bad     # more overshoot -> larger penalty


def test_risk_weight_adds_recharge_cost():
    assert MP._constraint_penalty({"charges": 4}, {"risk_weight": 10.0}) == 40.0


def test_multiple_budgets_sum():
    cons = {"max_time_s": 100.0, "max_charges": 1}
    p = MP._constraint_penalty({"time_s": 200.0, "charges": 5}, cons)
    assert p >= 2e6                                                    # both budgets violated -> both penalized


_BASE = {"name": "S", "body": "moon", "charger": [0, 0],
         "orders": [{"action": "p", "kind": "cut", "x": 5, "y": 5, "footprint_m2": 4, "depth_m": 0.1}]}


def test_mission_from_dict_validates_constraints():
    m = MP.mission_from_dict({**_BASE, "objective_constraints": {"max_charges": 3, "risk_weight": 2.0}})
    assert m.objective_constraints == {"max_charges": 3.0, "risk_weight": 2.0}
    with pytest.raises(ValueError):
        MP.mission_from_dict({**_BASE, "objective_constraints": {"bogus": 1}})       # unknown key
    with pytest.raises(ValueError):
        MP.mission_from_dict({**_BASE, "objective_constraints": {"max_charges": -1}})  # negative budget


def test_no_constraints_is_default_none():
    m = MP.mission_from_dict(_BASE)
    assert m.objective_constraints is None                            # unconstrained = byte-identical path
