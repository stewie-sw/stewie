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

import secrets

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stewie.contracts import MissionIntent
from stewie.contracts.executive import MissionExecutive
from stewie.server import objects as OBJ
from stewie.server import state
from stewie.server.deps import require_director, require_role
from stewie.server.services import log_event

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
    log_event(_auth, "executive.advance",
              f"{intent.mission_id} rev {intent.revision} -> {res.executive.state.value}")
    return JSONResponse(content={
        "ok": True,
        "label": "sim",                                   # MO-04: planned/rehearsed on the sim authority
        "state": res.executive.state.value,
        "signed_revision": rel.model_dump(mode="json") if rel is not None else None,
        "evidence": res.evidence,
        "transitions": res.transitions,
    })


class ReleasePlanRequest(BaseModel):
    """The cockpit's current build-order queue, for the live "release the current plan" surface."""
    orders: list[dict] = Field(max_length=1000)
    body: str = "moon"
    mission_id: str = "cockpit-release"
    revision: int = Field(default=0, ge=0)


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
    log_event(_auth, "executive.release_plan",
              f"{req.mission_id}: {len(intent.objectives)} objectives -> {res.executive.state.value}")
    return JSONResponse(content={
        "ok": True,
        "label": "sim",
        "state": res.executive.state.value,
        "signed_revision": rel.model_dump(mode="json") if rel is not None else None,
        "evidence": res.evidence,
        "transitions": res.transitions,
        "released_objectives": len(intent.objectives),
        "skipped": skipped,
    })


class RunRequest(BaseModel):
    """#245: run a released build plan as a SIM execution. Same queue shape as release-plan + the site."""
    orders: list[dict] = Field(max_length=1000)
    body: str = "moon"
    site: str = Field("haworth", max_length=40)
    mission_id: str = "cockpit-run"
    revision: int = Field(default=0, ge=0)


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
    from lode.mission_intent_compiler import intent_from_orders
    from lode.sim_execution import run_sim_execution
    try:
        intent, skipped = intent_from_orders(
            list(req.orders), mission_id=req.mission_id, approver=identity, body=req.body, revision=req.revision)
        if not intent.objectives:
            return JSONResponse(status_code=400, content={
                "ok": False, "skipped": skipped, "error": "no build orders to run (cut/fill/sinter)"})
        released = LC.run_lifecycle(MissionExecutive.start(intent)).executive
        mission = MP.mission_from_dict({"name": req.mission_id, "body": req.body,
                                        "orders": list(req.orders), "charger": [0.0, 0.0]})
        dem, origin = state.moon_dem(req.site) if req.body == "moon" else (None, (0.0, 0.0))
        out = AUT.run_closed_loop(mission, dem=dem, dem_origin=origin)
        run = run_sim_execution(released, out.get("legs", []))
    except (ValueError, KeyError, TypeError) as e:    # #300: malformed order field -> 400, not an uncaught 500
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e), "skipped": []})
    run_id = secrets.token_hex(6)
    rec = {"label": run["label"], "final_state": run["final_state"], "transitions": run["transitions"],
           "n_legs_total": run["n_legs_total"], "safed": run["safed"], "nonnominal_legs": run["nonnominal_legs"],
           "executed_legs": run["executed_legs"], "mission_id": req.mission_id, "site": req.site}
    OBJ.save_run(run_id, rec, owner=identity)                  # #245: persist the run for later retrieval
    log_event(identity, "executive.run",
              f"{run_id} {req.mission_id}: {run['final_state']} ({run['n_legs_total']} legs)")
    return JSONResponse(content={"ok": True, "run_id": run_id, **rec, "skipped": skipped})


@router.get("/executive/run/{run_id}")
def executive_run_get(run_id: str, identity: str = Depends(require_role("operator"))) -> JSONResponse:
    """#245: retrieve a persisted SIM run by id -- the caller's OWN runs (per-owner sandbox). 404 if absent."""
    rec = OBJ.load_run(run_id, owner=identity)
    if rec is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no run {run_id!r}"})
    return JSONResponse(content={"ok": True, **rec})
