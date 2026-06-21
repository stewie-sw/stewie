"""Models router (FS-03 work area): the read surface for the cockpit Models pane (engineer/dev surface;
gated to operator+, mirroring the System-pane convention -- System / config / validation are operator+,
so the model+registry inspection surface is too). It is the REGISTRY authority -- the deployable
configuration + substrate registries the system runs on, every one read straight off the real source of
truth (nothing fabricated):

  * SYSTEM PROFILES (stewie.specs.profiles): the deployable runtime profiles (sensor rig + vehicle +
    energy + mapping config) with their EXACT-bytes sha256, VERIFIED/UNVERIFIED status, and source. This
    is the closest real analogue to a deployed-artifact registry: a profile is a versioned, checksummed,
    status-gated config the runtime loads. VERIFIED == safe to deploy; UNVERIFIED is defined but not.

  * VEHICLE REGISTRY (stewie.specs.vehicles): the platform registry with per-vehicle provenance.

  * BODY REGISTRY (stewie.specs.bodies): the soil/terramechanics registry with per-body provenance +
    measured/estimated confidence + Bekker regime.

  * MODEL GOVERNANCE (stewie.contracts.ModelArtifact, FS-12/ML-01/§25.3): the typed contract every
    learned model must satisfy to be DEPLOYED -- the ML-01 deployment-ready gate criteria (declared
    typed I/O schemas, positive latency+memory budgets, calibration, OOD detector, deterministic
    fallback, off the command path) and the §25.3 INVARIANT that no learned model is on the rover
    command path. There is no deployed-model instance registry on this build (FS-12 is the gated future
    surface; the contract definition ships via /contracts/schema), so the honest status is NO learned
    model is deployed on the command path -- which the gate reports, rather than fabricating instances.

Operator+ (engineer/dev inspection surface, gated like System)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from stewie.server.deps import require_role

router = APIRouter()


def _profile_row(pid: str) -> dict:
    """One system profile -> a JSON-safe registry row read off the real loaded profile: id, status,
    substrate, exact-bytes sha256, source, and a few headline config facts (camera count, vehicle mass,
    energy capacity). Deployment-ready == VERIFIED (status gate)."""
    from stewie.specs import profiles as P
    sp = P.load_profile(pid)
    veh = dict(sp.vehicle) if sp.vehicle else {}
    en = dict(sp.energy) if sp.energy else {}
    return {
        "id": sp.profile_id,
        "status": sp.status,
        "substrate": sp.substrate,
        "sha256": sp.sha256,
        "source": sp.source,
        "n_cameras": len(sp.cameras.get("entries", [])) if sp.cameras else 0,
        "dry_mass_kg": float(veh["dry_mass_kg"]) if "dry_mass_kg" in veh else None,
        "capacity_wh": float(en["capacity_wh"]) if "capacity_wh" in en else None,
        "deployment_ready": sp.status == "VERIFIED",   # the runtime status gate (require_verified)
    }


def _vehicle_row(v) -> dict:
    """One vehicle registry entry -> a JSON-safe row (the platform model registry, with provenance)."""
    return {
        "id": v.name,
        "label": v.label,
        "dry_mass_kg": float(v.dry_mass_kg),
        "n_wheels": int(v.n_wheels),
        "capabilities": sorted(v.capabilities),
        "provenance": v.provenance,
    }


def _body_row(b) -> dict:
    """One body registry entry -> a JSON-safe row (the soil/terramechanics model registry, with
    provenance + measured/estimated confidence + the Bekker regime)."""
    return {
        "id": b.name,
        "label": b.label,
        "g_m_s2": float(b.g),
        "bekker_regime": b.bekker_regime,
        "bulk_density_kg_m3": float(b.bulk_density) if b.bulk_density is not None else None,
        "repose_deg": float(b.repose_deg) if b.repose_deg is not None else None,
        "confidence": b.confidence,
        "provenance": b.provenance,
    }


@router.get("/models")
def get_models(_auth: str = Depends(require_role("operator"))):
    """FS-03: the model + configuration registries (system profiles, vehicle registry, body registry --
    all real, all with provenance) + the FS-12/ML-01 model-deployment governance. The ML-01
    deployment-ready criteria and the §25.3 no-command-path invariant are read off the real ModelArtifact
    contract; there is no deployed learned-model instance on this build, so `model_governance.status`
    reports that honestly (no fabricated instances)."""
    from stewie.contracts import ModelArtifact
    from stewie.specs import bodies as B
    from stewie.specs import profiles as P
    from stewie.specs import vehicles as VH

    profiles = [_profile_row(pid) for pid in P.available_profiles()]
    vehicles = [_vehicle_row(v) for v in VH.VEHICLES.values()]
    bodies = [_body_row(b) for b in B.BODIES.values()]

    # ML-01 deployment-ready gate criteria, read off the real ModelArtifact contract (the fields the
    # `deployment_ready` property requires + the §25.3 command-path invariant). No fabricated instances.
    fields = set(ModelArtifact.model_fields)
    governance = {
        "contract": "ModelArtifact (stewie.contracts, FS-12/§25.3)",
        "schema_endpoint": "/contracts/schema",
        # the ML-01 gate: a learned model may be DEPLOYED only when all of these hold.
        "deployment_ready_criteria": [
            "input_schema declared (typed input contract)",
            "output_schema declared (typed estimate contract)",
            "latency_budget_ms > 0",
            "memory_budget_mb > 0",
            "calibrated",
            "ood_detector present",
            "deterministic fallback or rollback_to set",
            "off the rover command path (command_path == False)",
        ],
        # the §25.3 hard invariant: enforced by a field validator on the contract itself.
        "command_path_invariant": "no learned model may be on the rover command path (ModelArtifact rejects command_path=True)",
        "command_path_enforced": "command_path" in fields,
        # honest status: this build ships the contract DEFINITION (schema), not deployed model instances.
        "deployed_models": [],
        "status": ("No learned model is deployed on the command path. The ModelArtifact contract + ML-01 "
                   "deployment-ready gate are defined (schema at /contracts/schema); a live model "
                   "registry (FS-12) is gated and ships no instances on this build."),
    }
    return {
        "ok": True,
        "profiles": profiles,
        "profile_count": len(profiles),
        "profiles_deployable": sum(1 for p in profiles if p["deployment_ready"]),
        "default_profile": P.DEFAULT_PROFILE_ID,
        "vehicles": vehicles,
        "vehicle_count": len(vehicles),
        "default_vehicle": VH.DEFAULT_VEHICLE,
        "bodies": bodies,
        "body_count": len(bodies),
        "default_body": B.DEFAULT_BODY,
        "model_governance": governance,
        "note": ("Registries are the real source of truth: system profiles (specs/profiles.py, exact-bytes "
                 "sha256 + VERIFIED/UNVERIFIED status), the vehicle registry (specs/vehicles.py), and the "
                 "body/soil registry (specs/bodies.py), each with provenance. Model governance is the real "
                 "ModelArtifact (ML-01) deployment-ready gate + §25.3 no-command-path invariant; no learned "
                 "model is deployed on the command path."),
    }
