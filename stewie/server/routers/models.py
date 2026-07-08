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
    learned model must satisfy to be DEPLOYED -- the ML-01/RL-01 deployment-ready gate criteria
    (recorded training/eval lineage, declared typed I/O schemas, positive latency+memory budgets,
    calibration, OOD detector, deterministic fallback, off the command path) and the §25.3 INVARIANT
    that no learned model is on the rover
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
            "dataset_lineage recorded (training-data lineage, RL-01)",
            "eval_split recorded (evaluation lineage, RL-01)",
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


@router.get("/physics/backends")
def get_physics_backends():   # public read (informational backend/model registry; nginx proxies /api/ keyless, like /world/layer-catalog)
    """[REQ:PX-02] The selectable physics-backend registry + the EG-12 model-governance ledger: the engines a
    mission may run its terramechanics on (``selectable_backends`` = list_backends(); only the conserved
    tier2_numpy is release-authority) and every registered physics MODEL with its validated / frozen /
    deprecated status + validated bodies + calibration provenance. This is the read surface behind the mission
    ``physics_backend_id`` selector: a mission may name any ``selectable_backends`` id; the PX-03 Chrono oracle
    (tier3_chrono) is listed here for transparency but is NOT selectable until it conserves mass."""
    from stewie.contracts import physics_model_control as PMC
    from stewie.physics.backend import list_backends

    models = [
        {"model_id": m.model_id, "backend_id": m.backend_id, "version": m.version,
         "validated": m.validated, "frozen": m.frozen, "deprecated": m.deprecated,
         "calibration": m.calibration, "validated_bodies": list(m.validated_bodies), "notes": m.notes}
        for m in PMC.MODELS.values()
    ]
    return {
        "ok": True,
        "selectable_backends": list_backends(),            # a mission physics_backend_id MUST be one of these
        "backend_count": len(list_backends()),
        "live_default_model": PMC.LIVE_DEFAULT_MODEL_ID,
        "models": models,
        "model_count": len(models),
        "note": ("A mission's physics_backend_id selects the terramechanics engine; only conserved, "
                 "release-authority backends are selectable (list_backends()). The models ledger is the EG-12 "
                 "governance record (validated/frozen/deprecated per version); a not-yet-conserving oracle "
                 "(tier3_chrono) appears with validated=False and is excluded from the selectable set."),
    }


@router.get("/physics/compatibility")
def get_physics_compatibility(allow_analog: bool = False, _auth: str = Depends(require_role("operator"))):
    """[REQ:BD-03] The body-by-backend compatibility matrix behind the Plan/Models body + physics-backend
    selectors, plus the SOIL OVERRIDE (``allow_analog``): for each (body, backend) whether the backend SUPPORTS
    the body + the legible verdict reason. Defers to the REAL rules -- ``body_in_regime`` (a MICROGRAVITY body
    like Bennu/Phobos is REFUSED fail-closed: Bekker terramechanics is out-of-regime there) and the PMC model
    ledger's ``validated_bodies``. The soil override mirrors ``params_for_body(allow_analog=True)``: it lets a
    microgravity body run against an EXPLICIT gravity-loaded analog soil (caveated [UNKNOWN]) instead of being
    refused -- the same escape hatch a mission uses. No fabricated support claims."""
    from stewie.contracts import physics_model_control as PMC
    from stewie.physics.backend import list_backends
    from stewie.specs.bodies import BODIES, body_in_regime

    backends = list(list_backends())
    validated: dict[str, set[str]] = {}
    for m in PMC.MODELS.values():
        validated.setdefault(m.backend_id, set()).update(m.validated_bodies)

    bodies = sorted(BODIES)
    matrix: dict[str, dict[str, dict]] = {}
    for body in bodies:
        in_regime = body_in_regime(body)
        row: dict[str, dict] = {}
        for be in backends:
            if not in_regime and not allow_analog:
                row[be] = {"supported": False, "regime_ok": False,
                           "reason": "microgravity: Bekker terramechanics out-of-regime (refused)"}
            elif not in_regime and allow_analog:
                row[be] = {"supported": True, "regime_ok": False,
                           "reason": "microgravity: supported ONLY via explicit gravity-loaded analog soil "
                                     "(caveated [UNKNOWN])"}
            elif body in validated.get(be, set()):
                row[be] = {"supported": True, "regime_ok": True,
                           "reason": "gravity-loaded + validated for this backend"}
            else:
                row[be] = {"supported": False, "regime_ok": True,
                           "reason": "gravity-loaded but not validated for this backend"}
        matrix[body] = row
    return {"ok": True, "allow_analog": allow_analog, "backends": backends, "bodies": bodies, "matrix": matrix}


@router.get("/runtime/profiles")
def get_runtime_profiles():   # public read (informational runtime-profile registry; keyless like /world/layer-catalog)
    """[REQ:RT-01] the runtime profile registry: the execution environments a mission can run in (desktop_sil /
    digital_twin / ros2_replay / gazebo_sim / hil / field_test / live_rover) + each one's command + evidence
    capabilities. The cockpit keys on this to gate what a profile may do -- a SIL / twin / replay / sim profile
    can rehearse + produce evidence but NEVER command the real rover (can_release/can_execute = False); only
    hil / field / live profiles carry live command authority. Sourced from the PRD2 runnable_profile taxonomy."""
    from stewie.specs.runtime_profiles import list_runtime_profiles
    profiles = list_runtime_profiles()
    return {
        "ok": True, "profiles": profiles, "count": len(profiles),
        "note": ("A SIL/twin/replay/sim profile rehearses + produces evidence but holds no live command "
                 "authority (can_release/can_execute False); only hil/field_test/live_rover can release/execute "
                 "on real hardware, escalating command_capability none->bounded->full."),
    }


@router.get("/physics/authority")
def get_physics_authority():   # public read (informational authority registry; keyless like /world/layer-catalog)
    """[REQ:PH-01] the physics backend AUTHORITY registry (the PRD2 physics spine): per backend (tier2_numpy /
    gazebo / chrono / hardware / godot) the authority scope, mass-conservation, per-lifecycle validity (planning
    / rehearsal / release / execute), and the refusal reason where it is not release/execute-eligible. Every
    cost/risk/volume value must name its backend (PH-02). Load-bearing invariants: tier2_numpy is the conserved,
    release-eligible terrain authority; gazebo is robot/sensor sim, NOT the terrain-mutation authority; chrono is
    not release-eligible until conservation+calibration gates pass; godot is rendering only, never authority.
    Complements the PX-02 model ledger (/physics/backends) with the authority model."""
    from stewie.specs.physics_authority import list_backend_authority
    backends = list_backend_authority()
    return {"ok": True, "backends": backends, "count": len(backends),
            "note": ("Every planner/report value must name the backend that produced it. Only tier2_numpy "
                     "(conserved terrain) + hardware (real) are release/execute-eligible; gazebo/chrono are "
                     "rehearsal-only; godot renders and never owns physics or command authority.")}


@router.get("/physics/terramechanics-spine")
def get_terramechanics_spine():   # public read (informational terramechanics-spine registry; keyless like /world/layer-catalog)
    """[REQ:TM-02] the terramechanics spine: the terms the conserved tier2_numpy solver computes (slope,
    roughness, regolith density, contact pressure/bearing, sinkage, slip, traction, compaction resistance,
    drive energy) as inspectable entries -- each with unit, symbol, description, calibration status, and the
    REAL solver callable that produces it. The cockpit inspects these to explain any cost/risk/energy value.
    Every computed term is bound to the live stewie.physics function (import-checked), so the spine cannot drift
    from the solver -- it is not a synthetic catalog."""
    from stewie.specs.terramechanics_spine import list_terra_spine
    terms = list_terra_spine()
    return {"ok": True, "backend": "tier2_numpy", "terms": terms, "count": len(terms),
            "note": ("Each computed term names the real stewie.physics callable that produces it; input terms "
                     "(slope/roughness/density) are terrain/body-derived. Calibration status is honest per term "
                     "(measured vs calibrated Bekker moduli).")}
