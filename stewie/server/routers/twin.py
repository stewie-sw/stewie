"""Twin router (ARCH-3): the digital-twin surface -- the live center-of-gravity / tip-margin readout
(pure stability compute) plus the durable observed-terrain twin's resync (reconstruction update) and
version/audit views. The twin store + lock live in server.state (shared, imported here -- no app
import, no cycle); resync is auth-gated."""
from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from stewie.server import state
from stewie.server.deps import require_auth, require_director, require_role
from stewie.server.services import log_event
from stewie.specs.config import data_dir
from stewie.twin import terrain_memory as TM

router = APIRouter()

# #278: serialize the load->apply->save read-modify-write of a site's durable Terrain Memory. Two
# concurrent POST /twin/terrain/{site} handlers (sync defs -> FastAPI threadpool) would otherwise
# last-writer-win and silently drop a mission's as-built delta. Per-site lock so different sites proceed
# in parallel; a meta-lock guards the registry dict itself.
_TERRAIN_LOCKS: dict = {}
_TERRAIN_LOCKS_GUARD = threading.Lock()


def _terrain_lock(site: str) -> threading.Lock:
    # #282: key on the SANITIZED site (the same normalization save_site/load_site use for the .npz path), so
    # two requests whose site spellings collapse to the same file (e.g. "haworth" vs "haworth ") take the
    # SAME lock -- keying on the raw param re-opened the #278 lost-mission RMW race for such spellings.
    key = TM.safe_site(site)
    with _TERRAIN_LOCKS_GUARD:
        return _TERRAIN_LOCKS.setdefault(key, threading.Lock())


@router.get("/twin/cg")
def twin_cg(front_deg: float = 0.0, back_deg: float = 0.0, front_kg: float = 0.0,
            back_kg: float = 0.0, pitch_deg: float = 0.0, roll_deg: float = 0.0):
    """#25: the live center-of-gravity + tip margin -- posture (arm angles) + drum LOADS through
    ArmState.cg_offset_m (the loads enter AT the drums) and the SSA stability model."""
    from stewie.physics.stability import stability as STAB
    from stewie.specs.arm_state import ArmState
    # F2 (data-book audit): THREE conflicting geometry triplets existed. The registry is the ONE
    # source (per-vehicle, Aaron's directive): geometry_of("ipex") = gauge 0.3645 [WHEELTEST Eq.1
    # 0.5207 test-platform track x the 0.7 IPEx scale, per ipex_specs' own comment] / wheelbase
    # 0.30 / CG 0.21. This CORRECTS the #59 change, which over-read 0.5207 as IPEx's own track.
    from stewie.specs.vehicles import geometry_of
    arm = ArmState()
    arm.front_deg = max(-110.0, min(110.0, float(front_deg)))   # instantaneous pose (no rate sim here)
    arm.back_deg = max(-110.0, min(110.0, float(back_deg)))
    dx, dz = arm.cg_offset_m(front_drum_kg=max(0.0, front_kg), back_drum_kg=max(0.0, back_kg))
    geo = geometry_of("ipex")
    st = STAB(float(pitch_deg), float(roll_deg), gauge_m=geo["gauge_m"],
              wheelbase_m=geo["wheelbase_m"], cg_height_m=geo["cg_height_m"] + dz, cg_dx_m=dx)  # VT4-01: dx now bites
    return {"ok": True, "cg_dx_m": round(dx, 4), "cg_dz_m": round(dz, 4),
            "cg_height_m": round(geo["cg_height_m"] + dz, 4), **{k: (round(v, 3) if isinstance(v, float) else v)
                                                          for k, v in st.items()}}


class ResyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heights_m: list
    origin_rc: tuple[int, int]   # #299: a (row, col) PAIR -- validate at the contour so a 1-elem/non-int
    #                              origin is a 400 (was an uncaught IndexError -> 500 inside apply_patch)
    provenance: str


@router.post("/twin/resync")
def twin_resync(req: ResyncRequest, identity: str = Depends(require_role("operator"))):
    # SECURITY (council #234 dim-3): resync MUTATES the shared authoritative twin (apply_patch on the live
    # observed terrain) -- it must be operator+, not any authenticated client. Previously require_auth let a
    # guest/trainee (confined elsewhere to read-only / own sandbox) overwrite the world model everyone plans
    # against. Now gated like its sibling twin_terrain_record + audit-logged.
    import numpy as _np
    try:
        v = state.twin().apply_patch(_np.array(req.heights_m, dtype=float),
                                     origin_rc=tuple(req.origin_rc), provenance=req.provenance)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event(identity, "twin.resync", str(req.provenance))
    return {"ok": True, "twin_version": v}


@router.get("/twin/version")
def twin_version(_auth: str = Depends(require_auth)):
    """DT-02 (least privilege): ANY authenticated client gets the minimal version TOKEN -- the current
    observed-twin version + chain-integrity flag -- but NOT the event history (that is an audit log,
    director-only via /twin/history). Previously this leaked the full history with no auth at all."""
    t = state.twin()
    return {"twin_version": t.version, "chain_valid": t.verify_chain()}


@router.get("/twin/history")
def twin_history(_d: str = Depends(require_director)):
    """DT-02: the full observed-twin audit history (resync events + provenance) -- director-only."""
    t = state.twin()
    return {"twin_version": t.version, "chain_valid": t.verify_chain(), "events": t.history()}


@router.get("/twin/terrain/{site}")
def twin_terrain(site: str, _auth: str = Depends(require_auth)):
    """W3 (Terrain Memory): a site's authoritative world-model summary -- how much the terrain has changed
    across every recorded mission (version, cells changed, net volume moved, deepest cut / highest build,
    the mission log + chain-integrity flag). Never 500: an unrecorded site returns an empty (version 0)
    summary so the cockpit shows an honest "no terrain changes recorded yet" rather than an error."""
    try:
        mem = TM.load_site(data_dir(), site)
    except Exception:
        mem = None
    if mem is None:
        return {"ok": True, "site": site, "recorded": False, "version": 0, "cells_changed": 0,
                "net_volume_m3": 0.0, "max_cut_m": 0.0, "max_fill_m": 0.0, "missions": []}
    s = mem.summary()
    s.update({"ok": True, "recorded": True, "chain_valid": mem.verify_chain()})
    return s


class TerrainRecordReq(BaseModel):
    """W3: record a (completed) mission's terrain change into a site's Terrain Memory. ``mission`` is the
    /plan order shape; the optional site-grid fields define the persistent site extent (default: the
    mission's own footprint, for a single-mission site)."""
    model_config = ConfigDict(extra="forbid")
    mission: dict
    rows: int | None = None
    cols: int | None = None
    cell_m: float | None = None
    origin: tuple[float, float] | None = None


@router.post("/twin/terrain/{site}")
def twin_terrain_record(site: str, req: TerrainRecordReq, identity: str = Depends(require_role("operator"))):
    """W3 (Terrain Memory): fold a completed mission's conserved terrain change into a site's authoritative
    world model and persist it -- the terrain then REMEMBERS what was built, and a future plan can target
    the remembered surface (imprint_on_dem). The delta is computed on the conserved authority via
    lode.mission_terrain_delta (flat-mantle baseline; a real-DEM baseline is the next wire). Operator+ (it
    writes durable world state). On a fresh site the grid defaults to the mission's footprint frame; on an
    existing site the mission is placed at its global offset (clipped to the site bounds, surfaced)."""
    from lode import mission_planner as MP
    from lode.planner_acceptance import mission_terrain_delta
    try:
        mission = MP.mission_from_dict({"name": req.mission.get("name", site), **req.mission})
        d = mission_terrain_delta(mission)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"bad mission: {e}")
    with _terrain_lock(site):    # #278: the load->apply->save RMW is atomic per site (no lost-mission race)
        mem = TM.load_site(data_dir(), site)
        if mem is None:
            mem = TM.TerrainMemory(site=site, rows=int(req.rows or d["rows"]), cols=int(req.cols or d["cols"]),
                                   cell_m=float(req.cell_m or d["cell_m"]),
                                   origin=req.origin if req.origin else (float(d["x0"]), float(d["y0"])))
        try:
            res = mem.apply_subgrid(d["delta"], sub_origin=(d["x0"], d["y0"]), cell_m=d["cell_m"],
                                    mission=str(mission.name), mass_moved_kg=d["mass_moved_kg"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"cannot place mission on site grid: {e}")
        TM.save_site(data_dir(), mem)
        log_event(identity, "twin.terrain.record", f"{site}:{mission.name}")
        out = mem.summary()
        out.update({"ok": True, "recorded": True, "chain_valid": mem.verify_chain(), **res})
    return out
