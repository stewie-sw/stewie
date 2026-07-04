"""[REQ:MP-05] The mission-planning object model (PRD §7 / §30).

The twelve planning objects -- intent, mission, task, task_dependency, plan, plan_candidate, assignment,
resource_budget, risk_assessment, rehearsal_result, execution_policy, plan_decision -- as strict, frozen,
version-stamped Contract subclasses (:class:`stewie.contracts.Contract`), provenance + transaction-linked to
the world-model store. A ``Plan`` carries its chosen candidate, its ``PlanDecision``, its provenance, and the
world-transaction id, and round-trips losslessly through the store (``plan_to_record`` / ``plan_from_record``,
the store persists JSON).

These are the FORMAL planning contracts of the §30 mission-planning engine (the typed spine model), distinct
from the operational ``lode.planner_model`` dataclasses; the engine rows (MP-06/08/09/10/11) build on them.
"""
from __future__ import annotations

from stewie.contracts import Contract


class Intent(Contract):
    """WHY -- the mission intent a mission serves."""
    intent_id: str
    goal: str
    body: str = "moon"
    priority: int = 0
    provenance: str = ""


class Task(Contract):
    """A unit of work in a mission (a cut/fill/traverse/... with its required capabilities)."""
    task_id: str
    mission_id: str
    kind: str
    params: dict = {}
    required_capabilities: tuple[str, ...] = ()


class TaskDependency(Contract):
    """A precedence edge: ``task_id`` cannot start until ``depends_on`` completes."""
    task_id: str
    depends_on: str
    kind: str = "finish_to_start"


class Mission(Contract):
    """A mission -- the tasks that realize an intent on a body (the typed spine Mission)."""
    mission_id: str
    intent_id: str
    name: str
    body: str = "moon"
    task_ids: tuple[str, ...] = ()
    provenance: str = ""


class Assignment(Contract):
    """A task -> asset assignment with the capabilities it satisfies (MP-08)."""
    assignment_id: str
    task_id: str
    asset_id: str
    capabilities_met: tuple[str, ...] = ()


class ResourceBudget(Contract):
    """The energy/time/drum budget a candidate consumes + whether it is feasible (MP-09)."""
    energy_j: float = 0.0
    time_s: float = 0.0
    drum_cycles: int = 0
    battery_reserve_frac: float = 0.0
    feasible: bool = True


class RiskAssessment(Contract):
    """The risk score + hazards for a candidate (feeds MP-10 / EG-08)."""
    risk_score: float = 0.0
    hazards: tuple[str, ...] = ()
    rehearsal_id: str = ""


class PlanCandidate(Contract):
    """One candidate plan: an assignment set + physics score + resource budget + risk (MP-06/08/09)."""
    candidate_id: str
    plan_id: str
    assignments: tuple[Assignment, ...] = ()
    physics_score: float = 0.0
    resource_budget: ResourceBudget = ResourceBudget()
    risk_assessment: RiskAssessment = RiskAssessment()


class RehearsalResult(Contract):
    """The predicted outcome + risk from rehearsing a candidate (MP-10, on sim branches only)."""
    rehearsal_id: str
    candidate_id: str
    predicted_outcome: str = ""
    risk_score: float = 0.0
    mode: str = "rehearsal"


class ExecutionPolicy(Contract):
    """The abort/rollback rules + safety envelope a plan executes under (links EG-11 / §29.8)."""
    policy_id: str
    abort_rules: tuple[str, ...] = ()
    rollback_rule: str = ""
    max_speed_mps: float = 0.0


class PlanDecision(Contract):
    """The recorded authority decision on a plan (proposed/approved/rejected) -- for the EG-07 audit trail."""
    decision_id: str
    plan_id: str
    decision: str = "proposed"       # proposed | approved | rejected
    decided_by: str = ""             # the deciding role/principal
    reason: str = ""
    timestamp: str = ""


class Plan(Contract):
    """THE plan -- its ordered tasks, the chosen candidate, the decision, provenance, the execution policy, and
    the world-transaction it is linked to. This is what round-trips through the store."""
    plan_id: str
    mission_id: str
    task_ids: tuple[str, ...] = ()
    candidate: PlanCandidate | None = None
    decision: PlanDecision | None = None
    execution_policy: ExecutionPolicy | None = None
    provenance: str = ""
    transaction_id: str = ""


#: the 12 planning contracts (MP-05 acceptance: "each is a Contract subclass").
PLANNING_CONTRACTS = (Intent, Mission, Task, TaskDependency, Plan, PlanCandidate, Assignment,
                      ResourceBudget, RiskAssessment, RehearsalResult, ExecutionPolicy, PlanDecision)


def plan_to_record(plan: Plan) -> str:
    """Serialize a Plan to a world-model store record (the store persists JSON). Lossless."""
    return plan.model_dump_json()


def plan_from_record(record: str) -> Plan:
    """Load a Plan back from a store record -- round-trips losslessly, carrying its nested candidate, decision,
    provenance, and world-transaction link."""
    return Plan.model_validate_json(record)
