"""MO-WIRE executive router: the live plan -> executive advance surface.

``POST /executive/advance`` takes a canonical MO-01 ``MissionIntent`` and drives a fresh MO-02
``MissionExecutive`` through the planning + authorization head of the lifecycle
(DRAFT -> ANALYZED -> REHEARSED -> REVIEWED -> RELEASED) via ``lode.mission_lifecycle.run_lifecycle``,
attaching REAL evidence at each transition (the compiler's deterministic plan_id at ANALYZED; the real
forward_compare ranking at REHEARSED) and honouring MO-02's role + evidence guards. It returns the reached
state, the signed immutable revision, the evidence bundle, and the ordered transition log.

The route is DIRECTOR-GATED (``require_director``): RELEASED is a director-authority signing transition, so
the whole advance is exposed only to a director identity. It does NOT command a rover -- the live
ARMED..EXECUTING chain is gated (PRD MO-04); this route plans, rehearses, reviews and signs only, and the
returned revision stays SIM/FORECAST-derived (the compiler runs on the conserved sim authority).

A malformed intent or an uncompilable mission (e.g. a mandatory objective with no work geometry) yields a
400 with the validator/compiler error -- nothing is advanced and no plan_id is fabricated. No app-module
import (the lifecycle bridge is a leaf), so no router<->app cycle.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from stewie.contracts import MissionIntent
from stewie.contracts.executive import MissionExecutive
from stewie.server import objects as OBJ
from stewie.server import state
from stewie.server.deps import require_director, require_role
from stewie.server.services import log_event

log = logging.getLogger("stewie.server")
router = APIRouter()


@router.post("/executive/advance")
def advance_executive(intent: MissionIntent, _auth: str = Depends(require_director)) -> JSONResponse:
    """Drive a fresh MissionExecutive for ``intent`` through DRAFT -> RELEASED (MO-WIRE), returning the
    reached state + signed revision + the real evidence (plan_id, forward_compare) + transition log. The
    compiler/planner run on the conserved sim authority, so the result is SIM/FORECAST-labeled (no live ROS
    command -- the execution tier is gated, MO-04). Director-gated: RELEASED is a director-signing edge."""
    from lode import mission_lifecycle as LC
    ex = MissionExecutive.start(intent)
    try:
        res = LC.run_lifecycle(ex)
    except (ValueError, KeyError) as e:
        # an uncompilable intent (no work geometry, bad frame, ...) -> 400; nothing advanced, no fabrication.
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    rel = res.executive.released_revision
    persisted = _persist_released_revision(rel, res)     # [dispatch-audit R1] freeze it in the durable store
    log_event(_auth, "executive.advance",
              f"{intent.mission_id} rev {intent.revision} -> {res.executive.state.value}")
    return JSONResponse(content={
        "ok": True,
        "label": "sim",                                   # MO-04: planned/rehearsed on the sim authority
        "state": res.executive.state.value,
        "signed_revision": rel.model_dump(mode="json") if rel is not None else None,
        "revision_persisted": persisted,                  # [dispatch-audit R1] durably frozen by content_hash
        "evidence": res.evidence,
        "transitions": res.transitions,
    })


class ReleasePlanRequest(BaseModel):
    """The cockpit's current build-order queue, for the live "release the current plan" surface."""
    orders: list[dict] = Field(max_length=1000)
    body: str = "moon"
    mission_id: str = "cockpit-release"
    revision: int = Field(default=0, ge=0)


def _command_authority(rel: object) -> dict | None:
    """[REQ:FS-28] Freeze the Release-pane command-authority card at sign time: the immutable plan hash +
    director sign-off (from the signed revision), the runtime + sensor profile (from the active system
    profile -- real values, no fabrication), the live deployment namespace released missions bind to (the
    rc.py convention), the AG-08 director authorization a released revision carries, and the SF-01 watchdog
    deadline that governs execution. None when nothing was released."""
    if rel is None:
        return None
    import inspect

    from stewie.bridge.rc_contract import SafingWatchdog
    from stewie.specs import profiles
    prof = profiles.load_profile()
    sf01_deadline_s = inspect.signature(SafingWatchdog.__init__).parameters["deadline_s"].default
    return {
        "plan_hash": getattr(rel, "content_hash"),
        "signed_by": getattr(rel, "signed_by"),
        "runtime_profile": prof.profile_id,
        "sensor_profile": str(prof.sensors.get("selected_depth_source")),
        "namespace": "live",                    # released missions bind to the live namespace (rc.py)
        "authorized": True,                     # AG-08: a released revision is director-signed
        "watchdog_deadline_s": float(sf01_deadline_s),   # SF-01 watchdog governs execution
    }


def _persist_released_revision(rel: object, res: object) -> bool:
    """[dispatch-audit R1] Freeze the just-signed release into the durable revision store, keyed by its
    immutable content_hash, so a later run / RC can BIND the exact signed artifact (the R2 foundation)
    instead of rebuilding from mutable orders. Stores the whole frozen artifact: the SignedRevision (incl.
    the full intent), the analyze/rehearse evidence (plan_ir hash + forward_compare), and the ordered
    approval transitions. BEST-EFFORT: the SIGNING already happened and is authoritative in the response;
    a durable-store hiccup must not 500 a valid release -- it is surfaced honestly as ``revision_persisted:
    false`` and logged. Returns whether the revision is now durably present."""
    if rel is None:
        return False
    from stewie.server import db
    art = {
        "content_hash": getattr(rel, "content_hash"),
        "revision": getattr(rel, "revision", 0),
        "mission_id": getattr(getattr(rel, "intent", None), "mission_id", ""),
        "signed_by": getattr(rel, "signed_by", ""),
        "signed_revision": getattr(rel, "model_dump")(mode="json"),   # the full frozen SignedRevision
        "evidence": getattr(res, "evidence", {}) or {},
        "transitions": getattr(res, "transitions", []) or [],
    }
    try:
        return bool(db.persist_release_revision(art))
    except Exception as e:   # noqa: BLE001 -- R1: durability is a projection of the authoritative signature;
        log.warning("release-revision persist failed (release still valid): %s", e)   # never fail a valid release
        return False


@router.post("/executive/release-plan")
def release_plan(req: ReleasePlanRequest, _auth: str = Depends(require_director)) -> JSONResponse:
    """Director-gated: build a canonical MO-01 MissionIntent from the cockpit's current build-order queue
    (``lode.mission_intent_compiler.intent_from_orders``) and drive it through the MO-02 lifecycle to
    RELEASED -- the live "release the current plan" surface. Each build order (cut|fill|sinter) becomes a
    mandatory objective carrying its order_kind, so the full plan round-trips; non-build orders (e.g. goto
    path waypoints) are NOT objectives and are returned in ``skipped`` so the surface shows them honestly
    (nothing is dropped or faked). Same SIM/FORECAST labeling + 400-on-uncompilable contract as
    /executive/advance; signs only, no live ROS command (the execution tier is gated, MO-04)."""
    from lode import mission_lifecycle as LC
    from lode.mission_intent_compiler import intent_from_orders
    try:
        intent, skipped = intent_from_orders(
            list(req.orders), mission_id=req.mission_id, approver=_auth, body=req.body, revision=req.revision)
        if not intent.objectives:
            return JSONResponse(status_code=400, content={
                "ok": False, "skipped": skipped,
                "error": "no build orders to release (cut/fill/sinter): the queue has only path/other orders"})
        res = LC.run_lifecycle(MissionExecutive.start(intent))
    except (ValueError, KeyError, TypeError) as e:
        # #300: a malformed order field (a list/object where a number is expected) is a client 400, not an
        # uncaught TypeError -> 500. an uncompilable plan (no work geometry, bad frame, ...) -> 400 too.
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e), "skipped": []})
    rel = res.executive.released_revision
    persisted = _persist_released_revision(rel, res)     # [dispatch-audit R1] freeze it in the durable store
    log_event(_auth, "executive.release_plan",
              f"{req.mission_id}: {len(intent.objectives)} objectives -> {res.executive.state.value}")
    from stewie.server.audit_log import record_action                                    # [REQ:EG-07]
    record_action(_auth, "executive.release_plan", location=req.mission_id, mode="sim",
                  reason=f"{len(intent.objectives)} objectives released",
                  before_state="planned", after_state=res.executive.state.value,
                  evidence=(getattr(rel, "content_hash", "") if rel is not None else ""))   # F5: SignedRevision.content_hash (there is no plan_hash key)
    return JSONResponse(content={
        "ok": True,
        "label": "sim",
        "state": res.executive.state.value,
        "signed_revision": rel.model_dump(mode="json") if rel is not None else None,
        "command_authority": _command_authority(rel),   # [REQ:FS-28] frozen Release-pane authority card
        "revision_persisted": persisted,                 # [dispatch-audit R1] durably frozen by content_hash
        "evidence": res.evidence,
        "transitions": res.transitions,
        "released_objectives": len(intent.objectives),
        "skipped": skipped,
    })


class RunRequest(BaseModel):
    """#245: run a released build plan as a SIM execution. Same queue shape as release-plan + the site.

    [dispatch-audit R2 / F1] ``revision_hash`` BINDS the run to a durable R1 released revision: when set,
    the executed plan is the FROZEN signed intent (``compile_intent`` of the stored intent) and the client
    ``orders`` are IGNORED, so the run provably executes exactly what was signed -- not a rebuild from mutable
    browser orders. When unset, the legacy orders path runs (unbound; the cockpit migrates to revision_hash
    in R7). ``orders`` is optional so a bound run carries no plan geometry at all."""
    orders: list[dict] = Field(default_factory=list, max_length=1000)
    body: str = "moon"
    site: str = Field("haworth", max_length=40)
    mission_id: str = "cockpit-run"
    revision: int = Field(default=0, ge=0)
    revision_hash: str | None = Field(default=None, max_length=64)   # [R2] bind to an immutable revision


def _remember_sim_terrain(wss, mission, out, *, site: str, body: str, mission_id: str) -> None:
    """gap N1/N2: close the execute->remember loop for a COMPLETED SIM run. Fold the mission's conserved
    terrain delta into the site's TerrainMemory (so the next /plan reads it via CurrentTerrainView),
    record the advanced authority_sha into the world log, and commit the run's final belief. SIM-labeled.
    Only a terrain-changing run (mass_moved_kg > 0) is remembered. Uses the SAME per-site lock as POST
    /twin/terrain so the two record paths cannot lose each other's RMW. Mirrors that route's fold."""
    import dataclasses as _dc
    import hashlib as _hl

    import numpy as _np

    from lode.planner_acceptance import mission_terrain_delta
    from stewie.server.world_state import _terrain_lock
    from stewie.server.world_state import compensating
    from stewie.specs.config import data_dir
    from stewie.twin import terrain_memory as TM
    d = mission_terrain_delta(mission)
    if float(d.get("mass_moved_kg", 0.0)) <= 0.0:
        return                                                   # nothing built -> nothing to remember
    with _terrain_lock(site):                                    # #278: atomic RMW, shared with /twin/terrain
        prior = TM.snapshot_site(data_dir(), site)               # DT-03: prior state for a compensating rollback
        mem = TM.load_site(data_dir(), site)
        if mem is None:
            mem = TM.TerrainMemory(site=site, rows=int(d["rows"]), cols=int(d["cols"]),
                                   cell_m=float(d["cell_m"]), origin=(float(d["x0"]), float(d["y0"])))
        mem.apply_subgrid(d["delta"], sub_origin=(d["x0"], d["y0"]), cell_m=d["cell_m"],
                          mission=str(mission.name), mass_moved_kg=d["mass_moved_kg"])
        TM.save_site(data_dir(), mem)
        a_sha = _hl.sha256(_np.asarray(mem.cumulative_delta(), dtype=_np.float64).tobytes()).hexdigest()
        # DT-03: the terrain fold is persisted; its as-built world-log record must be ATOMIC with it. On a
        # commit failure, COMPENSATE (restore the prior TerrainMemory file) so the store never runs ahead of
        # /world/transaction, then re-raise so the caller surfaces it (no best-effort swallow).
        with compensating(lambda: TM.restore_site(data_dir(), site, prior), what="SIM remember"):
            wss.record_terrain(authority_sha=a_sha, mission=str(mission_id), site=str(site), body=str(body),
                               provenance=f"SIM as-built: {mission_id}")
    belief = out.get("belief") if isinstance(out, dict) else None
    if belief is not None:                                       # commit the run's final belief (a separate snapshot)
        belief_d = _dc.asdict(belief) if (_dc.is_dataclass(belief) and not isinstance(belief, type)) else belief
        wss.record_belief(belief=belief_d, provenance=f"SIM run belief: {mission_id}")


def _remember_sim_traffic(wss, mission, out, *, site: str, body: str, mission_id: str, dem) -> dict | None:
    """[REQ:TW-11] fold a completed SIM run's REAL executed drive path into the site's persistent TrafficMemory
    (per-cell traversal hardening: cumulative-load densification toward the conserved Bekker equilibrium,
    H-09-safe), persist it, and record ONE DT-01 world-log event -- but ONLY when NEW load actually hardened
    the road (the hash advances only on new load, per the accumulator's idempotent apply). BEST-EFFORT: the
    traffic layer is an enhancement over the conserved terrain fold, so a failure here is logged and swallowed,
    never failing an otherwise-good run (unlike the mass-conserving terrain fold, which is correctness-critical
    and surfaces). Uses the same per-site lock + DT-03 compensating rollback pattern as the terrain fold."""
    try:
        from stewie.server import traffic_fold as TF
        from stewie.server.world_state import _terrain_lock, compensating
        from stewie.specs.config import data_dir
        from stewie.twin import traffic_memory as TW
        with _terrain_lock(site):                                # share the per-site RMW lock with the terrain fold
            prior = TW.snapshot_site(data_dir(), site)           # DT-03 pre-mutation snapshot for a compensating rollback
            mem = TF.traffic_from_run(out, charger=tuple(mission.charger), dem=dem, site=site,
                                      data_dir=data_dir(), mission_id=mission_id)
            if mem is None:
                return None                                      # nothing new hardened (idempotent re-commit / off-crop)
            TW.save_site(data_dir(), mem)
            with compensating(lambda: TW.restore_site(data_dir(), site, prior), what="SIM traffic"):
                wss.record_execution_event(authority_sha=None, provenance=f"SIM traffic hardening: {mission_id}",
                                           mission=str(mission_id), site=str(site), body=str(body))
        return mem.summary()
    except Exception as e:   # noqa: BLE001 -- TW-11 traffic hardening is an enhancement; never fail a good run
        log.warning("SIM traffic fold for %s failed (non-fatal): %s", mission_id, e)
        return None


def _rollback_abort_rule(run: dict) -> bool:
    """[REQ:MP-07] F24: the §30.3 rollback/abort-rule precondition, as a REAL predicate. The abort/safing
    rule is defined + was in force exactly when the run reached a GOVERNED terminal of the abort-capable
    executive -- COMPLETED (nominal) or SAFED (the abort rule fired). A run stuck mid-lifecycle or a
    malformed record (no governed terminal) cannot attest a rollback/abort rule, so it returns False. This
    replaces the prior ``"safed" in transitions or run.get("safed") is not None``, whose second clause was a
    tautology (``safed`` is always a bool) that made the precondition constant-True."""
    return run.get("final_state") in ("completed", "safed")


@router.post("/executive/run")
def executive_run(req: RunRequest, identity: str = Depends(require_director)) -> JSONResponse:
    """#245: execute a RELEASED build plan as a SIM run -- ARMED -> EXECUTING -> (COMPLETED | SAFED) over
    the conserved closed-loop sim, sequenced by lode.sim_execution.run_sim_execution. Builds the MO-01
    intent from the queue, drives the MO-02 head to RELEASED, runs run_closed_loop on the chosen site DEM,
    then steps the live chain. DIRECTOR-gated (#276, two-role ConOps): this route drives the plan to RELEASED,
    and RELEASED is a director-authority MO-02 signing edge -- so an operator must NOT be able to drive it (the
    prior require_role('operator') let an operator forge a director-signed release). Operators plan + rehearse;
    a director releases (here, or via /executive/release-plan). DataLabel SIM ONLY -- this drives the in-process
    plant, never the gated real-rover command path. 400 on an uncompilable / no-build-order plan."""
    from lode import autonomy as AUT
    from lode import mission_lifecycle as LC
    from lode import mission_planner as MP
    from lode.mission_intent_compiler import compile_intent, intent_from_orders
    from lode.sim_execution import run_sim_execution
    skipped: list = []
    bound_revision: str | None = None
    try:
        if req.revision_hash:
            # [dispatch-audit R2 / F1] BIND: execute the FROZEN signed revision, never the mutable client
            # orders. Fetch the durable R1 artifact; an unknown hash is refused (release it first). The
            # executed mission is compile_intent(signed_intent).mission -- the exact signed content -- so the
            # run provably runs what was released. The client's ``orders`` (if any) are ignored.
            from stewie.server import db
            art = db.read_release_revision(req.revision_hash)
            if art is None:
                return JSONResponse(status_code=400, content={
                    "ok": False, "error": f"revision_hash {req.revision_hash!r} is not a released revision "
                    "(release the plan first)"})
            intent = MissionIntent.model_validate(art["signed_revision"]["intent"])
            released = LC.run_lifecycle(MissionExecutive.start(intent)).executive
            rel = released.released_revision
            if rel is None or rel.content_hash != req.revision_hash:   # tamper-evident re-derivation
                return JSONResponse(status_code=409, content={
                    "ok": False, "error": "released revision hash mismatch (store integrity)"})
            mission = compile_intent(intent).mission                   # the SIGNED content -> executed mission
            body = mission.body                                        # body from the signed intent (R4 frame)
            bound_revision = req.revision_hash
        else:
            intent, skipped = intent_from_orders(
                list(req.orders), mission_id=req.mission_id, approver=identity, body=req.body,
                revision=req.revision)
            if not intent.objectives:
                return JSONResponse(status_code=400, content={
                    "ok": False, "skipped": skipped, "error": "no build orders to run (cut/fill/sinter)"})
            released = LC.run_lifecycle(MissionExecutive.start(intent)).executive
            mission = MP.mission_from_dict({"name": req.mission_id, "body": req.body,
                                            "orders": list(req.orders), "charger": [0.0, 0.0]})
            body = req.body
        dem, origin = state.moon_dem(req.site) if body == "moon" else (None, (0.0, 0.0))
        if body == "moon":
            # [dispatch-audit R2/F4] execute on the SAME composed as-built surface the plan/review used
            # (state.as_built_dem = remembered/observed terrain over the raw DEM, plan.py:208), so an
            # as-built or observed hazard present during planning is present during SIM execution too --
            # not the pristine raw site DEM the run previously loaded (audit finding 3: inputs diverge).
            dem = state.as_built_dem(req.site, dem, origin)
        out = AUT.run_closed_loop(mission, dem=dem, dem_origin=origin)
        run = run_sim_execution(released, out.get("legs", []))
    except (ValueError, KeyError, TypeError) as e:    # #300: malformed order field -> 400, not an uncaught 500
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e), "skipped": skipped})
    run_id = secrets.token_hex(6)
    rec = {"label": run["label"], "final_state": run["final_state"], "transitions": run["transitions"],
           "n_legs_total": run["n_legs_total"], "safed": run["safed"], "nonnominal_legs": run["nonnominal_legs"],
           "executed_legs": run["executed_legs"], "mission_id": req.mission_id, "site": req.site}
    # gap W1: the SIM run is one canonical world-state record -- commit the released plan + per-leg
    # ExecutionEvents through the one DT-01 log so /world/transaction reflects the executed mission.
    # gap N1/N2: and CLOSE the execute->REMEMBER loop -- a completed terrain-changing SIM run folds its
    # conserved delta into the site's TerrainMemory (so the NEXT /plan reads the remembered surface via
    # CurrentTerrainView), advances the authority_sha, and commits the run's final belief. All SIM-labeled.
    # DT-03: this world-state commit is now ATOMIC with persisting the run -- the run is saved ONLY after the
    # commit durably succeeds, and _remember_sim_terrain compensates its TerrainMemory save on a commit
    # failure. So no store (TerrainMemory / run record) can run ahead of /world/transaction; a world-log
    # failure is surfaced (500), not swallowed.
    try:
        from stewie.server.world_state import commit_sim_run
        wss = state.world_state_service()
        commit_sim_run(wss, run, mission=req.mission_id, site=req.site, body=body,
                       plan_id=req.mission_id)
        if not run.get("safed"):
            _remember_sim_terrain(wss, mission, out, site=req.site, body=body, mission_id=req.mission_id)
            # [REQ:TW-11] fold the run's driven path into the per-site TrafficMemory (best-effort, non-fatal).
            _remember_sim_traffic(wss, mission, out, site=req.site, body=body,
                                  mission_id=req.mission_id, dem=dem)
    except Exception as e:   # noqa: BLE001 -- DT-03: world-state commit failed; the terrain fold self-
        # compensated and the run is NOT persisted ahead of the failed log -- surfaced, not swallowed.
        log.warning("world-state commit for SIM run %s failed; run not persisted: %s", run_id, e)
        return JSONResponse(status_code=500,
                            content={"ok": False, "error": f"world-state commit failed: {e}"})
    OBJ.save_run(run_id, rec, owner=identity)                  # #245: persist the run only after the world state is durable
    log_event(identity, "executive.run",
              f"{run_id} {req.mission_id}: {run['final_state']} ({run['n_legs_total']} legs)")
    from stewie.server.audit_log import record_action                                    # [REQ:EG-07]
    record_action(identity, "executive.run", location=f"{req.mission_id}@{req.site}", mode="sim",
                  reason=f"SIM run {run_id}", before_state="released", after_state=str(run["final_state"]),
                  evidence=f"run_id={run_id};legs={run['n_legs_total']};safed={run.get('safed')}")
    # [REQ:MP-07] the plan-executability card: the 8 §30.3 preconditions derived from the REAL released +
    # rehearsal (closed-loop) + run state -- reported on the run, so an operator sees which gates held.
    from stewie.contracts.plan_gate import PlanPreconditions, is_executable
    from stewie.physics.backend import get_backend
    _pre = PlanPreconditions(
        required_capabilities=bool(intent.objectives),
        assigned_assets=bool(intent.objectives),                     # the released plan runs on the site vehicle
        physics_score=get_backend("tier2_numpy").conserves_mass(),   # the SIM ran on the conserved authority
        resource_budget=not bool(run.get("safed")),                  # a SAFED run hit a resource/safety stop
        rehearsal_result=bool(out.get("legs")),                      # the closed-loop rehearsal produced legs
        safety_check=(run["final_state"] == "completed"),            # completed = as-built acceptance held
        approval_record=(str(released.state.value) == "released"),   # director-signed RELEASED
        rollback_abort_rule=_rollback_abort_rule(run))               # F24: governed terminal, not a tautology
    executability = {"executable": is_executable(_pre), "unmet": _pre.unmet(),
                     "preconditions": {k: getattr(_pre, k) for k in _pre.__dataclass_fields__}}
    # [REQ:EG-08] reconciliation: the run's predicted-vs-observed ENERGY residual (budgeted nominal_J vs the
    # slip-truth true_J) reconciled against the estimator's OWN energy sigma -> a world-update Proposal, plus a
    # model-update Proposal when the surprise exceeds measurement noise -- feeding the EG-08 lifecycle (MP-11).
    from stewie.contracts.reconciliation_step import reconcile_prediction
    _legs = out.get("legs", [])
    _pred_j = sum(float(lg.get("nominal_J", 0.0)) for lg in _legs)
    _obs_j = sum(float(lg.get("true_J", 0.0)) for lg in _legs)
    _tol_j = sum(float(lg.get("energy_sigma_J", 0.0)) for lg in _legs)
    _recon = reconcile_prediction(_pred_j, _obs_j, quantity="energy_J", sensor_tolerance=_tol_j,
                                  provenance=f"run:{run_id}", proposal_stem=f"run:{run_id}")
    reconciliation = {
        "quantity": "energy_J", "predicted": _pred_j, "observed": _obs_j,
        "residual": _recon.residual.residual, "implicates_model": _recon.residual.implicates_model,
        "proposals": [{"proposal_id": p.proposal_id, "state": p.state.value, "confidence": p.confidence,
                       "model_error": p.model_error, "change": p.change} for p in _recon.proposals]}
    if _recon.residual.implicates_model:                                                 # [REQ:EG-08] audit
        record_action(identity, "executive.reconcile", location=f"{req.mission_id}@{req.site}", mode="sim",
                      reason="energy residual exceeds estimator sigma -> model-update proposed",
                      before_state=f"predicted={_pred_j:.1f}J", after_state=f"observed={_obs_j:.1f}J",
                      evidence=f"residual={_recon.residual.residual:.1f}J;proposals={len(_recon.proposals)}")
    # [REQ:EG-05] the live-execution token: §29.5 mints a token ONLY when all 6 training->live preconditions
    # hold (mission created + sim branch + rehearsal done + physics passed + safety passed + human approval),
    # derived from the run's REAL state. A token ATTESTS the released plan is live-executable; a safed or
    # unapproved plan yields none. The require-token half stays on the rc.py LIVE bridge (SIM /run never
    # commands a rover), so this mints the attestation the live path would demand.
    import time as _time

    from stewie.contracts.live_gate import LiveExecutionRefused, LivePreconditions, issue_live_token
    _live_pre = LivePreconditions(
        mission_created=bool(intent.objectives), simulation_branch=True,
        rehearsal_completed=bool(out.get("legs")),
        physics_passed=get_backend("tier2_numpy").conserves_mass(),
        safety_passed=(run["final_state"] == "completed"),
        human_approval=(str(released.state.value) == "released"))
    # [dispatch-audit R3] bind the token to the released revision's IMMUTABLE content_hash (not the mutable
    # revision int), and mint it EXPIRING (issue_live_token stamps issued_at=now + a bounded ttl). So the
    # attestation authorizes exactly the signed plan for a bounded window -- the live-write path (rc_command)
    # requires an unexpired, hash-matching token before a real rover command (the R3 gated-live-writes seam).
    _rev_id = released.released_revision.content_hash if released.released_revision is not None \
        else str(req.revision)
    try:
        _tok = issue_live_token(req.mission_id, _rev_id, _live_pre, now=_time.time())
        live_token = {"issued": True, "mission_id": _tok.mission_id, "revision_id": _tok.revision_id,
                      "signature": _tok.signature, "issued_at": _tok.issued_at, "ttl_s": _tok.ttl_s,
                      "expires_at": _tok.issued_at + _tok.ttl_s}
    except LiveExecutionRefused as _e:
        live_token = {"issued": False, "reason": str(_e)}
    # [REQ:PH-02] attribute the run's numbers to the physics backend that produced them: the closed-loop sim,
    # the energy reconciliation, and the terrain fold all ran on tier2_numpy (the conserved authority) -- so the
    # response names that backend + its calibration model + release-eligibility. No value is left unattributed.
    from stewie.contracts.physics_model_control import physics_attribution
    physics = physics_attribution("tier2_numpy",
                                  quantities=("energy_J", "conserved_terrain_delta_m3", "as_built_acceptance"))
    # [REQ:TM-04] the rehearsal predicted-vs-observed terramechanics report from the REAL legs: energy compared
    # (nominal model vs slip-truth) with a residual, slip observed-only, sinkage honestly marked not-telemetered.
    from stewie.runtime.replay_loop import terramechanics_comparison
    terra_compare = terramechanics_comparison(_legs)
    return JSONResponse(content={"ok": True, "run_id": run_id, **rec, "executability": executability,
                                 "reconciliation": reconciliation, "live_token": live_token,
                                 "physics_attribution": physics, "terramechanics_comparison": terra_compare,
                                 "bound_revision": bound_revision,   # [dispatch-audit R2] the immutable revision executed
                                 "skipped": skipped})


@router.get("/executive/run/{run_id}")
def executive_run_get(run_id: str, identity: str = Depends(require_role("operator"))) -> JSONResponse:
    """#245: retrieve a persisted SIM run by id -- the caller's OWN runs (per-owner sandbox). 404 if absent."""
    rec = OBJ.load_run(run_id, owner=identity)
    if rec is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no run {run_id!r}"})
    return JSONResponse(content={"ok": True, **rec})


@router.get("/executive/revision/{content_hash}")
def executive_revision(content_hash: str,
                       identity: str = Depends(require_role("operator"))) -> JSONResponse:
    """[dispatch-audit R1] Fetch a durably-frozen released revision by its immutable content_hash -- the
    whole signed artifact (SignedRevision incl. intent, the analyze/rehearse evidence, the approval
    transitions). This is the canonical store a later run / RC BINDS to (R2), so the executed plan is
    provably the one that was signed, not a rebuild from mutable orders. Read-gated (operator+): a released
    revision is director-signed but operator-readable (operators execute against it); 404 if never released."""
    from stewie.server import db
    rec = db.read_release_revision(content_hash)
    if rec is None:
        return JSONResponse(status_code=404,
                            content={"ok": False, "error": f"no released revision {content_hash!r}"})
    return JSONResponse(content={"ok": True, "revision": rec})


@router.get("/executive/audit")
def executive_audit(identity: str = Depends(require_role("operator"))) -> JSONResponse:
    """[REQ:EG-07] The executive AUDIT TRAIL: the tamper-evident hash-chained record of director plan releases
    + SIM runs (who/what/when/where/mode/reason/before/after/evidence), with an integrity flag. Read-only,
    operator-visible -- the delivered EG-07 audit contract, now POPULATED by the live executive flow."""
    from dataclasses import asdict

    from stewie.server.audit_log import get_audit_log
    lg = get_audit_log()
    return JSONResponse(content={"ok": True, "verified": lg.verify(), "count": len(lg.records()),
                                 "records": [asdict(r) for r in lg.records()]})


@router.get("/executive/run/{run_id}/stream")
async def executive_run_stream(run_id: str, request: Request, interval_s: float = 0.6,
                               identity: str = Depends(require_role("operator"))):
    """SSE playback: replay a persisted SIM run's FS-04 ExecutionEvent timeline as Server-Sent Events --
    one event per leg + a terminal ``done`` -- paced by ``interval_s`` so the cockpit Execute pane plays
    the run back as it happened. The events are REAL (built from the persisted run via execution_events);
    only the pacing is a display rate. Owner-scoped (the caller's own runs); 404 if absent. One-way push
    only -- never a command path."""
    rec = OBJ.load_run(run_id, owner=identity)
    if rec is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no run {run_id!r}"})
    from lode.sim_execution import execution_events
    events = execution_events(rec)
    interval = max(0.0, min(float(interval_s), 5.0))
    # #58.2: SSE resume. A reconnecting EventSource sends Last-Event-ID = the last leg id it received; replay
    # only the legs AFTER it (each event carries `id: <leg>`), so a transient network blip does not re-play the
    # whole run from leg 0. A non-numeric id ("done" / absent) resumes from the start (harmless -- idempotent).
    _leid = request.headers.get("last-event-id")
    resume_after = int(_leid) if (_leid is not None and _leid.isdigit()) else -1   # None/non-numeric -> from start

    async def _gen():
        for i, ev in enumerate(events):
            if i <= resume_after:
                continue
            yield ("id: " + str(i) + "\n"
                   + "data: " + json.dumps({"kind": ev.kind, "detail": ev.detail, "outcome": ev.outcome,
                                            "t_s": ev.t_s, "vehicle_id": ev.vehicle_id, "leg": i}) + "\n\n")
            if interval:
                await asyncio.sleep(interval)
        yield ("id: " + str(len(events)) + "\n"
               + "data: " + json.dumps({"done": True, "final_state": rec.get("final_state"),
                                        "n_legs_total": rec.get("n_legs_total"),
                                        "safed": rec.get("safed")}) + "\n\n")

    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
