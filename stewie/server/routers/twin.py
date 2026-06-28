"""Twin router (ARCH-3): the digital-twin surface -- the live center-of-gravity / tip-margin readout
(pure stability compute) plus the durable observed-terrain twin's resync (reconstruction update) and
version/audit views. The twin store + lock live in server.state (shared, imported here -- no app
import, no cycle); resync is auth-gated."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from stewie.server import state
from stewie.server.deps import require_auth, require_director
from stewie.specs.config import data_dir
from stewie.twin import terrain_memory as TM

router = APIRouter()


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
    origin_rc: list
    provenance: str


@router.post("/twin/resync")
def twin_resync(req: ResyncRequest, _auth: None = Depends(require_auth)):
    import numpy as _np
    try:
        v = state.twin().apply_patch(_np.array(req.heights_m, dtype=float),
                                     origin_rc=tuple(req.origin_rc), provenance=req.provenance)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
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
