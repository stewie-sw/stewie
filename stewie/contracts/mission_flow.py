"""[REQ:MP-06] The intent-to-world planning FLOW (PRD §7 MP-06 / §30 mission-planning engine).

The single deterministic orchestrator that drives a mission end to end by COMPOSING the existing pieces --
it invents no new physics or planning logic, it only wires the sibling contracts together:

    Intent/Mission/Task           (planning_model)      -- WHY -> WHAT
      -> Capability matching       (capability_matching.match_task)   -- WHAT -> WHICH ASSET
      -> Candidate plans           (planning_model.PlanCandidate)     -- one whole-mission candidate per asset
      -> Physics scoring           (physics_scoring.score_candidate / rank_feasible, CONSERVED backend)
      -> Rehearsal                 (rehearsal.rehearse, in a SIMULATE mode -- REHEARSAL by default)
      -> Approval                  (governance -> planning_model.PlanDecision)
      -> a Plan + a proposed world update + a report

It PRODUCES the plan and the PROPOSED world-model update (the approved plan carries the world-transaction id it
would apply); it does NOT command live hardware -- the Execution -> Reconciliation -> applied-world seam (MP-11 /
EG-08) is the noted follow-up, gated behind LIVE authority the planning flow deliberately never holds. The whole
flow runs under a SIMULATE mode (``require_authority(mode, "simulate")``) so it can rehearse without any
real-command or accepted-world authority, and it is fully DETERMINISTIC (conserved physics, no randomness, no
wall-clock): the same mission dict yields an identical :class:`MissionFlowResult`.

Candidate generation is real, not decorative: every available asset that COVERS all the mission's tasks (via the
real ``match_task``) becomes one whole-mission candidate; each is physics-scored on the conserved backend and
rehearsed; ``rank_feasible`` (the shared ranking authority) selects the best FEASIBLE candidate, and an infeasible
candidate is flagged (never silently ranked). Approval is a governance decision: only a role granting
``approve_live_transition`` (Mission Director / Safety Officer / Admin -- EG-04) can approve, and a plan with no
feasible candidate or an unauthorized decider is rejected (and proposes no world change).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import Field

from stewie.contracts import Contract
from stewie.contracts.capability_matching import CapabilityUnmet, match_task
from stewie.contracts.governance import EnvironmentMode, require_authority, role_permits
from stewie.contracts.physics_scoring import PhysicsScore, rank_feasible, score_candidate
from stewie.contracts.planning_model import (
    Intent,
    Mission,
    Plan,
    PlanCandidate,
    PlanDecision,
    RehearsalResult,
    ResourceBudget,
    RiskAssessment,
    Task,
)
from stewie.contracts.rehearsal import RehearsalCandidate, rehearse
from stewie.physics.backend import PhysicsBackend
from stewie.specs import bodies as B
from stewie.specs import vehicles as V


# ---- the input contract: the mission dict, validated strictly at the boundary --------------------
class TaskSpec(Contract):
    """One unit of work in the mission dict: its kind + the capabilities an asset must have to do it."""
    task_id: str
    kind: str
    required_capabilities: tuple[str, ...] = ()
    params: dict = {}


class AssetSpec(Contract):
    """One available asset in the mission dict: a real ``stewie.specs.vehicles`` platform, optionally with
    mounted tools. ``capabilities`` empty -> derive the EFFECTIVE set from the vehicle + its tools (a bare
    IPEx cannot sinter; with the sinter tool it can)."""
    asset_id: str
    vehicle: str = "ipex"
    tools: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()


class MissionSpec(Contract):
    """The mission dict as a strict typed contract (unknown keys rejected at the boundary). Carries the intent
    (WHY), the tasks (WHAT), the representative payload the physics feasibility is scored against, the available
    assets (empty -> the whole real VEHICLES registry), and WHO decides the approval + under which role."""
    intent_id: str
    goal: str
    mission_id: str
    payload_kg: float = Field(ge=0.0)
    tasks: tuple[TaskSpec, ...] = Field(min_length=1)
    body: str = "moon"
    priority: int = 0
    name: str = ""
    assets: tuple[AssetSpec, ...] = ()
    decided_by: str = "mission_director:controller"
    decider_role: str = "mission_director"
    timestamp: str = ""


# ---- the report + result contracts ---------------------------------------------------------------
class MissionFlowReport(Contract):
    """The end-to-end report the flow emits: one legible summary of every stage (matching, candidate
    generation, physics scoring, rehearsal, approval) + the proposed world update."""
    mission_id: str
    intent_id: str
    body: str
    n_tasks: int
    assignments: tuple[str, ...]            # "task_id->asset_id" for the chosen candidate (() if none)
    n_candidates_considered: int
    n_feasible: int
    chosen_candidate_id: str
    chosen_asset_id: str
    physics_score: float
    rehearsal_risk: float
    predicted_outcome: str
    decision: str                           # approved | rejected
    decision_reason: str
    world_update: str                       # the PROPOSED world-model update ("" when rejected)


class MissionFlowResult(Contract):
    """What the flow produces: the Plan (chosen candidate + decision + the proposed world-transaction link) and
    the report. Both are Contracts, so the whole result round-trips through the world-model store like a Plan."""
    plan: Plan
    report: MissionFlowReport


# ---- internal working records --------------------------------------------------------------------
@dataclass(frozen=True)
class _Asset:
    asset_id: str
    vehicle: str
    caps: frozenset[str]


@dataclass(frozen=True)
class _Scored:
    asset: _Asset
    candidate: PlanCandidate
    physics: PhysicsScore
    rehearsal: RehearsalResult


def _to_planning(spec: MissionSpec) -> tuple[Intent, Mission, list[Task]]:
    """Intent -> Tasks -> Mission: the planning_model objects the flow starts from."""
    provenance = f"mission_flow:{spec.mission_id}"
    intent = Intent(intent_id=spec.intent_id, goal=spec.goal, body=spec.body, priority=spec.priority,
                    provenance=provenance)
    tasks = [Task(task_id=t.task_id, mission_id=spec.mission_id, kind=t.kind, params=t.params,
                  required_capabilities=t.required_capabilities) for t in spec.tasks]
    mission = Mission(mission_id=spec.mission_id, intent_id=spec.intent_id, name=spec.name or spec.goal,
                      body=spec.body, task_ids=tuple(t.task_id for t in tasks), provenance=provenance)
    return intent, mission, tasks


def _assets(spec: MissionSpec) -> list[_Asset]:
    """The available assets: the mission's own list (effective capabilities resolved from vehicle + tools), or
    -- when none are given -- the whole real VEHICLES registry as assets."""
    if spec.assets:
        out: list[_Asset] = []
        for a in spec.assets:
            V.get_vehicle(a.vehicle)                                   # validate against the registry
            caps = frozenset(a.capabilities) if a.capabilities else frozenset(
                V.capabilities_of(a.vehicle, tools=a.tools))
            out.append(_Asset(asset_id=a.asset_id, vehicle=a.vehicle, caps=caps))
        return out
    return [_Asset(asset_id=name, vehicle=name, caps=frozenset(v.capabilities))
            for name, v in V.VEHICLES.items()]


def _candidates(plan_id: str, tasks: list[Task], assets: list[_Asset], *, body: str, payload_kg: float,
                mode: EnvironmentMode | str, backend: PhysicsBackend | None) -> list[_Scored]:
    """One whole-mission candidate per COVERING asset: its per-task assignments (via the real ``match_task``),
    its conserved physics score, and its rehearsal. An asset that cannot cover every task is skipped."""
    scored: list[_Scored] = []
    for asset in assets:
        try:
            assignments = tuple(match_task(t, [(asset.asset_id, asset.caps)]) for t in tasks)
        except CapabilityUnmet:
            continue                                                  # this asset can't cover the whole mission
        physics = score_candidate(body=body, payload_kg=payload_kg, vehicle_name=asset.vehicle, backend=backend)
        rehearsal = rehearse(
            RehearsalCandidate(candidate_id=f"cand:{plan_id}:{asset.asset_id}", payload_kg=payload_kg,
                               vehicle_name=asset.vehicle),
            mode=mode, body=body, backend=backend)
        veh = V.get_vehicle(asset.vehicle)
        drum_cycles = math.ceil(payload_kg / veh.drum_capacity_kg) if veh.drum_capacity_kg > 0 else 0
        budget = ResourceBudget(energy_j=veh.dig_energy_j_per_kg * payload_kg, drum_cycles=drum_cycles,
                                feasible=physics.feasible)
        risk = RiskAssessment(risk_score=rehearsal.risk_score, rehearsal_id=rehearsal.rehearsal_id,
                              hazards=() if physics.feasible else ("bearing_capacity_exceeded",))
        candidate = PlanCandidate(candidate_id=f"cand:{plan_id}:{asset.asset_id}", plan_id=plan_id,
                                  assignments=assignments, physics_score=physics.score,
                                  resource_budget=budget, risk_assessment=risk)
        scored.append(_Scored(asset=asset, candidate=candidate, physics=physics, rehearsal=rehearsal))
    return scored


def run_mission_flow(mission: dict | MissionSpec, *, mode: EnvironmentMode | str = EnvironmentMode.REHEARSAL,
                     backend: PhysicsBackend | None = None) -> MissionFlowResult:
    """Drive a mission through the full intent-to-world flow and return the Plan + report.

    ``mission`` is a mission dict (validated strictly via :class:`MissionSpec`) or a MissionSpec. The flow runs
    under a SIMULATE ``mode`` (default REHEARSAL) -- ``require_authority(mode, "simulate")`` fails closed for
    LIVE/REPLAY/ARCHIVE, so the planning flow can never hold real-command authority. Deterministic: same input ->
    identical result. Produces an approved Plan (chosen candidate + PlanDecision + the proposed world-transaction
    id) when a feasible candidate exists AND the deciding role may approve; otherwise a rejected plan that
    proposes no world change. Live execution + reconciliation of the approved plan is the follow-up seam.
    """
    spec = mission if isinstance(mission, MissionSpec) else MissionSpec.model_validate(mission)
    require_authority(mode, "simulate")                               # the whole flow rehearses -> simulate only
    B.get_body(spec.body)                                            # validate the body against the registry

    intent, mission_obj, tasks = _to_planning(spec)
    plan_id = f"plan:{spec.mission_id}"
    scored = _candidates(plan_id, tasks, _assets(spec), body=spec.body, payload_kg=spec.payload_kg,
                         mode=mode, backend=backend)

    ranked = rank_feasible([s.physics for s in scored])              # only feasible, best first (shared authority)
    chosen: _Scored | None = None
    if ranked:
        best = ranked[0]
        chosen = next(s for s in scored if s.physics is best)        # identity: best is one of the passed objects

    can_approve = role_permits(spec.decider_role, "approve_live_transition")
    if chosen is None:
        decision = "rejected"
        reason = ("capability unmet: no available asset covers all mission tasks" if not scored
                  else "no feasible candidate: every candidate exceeds the conserved bearing-capacity limit")
    elif not can_approve:
        decision = "rejected"
        reason = f"deciding role {spec.decider_role!r} does not grant approve authority (EG-04)"
    else:
        decision = "approved"
        reason = (f"best feasible candidate {chosen.candidate.candidate_id} "
                  f"(physics_score={chosen.physics.score:.4f}, rehearsal risk {chosen.rehearsal.risk_score:.2f})")

    approved = decision == "approved"
    transaction_id = f"wtx:{plan_id}" if approved else ""
    plan_decision = PlanDecision(decision_id=f"dec:{plan_id}", plan_id=plan_id, decision=decision,
                                 decided_by=spec.decided_by, reason=reason, timestamp=spec.timestamp)
    plan = Plan(plan_id=plan_id, mission_id=mission_obj.mission_id, task_ids=mission_obj.task_ids,
                candidate=chosen.candidate if chosen else None, decision=plan_decision,
                provenance=f"MP-06 mission_flow:{mission_obj.mission_id}", transaction_id=transaction_id)

    if approved and chosen is not None:
        kinds = ", ".join(t.kind for t in tasks)
        world_update = (f"PROPOSED world transaction {transaction_id}: apply {len(tasks)} task(s) [{kinds}] via "
                        f"{chosen.asset.asset_id} on {mission_obj.body}; predicted {chosen.rehearsal.predicted_outcome}")
    else:
        world_update = ""

    if chosen is not None:
        assignments = tuple(f"{a.task_id}->{a.asset_id}" for a in chosen.candidate.assignments)
        chosen_candidate_id, chosen_asset_id = chosen.candidate.candidate_id, chosen.asset.asset_id
        physics_score, rehearsal_risk = chosen.physics.score, chosen.rehearsal.risk_score
        predicted_outcome = chosen.rehearsal.predicted_outcome
    elif scored:                                                     # all infeasible: report why (first candidate)
        assignments = ()
        chosen_candidate_id, chosen_asset_id = "", ""
        physics_score, rehearsal_risk = scored[0].physics.score, scored[0].rehearsal.risk_score
        predicted_outcome = scored[0].rehearsal.predicted_outcome
    else:                                                            # capability unmet: nothing scored
        assignments = ()
        chosen_candidate_id, chosen_asset_id = "", ""
        physics_score, rehearsal_risk = 0.0, 0.0
        predicted_outcome = ""

    report = MissionFlowReport(
        mission_id=mission_obj.mission_id, intent_id=intent.intent_id, body=mission_obj.body,
        n_tasks=len(tasks), assignments=assignments, n_candidates_considered=len(scored), n_feasible=len(ranked),
        chosen_candidate_id=chosen_candidate_id, chosen_asset_id=chosen_asset_id, physics_score=physics_score,
        rehearsal_risk=rehearsal_risk, predicted_outcome=predicted_outcome, decision=decision,
        decision_reason=reason, world_update=world_update)

    return MissionFlowResult(plan=plan, report=report)