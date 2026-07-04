"""[REQ:MP-07] The plan-executability gate (PRD §30.3).

No plan is executable until it has ALL EIGHT preconditions: (1) required capabilities, (2) assigned assets,
(3) physics score, (4) resource budget, (5) rehearsal result, (6) safety check, (7) approval record,
(8) rollback/abort rule. This is the PLANNING-domain mirror of EG-05's §29.5 live gate
(:mod:`stewie.contracts.live_gate`). Each precondition maps to a real source in the mission-planning stack --
several already exist on a ``lode.mission_planner.PlanResult`` (``validation`` = as-built/safety acceptance,
``endurance`` = single-sortie resource reachability, ``provenance``/``trips`` = the physics-scored sim; a
RELEASED SignedRevision = the human approval). This makes the eight explicit + checkable.

The typed gate is delivered here; wiring it into ``plan()`` / the ``/executive/run`` flow (deriving each
precondition from the real PlanResult/executive state) is the noted [REQ:MP-07] integration follow-up.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass


class PlanNotExecutable(PermissionError):
    """Raised when a plan is submitted for execution before all eight §30.3 preconditions hold."""


@dataclass(frozen=True)
class PlanPreconditions:
    """§30.3 -- ALL EIGHT must hold before a plan is executable (with the real source of each)."""
    required_capabilities: bool = False   # the plan's capability requirements are declared + satisfiable
    assigned_assets: bool = False         # an asset/vehicle is assigned to each task (fleet allocation)
    physics_score: bool = False           # each candidate carries a conserved PhysicsBackend score (PX-04)
    resource_budget: bool = False         # energy/battery/time budget is feasible (PlanResult.endurance/totals)
    rehearsal_result: bool = False        # a rehearsal (MO-02 REHEARSED / sim) produced predicted outcomes
    safety_check: bool = False            # as-built acceptance + safety limits pass (PlanResult.validation, EG-11)
    approval_record: bool = False         # a human approval is recorded (RELEASED SignedRevision, EG-05)
    rollback_abort_rule: bool = False     # a rollback / abort rule is defined for the plan

    def unmet(self) -> list[str]:
        return [f.name for f in dataclasses.fields(self) if not getattr(self, f.name)]

    def all_met(self) -> bool:
        return not self.unmet()


def is_executable(preconditions: PlanPreconditions) -> bool:
    """True iff ALL EIGHT §30.3 preconditions hold."""
    return preconditions.all_met()


def require_executable(preconditions: PlanPreconditions) -> None:
    """The plan-executability chokepoint: raise PlanNotExecutable (naming the unmet preconditions) unless a
    plan has all eight. The planning-domain mirror of EG-05's require_live_token."""
    if not preconditions.all_met():
        raise PlanNotExecutable(f"plan not executable: unmet preconditions {preconditions.unmet()}")
