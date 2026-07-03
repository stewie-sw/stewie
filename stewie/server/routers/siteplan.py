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
    from leap.siteplan import PlacedStructure, analyze_siteplan   # [REQ:AP-01] lazy: app-layer router, not a module-level leap edge
    try:
        ps = [PlacedStructure(name=p.name, x=p.x, y=p.y, params=dict(p.params)) for p in req.placements]
        rpt = analyze_siteplan(ps, min_gap_m=req.min_gap_m)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(_auth, "siteplan.analyze", f"{len(ps)} structures")
    return {"ok": True, **rpt.to_dict()}


class VolumeRequest(BaseModel):
    """A mission (build orders) to estimate moved-regolith volume evidence for, with the design-time
    density envelope + optional drum cross-check. Bounded so a malformed body cannot exhaust the server."""
    orders: list[dict] = Field(min_length=1, max_length=200)
    body: str = "moon"
    density_kg_m3: float = Field(gt=0.0)
    density_frac: float = Field(default=0.0, ge=0.0, le=1.0)
    drum_inferred_kg: float | None = None


@router.post("/siteplan/volume")
def siteplan_volume(req: VolumeRequest, _auth: str = Depends(require_auth)):
    """[REQ:FR-13] Emit the RegolithVolumeEstimate for a mission: a conserved, uncertainty-carrying
    moved-regolith estimate cross-checked against the conserved-authority mass + (optional) drum sensor,
    linked to a world transaction. Read-only design-time evidence for the cockpit/report volume surface."""
    import hashlib

    import lode.mission_planner as MP

    from leap.volume_evidence import siteplan_volume_evidence
    try:
        mission = MP.mission_from_dict({"name": "volume", "body": req.body, "charger": [0, 0],
                                        "orders": req.orders})
        txn = "plan:" + hashlib.sha256(repr(req.orders).encode()).hexdigest()[:12]   # deterministic plan link
        ev = siteplan_volume_evidence(mission, work_order_id="siteplan", transaction_id=txn,
                                      density_kg_m3=req.density_kg_m3, density_frac=req.density_frac,
                                      drum_inferred_kg=req.drum_inferred_kg)
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(_auth, "siteplan.volume", f"{len(req.orders)} orders -> {ev.acceptance}")
    return {"ok": True, "volume": ev.model_dump()}
