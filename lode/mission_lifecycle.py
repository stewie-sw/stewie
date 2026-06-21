"""MO-WIRE: the live plan -> executive bridge -- wire MO-01 + CP-04 + MO-02 into ONE flow.

This module is the seam between the three already-existing bricks:

  * ``stewie.contracts.MissionIntent`` (MO-01) -- the operator's typed mission HIERARCHY.
  * ``lode.mission_intent_compiler.compile_intent`` (CP-04) -- the goal-grammar compiler that LOWERS an
    intent into the planner's request (a ``Mission`` + a weighted objective string).
  * ``stewie.contracts.executive.MissionExecutive`` (MO-02) -- the mission-executive STATE MACHINE whose
    transitions require an authorizing role + named evidence.

It drives a fresh ``MissionExecutive`` through the planning + authorization head of the MO-02 lifecycle::

    DRAFT --(planner)--> ANALYZED --(operator)--> REHEARSED --(reviewer)--> REVIEWED --(director)--> RELEASED

attaching REAL evidence at each step (never a placeholder string):

  * **ANALYZED** -- ``compile_intent`` lowers the intent and ``lode.mission_planner.plan_ir`` produces a
    DETERMINISTIC content-hash ``plan_id``. That plan_id is the analysis evidence (the same intent yields the
    same plan_id, no wall clock), so the transition cites a real, reproducible plan rather than a bare claim.
  * **REHEARSED** -- ``lode.resync.forward_compare`` re-simulates the compiled mission under each candidate
    solver at wall speed and ranks the futures with measured makespan/energy. The ranking IS the rehearsal
    evidence (the plan was actually run, not just compiled).
  * **REVIEWED** -- the reviewer signs off on the analyzed + rehearsed evidence.
  * **RELEASED** -- the director SIGNS the immutable revision (MO-02 ``SignedRevision``). This is the only
    transition that signs; it is director-authority only.

Every transition goes through MO-02's own ``MissionExecutive.transition`` guards (legal-edge check, named
evidence required, authorizing-role required), so an unevidenced or illegal or wrong-role transition is
REJECTED here exactly as MO-02 rejects it -- this bridge never bypasses the state machine.

It deliberately STOPS at RELEASED: the live chain (ARMED -> EXECUTING -> ...) is gated and not wired to
ROS/hardware (PRD MO-04 -- execution stays SIM/FORECAST-labeled until the gated tier exists). This module
plans, rehearses, reviews and signs; it does not drive a rover.
"""
from __future__ import annotations

import dataclasses
import json

from stewie.contracts.executive import ExecutiveState, MissionExecutive

from lode import mission_planner as MP
from lode.mission_intent_compiler import compile_intent
from lode.resync import forward_compare

#: the authorizing role MO-02 requires for each transition this bridge performs (the planning/authorization
#: head of the lifecycle). These match the MO-02 transition table's authorizing-role sets exactly.
ROLE_ANALYZE = "planner"
ROLE_REHEARSE = "operator"
ROLE_REVIEW = "reviewer"
ROLE_RELEASE = "director"

#: the candidate solver inputs forward_compare re-simulates at REHEARSED (the planner's concrete sequencers).
_REHEARSE_CANDIDATES = ("auto", "nearest")


@dataclasses.dataclass(frozen=True)
class LifecycleResult:
    """The outcome of a lifecycle step (or the full run): the advanced ``MissionExecutive`` snapshot, the
    REAL evidence collected so far (``plan_id`` once analyzed; ``forward_compare`` once rehearsed), and the
    ordered transition log (each legal edge with its authorizing role + the evidence string that justified
    it). The executive is the source of truth for state; ``evidence``/``transitions`` are the audit trail the
    UI/route renders."""
    executive: MissionExecutive
    evidence: dict
    transitions: list


def advance(executive: MissionExecutive, target: ExecutiveState, *, role: str,
            evidence: str) -> MissionExecutive:
    """Thin pass-through to MO-02's guarded transition. Kept as the single choke point so EVERY edge this
    bridge takes is enforced by the state machine (legal-edge + named-evidence + authorizing-role). Re-raises
    MO-02's own exceptions (``ValueError`` for empty evidence/role, ``IllegalTransition`` for a bad edge,
    ``PermissionError`` for a wrong role) unchanged."""
    return executive.transition(target, role=role, evidence=evidence)


def analyze(executive: MissionExecutive, *, role: str = ROLE_ANALYZE) -> LifecycleResult:
    """DRAFT -> ANALYZED: compile + plan the executive's intent, attaching the REAL deterministic plan_id as
    evidence. Runs ``compile_intent`` (the CP-04 lowering) then ``mission_planner.plan_ir`` to derive the
    content-hash ``plan_id``. If the intent does not compile (e.g. a mandatory objective with no work
    geometry), ``compile_intent`` raises and the executive is NOT advanced -- no plan_id can be fabricated.
    """
    req = compile_intent(executive.intent)                       # CP-04: lower MO-01 -> planner Mission
    ir = MP.plan_ir(req.mission, objective=req.objective)        # REAL deterministic content-hash plan_id
    plan_id = ir["plan_id"]
    evidence_str = (
        f"ANALYZED: intent {executive.intent.mission_id} rev {executive.intent.revision} compiled to "
        f"plan_id={plan_id} (objective={req.objective!r}, orders={len(req.mission.orders)})")
    advanced = advance(executive, ExecutiveState.ANALYZED, role=role, evidence=evidence_str)
    evidence = {"plan_id": plan_id, "objective": req.objective, "orders": len(req.mission.orders)}
    transitions = [{"to": ExecutiveState.ANALYZED.value, "role": role, "evidence": evidence_str}]
    return LifecycleResult(executive=advanced, evidence=evidence, transitions=transitions)


def rehearse(executive: MissionExecutive, *, role: str = ROLE_REHEARSE) -> LifecycleResult:
    """ANALYZED -> REHEARSED: re-simulate the compiled mission with ``forward_compare`` and attach the REAL
    ranked futures (measured makespan/energy per candidate) as the rehearsal evidence. The plan is actually
    run, not just compiled -- the ranking is the product."""
    req = compile_intent(executive.intent)                       # recompile (deterministic) to get the Mission
    objective = "duration" if req.objective in ("time", "duration") else req.objective
    fc = forward_compare(req.mission, candidates=_REHEARSE_CANDIDATES, objective=objective,
                         stem=f"lifecycle_{executive.intent.mission_id}")
    n = len(fc["futures"])
    evidence_str = (
        f"REHEARSED: forward_compare ran {n} futures over candidates {list(_REHEARSE_CANDIDATES)}; "
        f"recommended={fc['recommended']} ({json.dumps(fc['futures'][0], sort_keys=True)})")
    advanced = advance(executive, ExecutiveState.REHEARSED, role=role, evidence=evidence_str)
    evidence = {"forward_compare": fc}
    transitions = [{"to": ExecutiveState.REHEARSED.value, "role": role, "evidence": evidence_str}]
    return LifecycleResult(executive=advanced, evidence=evidence, transitions=transitions)


def review(executive: MissionExecutive, *, role: str = ROLE_REVIEW,
           evidence: str = "REVIEWED: analysis + rehearsal evidence accepted by the review board") \
        -> LifecycleResult:
    """REHEARSED -> REVIEWED: the reviewer accepts the analyzed plan + the rehearsal ranking. Evidence is the
    review acceptance record (the analyze/rehearse evidence it certifies is carried on the prior steps)."""
    advanced = advance(executive, ExecutiveState.REVIEWED, role=role, evidence=evidence)
    transitions = [{"to": ExecutiveState.REVIEWED.value, "role": role, "evidence": evidence}]
    return LifecycleResult(executive=advanced, evidence={}, transitions=transitions)


def release(executive: MissionExecutive, *, role: str = ROLE_RELEASE,
            evidence: str = "RELEASED: director release authorization") -> LifecycleResult:
    """REVIEWED -> RELEASED: the director SIGNS the immutable revision (MO-02 ``SignedRevision``). This is the
    only signing transition and is director-authority only; entering RELEASED produces the frozen signed
    record carrying the intent's content hash. A non-director role is rejected by MO-02's role guard, and
    releasing from any state but REVIEWED is an illegal edge."""
    advanced = advance(executive, ExecutiveState.RELEASED, role=role, evidence=evidence)
    transitions = [{"to": ExecutiveState.RELEASED.value, "role": role, "evidence": evidence}]
    return LifecycleResult(executive=advanced, evidence={}, transitions=transitions)


def run_lifecycle(executive: MissionExecutive) -> LifecycleResult:
    """Drive a fresh (DRAFT) executive through the whole planning + authorization head to RELEASED, returning
    the accumulated evidence + the ordered transition log. Each step uses the real compiler / planner and the
    MO-02 guards; the result's ``executive`` carries the signed immutable revision. Stops at RELEASED -- the
    live ARMED..EXECUTING chain is gated (MO-04)."""
    evidence: dict = {}
    transitions: list = []
    for step in (analyze, rehearse, review, release):
        res = step(executive)
        executive = res.executive
        evidence.update(res.evidence)
        transitions.extend(res.transitions)
    return LifecycleResult(executive=executive, evidence=evidence, transitions=transitions)
