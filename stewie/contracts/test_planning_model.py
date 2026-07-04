"""[REQ:MP-05] The mission-planning object model: the 12 planning objects are strict Contract subclasses, and
a Plan round-trips through the store losslessly carrying its decision + provenance + world-transaction link."""
import pytest
from pydantic import ValidationError

from stewie.contracts import Contract
from stewie.contracts.planning_model import (
    PLANNING_CONTRACTS,
    Assignment,
    Plan,
    PlanCandidate,
    PlanDecision,
    ResourceBudget,
    RiskAssessment,
    plan_from_record,
    plan_to_record,
)


def test_mp05_twelve_objects_are_contract_subclasses():  # [REQ:MP-05]
    assert len(PLANNING_CONTRACTS) == 12
    for c in PLANNING_CONTRACTS:
        assert issubclass(c, Contract), f"{c.__name__} is not a Contract subclass"


def test_mp05_plan_round_trips_through_the_store_with_decision_and_provenance():  # [REQ:MP-05]
    plan = Plan(
        plan_id="p1", mission_id="m1", task_ids=("t1", "t2"),
        candidate=PlanCandidate(
            candidate_id="c1", plan_id="p1",
            assignments=(Assignment(assignment_id="a1", task_id="t1", asset_id="ipex-1",
                                    capabilities_met=("dig",)),),
            physics_score=0.87,
            resource_budget=ResourceBudget(energy_j=1.2e6, feasible=True),
            risk_assessment=RiskAssessment(risk_score=0.1)),
        decision=PlanDecision(decision_id="d1", plan_id="p1", decision="approved",
                              decided_by="mission_director:bob", reason="within budget"),
        provenance="MP-05 test plan", transaction_id="txn-42")

    back = plan_from_record(plan_to_record(plan))
    assert back == plan                                        # lossless round-trip through the store
    assert back.decision.decision == "approved"                # carries its decision
    assert back.provenance == "MP-05 test plan"                # carries its provenance
    assert back.transaction_id == "txn-42"                     # transaction-linked
    assert back.candidate.resource_budget.energy_j == 1.2e6    # nested contracts survive


def test_mp05_contracts_are_strict():  # [REQ:MP-05]
    with pytest.raises(ValidationError):                       # extra="forbid" -> unknown field rejected
        PlanDecision(decision_id="d", plan_id="p", bogus_field=1)
