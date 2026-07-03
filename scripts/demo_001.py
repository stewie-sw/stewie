"""[REQ:DE-01] Demo 001 -- one IPEx-dig VERTICAL SLICE proving the STEWIE platform loop end-to-end from
EXISTING code (Path A, no new physics):

    body/profile  ->  selected conserved PhysicsBackend  ->  plan  ->  conserved execution + world/
    terrain-memory transaction  ->  RegolithVolumeEstimate reconcile  ->  a deterministic evidence artifact.

Real body constants + the conserved authority; no synthetic/fabricated values. Same inputs -> same
`content_sha` (the demo is deterministic; nothing wall-clock or random enters the artifact hash).
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

import lode.mission_planner as MP
from leap.volume_evidence import siteplan_volume_evidence
from lode.planner_acceptance import mission_terrain_delta
from stewie.physics.backend import get_backend
from stewie.server.world_state import WorldStateService
from stewie.specs.bodies import get_body
from stewie.twin import versioned as vt

#: the demo mission: an IPEx cut ("dig") on the Moon -- a rectangle graded to depth. Conserved: the cut mass is
#: moved into the drum. Fixed geometry -> deterministic.
_MISSION = {
    "name": "demo-001", "body": "moon",
    "orders": [
        {"action": "IPEx dig pad", "kind": "cut", "x": 0.0, "y": 0.0, "depth_m": 0.15,
         "shape": {"kind": "rectangle", "w": 4.0, "h": 3.0}},
    ],
}


def run_demo_001() -> dict:
    """Run the vertical slice and return a DETERMINISTIC evidence artifact."""
    body = get_body("moon")
    backend = get_backend("tier2_numpy")
    if not backend.info().conserves_mass:
        raise RuntimeError("Demo 001 requires a conserved (release-authority) physics backend")

    mission = MP.mission_from_dict(_MISSION)
    pr = MP.plan(mission)                                    # PlanResult (RB-03 canonical plan)

    # conserved execution: the terrain delta the mission imprints (validate_plan's rasterize->execute path).
    delta = mission_terrain_delta(mission)
    a_sha = hashlib.sha256(np.ascontiguousarray(delta["as_built"], dtype=float).tobytes()).hexdigest()

    # world/terrain-memory transaction (execute->remember): the released plan + the conserved terrain.
    plan_id = str((pr.provenance or {}).get("plan_id") or "demo-001")
    wss = WorldStateService(twin=lambda: vt.TwinStore(
        np.zeros((int(delta["rows"]), int(delta["cols"])), dtype=float), cell_m=float(delta["cell_m"])))
    wss.record_plan(plan_id=plan_id, provenance="DE-01 released plan",
                    mission="demo-001", site="haworth", body="moon")
    wss.record_terrain(authority_sha=a_sha, provenance="DE-01 conserved IPEx dig",
                       mission="demo-001", site="haworth", body="moon")

    # reconcile: RegolithVolumeEstimate (conserved-mass self-check + design-time density envelope).
    vol = siteplan_volume_evidence(mission, work_order_id="demo-001", transaction_id=plan_id,
                                   density_kg_m3=float(body.bulk_density))

    # deterministic evidence artifact: only order-invariant fields enter content_sha (no wall-clock / txn time).
    artifact = {
        "demo": "001",
        "body": body.name,
        "backend": {"id": backend.info().id, "authority_class": backend.info().authority_class,
                    "conserves_mass": backend.info().conserves_mass},
        "plan": {"plan_id": plan_id, "totals": pr.totals},
        "world_transaction": {"n": wss.transaction_count(), "authority_sha": a_sha,
                              "latest_provenance": wss.latest().provenance},
        "reconcile": {"mass_moved_kg": float(delta["mass_moved_kg"]),
                      "acceptance": vol.acceptance, "volume": vol.model_dump()},
    }
    artifact["content_sha"] = hashlib.sha256(
        json.dumps(artifact, sort_keys=True, default=str).encode()).hexdigest()
    return artifact


if __name__ == "__main__":
    import pprint
    pprint.pprint(run_demo_001())
