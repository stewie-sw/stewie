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

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from stewie.contracts import MissionIntent
from stewie.contracts.executive import MissionExecutive
from stewie.server.deps import require_director
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
