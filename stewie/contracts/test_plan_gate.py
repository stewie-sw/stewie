"""[REQ:MP-07] The plan-executability gate: a plan is not executable until all eight §30.3 preconditions hold;
it mirrors EG-05's live gate (both refuse until their full precondition set is met)."""
import dataclasses

import pytest

from stewie.contracts.plan_gate import (
    PlanNotExecutable,
    PlanPreconditions,
    is_executable,
    require_executable,
)

_STEPS = [f.name for f in dataclasses.fields(PlanPreconditions)]


def test_mp07_not_executable_when_any_precondition_missing():  # [REQ:MP-07]
    assert len(_STEPS) == 8
    for missing in _STEPS:
        pc = PlanPreconditions(**{s: (s != missing) for s in _STEPS})       # all but one
        assert is_executable(pc) is False
        with pytest.raises(PlanNotExecutable):
            require_executable(pc)


def test_mp07_executable_when_all_eight_met():  # [REQ:MP-07]
    pc = PlanPreconditions(*([True] * 8))
    assert is_executable(pc) is True
    require_executable(pc)                                                  # no raise
    assert pc.unmet() == []


def test_mp07_unmet_names_the_missing_preconditions():  # [REQ:MP-07]
    pc = PlanPreconditions(required_capabilities=True, assigned_assets=True)
    unmet = pc.unmet()
    assert "physics_score" in unmet and "approval_record" in unmet and "rollback_abort_rule" in unmet
    assert "required_capabilities" not in unmet


def test_mp07_mirrors_eg05_live_gate():  # [REQ:MP-07]
    from stewie.contracts.live_gate import LivePreconditions
    # both gates refuse on an empty precondition set (the planning-domain mirror of the live gate)
    assert is_executable(PlanPreconditions()) is False
    assert LivePreconditions().all_met() is False
