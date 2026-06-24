"""Site-plan router (structure-first base planning): validate-and-advise analysis over a SET of placed
structures. Read-only planning analysis -- it computes the base-wide mass economy, source<->sink routing,
inter-structure clearances, build order, and advisories WITHOUT changing any state or moving anything
(the operator keeps placement authority). So it needs auth (operational) but not a director gate.

The analysis is leap.siteplan.analyze_siteplan; this router is the thin HTTP boundary + input limits.
Auth from server.deps, audit from server.services -- no import of the app module (no cycle).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from leap.siteplan import PlacedStructure, analyze_siteplan
from stewie.server.deps import require_auth
from stewie.server.services import log_event

router = APIRouter()


class _Placement(BaseModel):
    name: str
    x: float
    y: float
    params: dict = Field(default_factory=dict)


class SitePlanRequest(BaseModel):
    """A base layout the operator authored: the placed structures + the minimum inter-structure gap to
    flag. Bounded so a malformed/oversized body cannot exhaust the server."""
    placements: list[_Placement] = Field(min_length=1, max_length=500)
    min_gap_m: float = Field(default=2.0, ge=0.0)


@router.post("/siteplan/analyze")
def siteplan_analyze(req: SitePlanRequest, _auth: str = Depends(require_auth)):
    """Validate-and-advise: return the base-wide mass economy, routing, clearances, build order, and
    advisories for the placed structures. 400 on an unknown structure name (honest failure)."""
    try:
        ps = [PlacedStructure(name=p.name, x=p.x, y=p.y, params=dict(p.params)) for p in req.placements]
        rpt = analyze_siteplan(ps, min_gap_m=req.min_gap_m)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(_auth, "siteplan.analyze", f"{len(ps)} structures")
    return {"ok": True, **rpt.to_dict()}
