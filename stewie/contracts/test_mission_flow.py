"""[REQ:MP-06] The intent-to-world planning FLOW: a real mission dict drives Intent -> Tasks -> capability
matching -> candidate plans -> conserved physics scoring -> rehearsal -> approval end to end, producing an
approved Plan (chosen candidate + PlanDecision), a proposed world-model update, and a report -- deterministically,
without commanding live hardware (LIVE authority is refused)."""
import pytest

from stewie.contracts.governance import EnvironmentMode, ModeAuthorityError
from stewie.contracts.mission_flow import (
    MissionFlowResult,
    run_mission_flow,
)
from stewie.contracts.planning_model import Plan, PlanCandidate, plan_from_record, plan_to_record

# A real IPEx-class dig-and-haul mission on the Moon: excavate + haul 25 kg of regolith. The default asset
# list is the whole real VEHICLES registry (ipex / ez_rassor / rassor2).
_MISSION = {
    "intent_id": "int-clear-pad",
    "goal": "clear a 25 kg regolith obstruction from the landing pad approach",
    "mission_id": "m-pad-01",
    "payload_kg": 25.0,
    "body": "moon",
    "priority": 2,
    "tasks": [
        {"task_id": "t1", "kind": "excavate", "required_capabilities": ["excavate"]},
        {"task_id": "t2", "kind": "haul", "required_capabilities": ["haul", "drive"]},
    ],
    "decided_by": "mission_director:controller",
    "decider_role": "mission_director",
}


def test_mp06_mission_drives_full_flow_to_approved_plan_and_world_update():  # [REQ:MP-06]
    result = run_mission_flow(_MISSION)
    assert isinstance(result, MissionFlowResult)

    # a real Plan carrying its chosen candidate + decision (Intent->...->Approval all ran)
    plan = result.plan
    assert isinstance(plan, Plan) and plan.mission_id == "m-pad-01"
    assert plan.task_ids == ("t1", "t2")
    assert isinstance(plan.candidate, PlanCandidate)
    assert plan.candidate.physics_score > 0.0                       # a real conserved-backend score
    assert len(plan.candidate.assignments) == 2                     # one assignment per task (capability matched)
    assert plan.decision is not None and plan.decision.decision == "approved"
    assert plan.decision.decided_by == "mission_director:controller"

    # it PRODUCED an updated-world proposal: the approved plan links a proposed world transaction
    assert plan.transaction_id == "wtx:plan:m-pad-01"

    # ... and a report summarizing every stage
    rep = result.report
    assert rep.n_tasks == 2 and rep.n_candidates_considered == 3 and rep.n_feasible == 3
    assert rep.chosen_asset_id in {"ipex", "ez_rassor", "rassor2"}
    assert set(rep.assignments) == {"t1->" + rep.chosen_asset_id, "t2->" + rep.chosen_asset_id}
    assert 0.0 <= rep.rehearsal_risk <= 1.0
    assert rep.decision == "approved"
    assert rep.world_update.startswith("PROPOSED world transaction wtx:plan:m-pad-01")


def test_mp06_flow_is_deterministic():  # [REQ:MP-06]
    a = run_mission_flow(_MISSION)
    b = run_mission_flow(_MISSION)
    assert a == b                                                   # conserved physics, no randomness/wall-clock


def test_mp06_result_round_trips_through_the_store():  # [REQ:MP-06]
    result = run_mission_flow(_MISSION)
    # the whole result is a Contract; its Plan round-trips losslessly through the world-model store
    back = plan_from_record(plan_to_record(result.plan))
    assert back == result.plan
    assert back.candidate is not None and back.decision is not None
    # and the full result serializes + reloads losslessly too
    assert MissionFlowResult.model_validate_json(result.model_dump_json()) == result


def test_mp06_flow_refuses_live_authority():  # [REQ:MP-06]
    # the planning flow rehearses -> it may only run in a SIMULATE mode; LIVE (real-command authority) fails closed
    with pytest.raises(ModeAuthorityError):
        run_mission_flow(_MISSION, mode=EnvironmentMode.LIVE)


@pytest.mark.parametrize("mode", [EnvironmentMode.DEV, EnvironmentMode.TRAINING, EnvironmentMode.REHEARSAL])
def test_mp06_flow_runs_in_every_simulate_mode(mode):  # [REQ:MP-06]
    result = run_mission_flow(_MISSION, mode=mode)
    assert result.plan.decision is not None and result.plan.decision.decision == "approved"


def test_mp06_infeasible_mission_is_rejected_and_proposes_no_world_change():  # [REQ:MP-06]
    overloaded = {**_MISSION, "mission_id": "m-overload", "payload_kg": 100000.0}   # exceeds bearing capacity
    result = run_mission_flow(overloaded)
    assert result.report.n_candidates_considered == 3 and result.report.n_feasible == 0
    assert result.plan.candidate is None                           # no feasible candidate chosen
    assert result.plan.decision is not None and result.plan.decision.decision == "rejected"
    assert "no feasible candidate" in result.plan.decision.reason
    assert result.plan.transaction_id == ""                        # rejected -> proposes no world update
    assert result.report.world_update == ""
    assert "entrapment" in result.report.predicted_outcome         # the report says WHY it was infeasible


def test_mp06_capability_unmet_mission_is_rejected():  # [REQ:MP-06]
    # a task needing 'sinter' -- NO bare registry vehicle can sinter (the sinter head is a separate Tool)
    needs_tool = {**_MISSION, "mission_id": "m-sinter",
                  "tasks": [{"task_id": "s1", "kind": "sinter", "required_capabilities": ["sinter"]}]}
    result = run_mission_flow(needs_tool)
    assert result.report.n_candidates_considered == 0
    assert result.plan.candidate is None
    assert result.plan.decision is not None and result.plan.decision.decision == "rejected"
    assert "capability unmet" in result.plan.decision.reason


def test_mp06_a_tooled_asset_satisfies_the_sinter_task():  # [REQ:MP-06]
    # mounting the real sinter Tool on an IPEx grants the 'sinter' capability -> the task now matches
    tooled = {**_MISSION, "mission_id": "m-sinter-ok",
              "tasks": [{"task_id": "s1", "kind": "sinter", "required_capabilities": ["sinter"]}],
              "assets": [{"asset_id": "ipex-sinter", "vehicle": "ipex", "tools": ["sinter"]}]}
    result = run_mission_flow(tooled)
    assert result.report.chosen_asset_id == "ipex-sinter"
    assert result.plan.decision is not None and result.plan.decision.decision == "approved"


def test_mp06_unauthorized_decider_role_cannot_approve():  # [REQ:MP-06]
    # an OPERATOR drives but does NOT grant approve_live_transition (EG-04) -> a feasible plan is still rejected
    op_mission = {**_MISSION, "mission_id": "m-op", "decider_role": "operator"}
    result = run_mission_flow(op_mission)
    assert result.plan.candidate is not None                       # a feasible candidate WAS found
    assert result.plan.decision is not None and result.plan.decision.decision == "rejected"
    assert "does not grant approve authority" in result.plan.decision.reason
    assert result.plan.transaction_id == ""                        # unapproved -> no proposed world change