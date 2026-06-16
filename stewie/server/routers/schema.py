"""Contract-schema exposure (FS-08 / §25 Phase 1): GET /contracts/schema returns the JSON Schema of
every onboard-autonomy spine contract, so the cockpit and browser tests build against the typed shapes
-- INCLUDING the contracts whose LIVE routes are gated on their systems (ModelArtifact -> FS-12 model
registry, ConstructionSkill -> FS-13 recorded movements). This is the contract DEFINITION (no live
data), the typed fixture FS-08 requires. Public read (schemas are not secret). No app-module import."""
from __future__ import annotations

from fastapi import APIRouter

from stewie import contracts as C

router = APIRouter()

_SPINE = {
    "EphemerisObservation": C.EphemerisObservation,
    "VehicleState": C.VehicleState,
    "FleetState": C.FleetState,
    "ResourceReservation": C.ResourceReservation,
    "WorldState": C.WorldState,
    "BeliefState": C.BeliefState,
    "PlanResult": C.PlanResult,
    "ExecutionEvent": C.ExecutionEvent,
    "ARGUSFactor": C.ARGUSFactor,
    "ModelArtifact": C.ModelArtifact,
    "ConstructionSkill": C.ConstructionSkill,
}


@router.get("/contracts/schema")
def contracts_schema() -> dict:
    """FS-08: the JSON Schema of every spine contract (the typed fixture the cockpit + browser tests
    load to build against the shapes). Live routes for the contracts whose systems exist (ephemeris,
    world, plan, belief, fleet) land alongside; the gated ones (models, skills) ship their schema here
    until their systems do."""
    return {"ok": True, "spine_version": C.SPINE_VERSION,
            "schemas": {name: model.model_json_schema() for name, model in _SPINE.items()}}
