"""Missions router (ARCH-3): build-mission CRUD over the file-backed object store
(server.objects). Auth comes from server.deps, the audit log from server.services -- no
import of the app module (no cycle).

AG-07: every route is namespace-aware (deps.namespace_for). A trainee/guest is confined to their own
sandbox; an operator+ works on live by default and may target their own sandbox with ?ns=sandbox. The
publish route promotes a sandbox draft into the shared live namespace (operator+)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from stewie.server import objects as OBJ
from stewie.server.deps import namespace_for, require_auth, require_role
from stewie.server.ratelimit import RateLimiter
from stewie.server.services import log_event

router = APIRouter()
_draft_quota = RateLimiter(120, 60.0)   # #241: bound per-identity autosave churn (debounced ~1-2s client-side)


@router.post("/missions/{name}")
def mission_save(name: str, doc: dict, ns: str = "live", identity: str = Depends(require_auth)):
    namespace, _owner = namespace_for(identity, ns)
    try:
        out = OBJ.save_mission(name, doc, owner=identity, namespace=namespace)   # AG-05/07: owner + namespace
        log_event(identity, "mission.save", out["name"])
        return {"ok": True, "namespace": namespace, **out}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@router.get("/missions")
def mission_list(ns: str = "live", identity: str = Depends(require_auth)):
    """S-06: operational reads require auth (a mission queue is not public). AG-07: trainees see their
    own sandbox; operator+ see live (or their own sandbox with ?ns=sandbox)."""
    namespace, owner = namespace_for(identity, ns)
    return {"ok": True, "namespace": namespace,
            "missions": OBJ.list_missions(namespace=namespace, owner=owner)}


@router.get("/missions/{name}")
def mission_load(name: str, ns: str = "live", identity: str = Depends(require_auth)):
    namespace, owner = namespace_for(identity, ns)
    d = OBJ.load_mission(name, namespace=namespace, owner=owner)
    if d is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no mission {name!r}"})
    return {"ok": True, "namespace": namespace, "doc": d}


# ---- #241: per-owner draft autosave ----------------------------------------------------------
# owner = the AUTHENTICATED identity (require_auth), NEVER a client param -> no cross-owner read/write.
# Sandbox-only by construction (OBJ.save_draft has no namespace/publish), so a draft is never
# command-eligible without the operator explicitly saving it as a mission (the publish path).
@router.get("/draft")
def draft_load(identity: str = Depends(require_auth)):
    """The caller's OWN authoring draft (per-owner sandbox); null if none saved yet."""
    return {"ok": True, "doc": OBJ.load_draft(owner=identity)}


@router.put("/draft")
def draft_save(doc: dict, identity: str = Depends(require_auth)):
    """Autosave the caller's draft to their per-owner sandbox. Rate-limited per identity; the global
    body-size cap (server.py) bounds the payload; unknown fields -> 400."""
    if not _draft_quota.allow(identity):
        raise HTTPException(status_code=429, detail="draft autosave quota exceeded; slow down")
    try:
        out = OBJ.save_draft(doc, owner=identity)
        log_event(identity, "draft.save", "sandbox")        # FS-19: operator-action audit
        return {"ok": True, **out}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


# ---- #241: per-owner SOIL OVERLAY (user-authored terramechanics over the static bodies.py baseline) -------
# owner = the AUTHENTICATED identity (never client). NO-FABRICATION: OBJ.save_soil rejects a soil missing
# provenance/confidence (400). The static bodies.py registry is unchanged -- this is a per-owner overlay.
@router.get("/soils")
def soils_list(identity: str = Depends(require_auth)):
    """The caller's per-owner custom soil overlay (provenance-tagged). The built-in body soils stay in
    bodies.json; this lists ONLY the operator's own authored soils."""
    return {"ok": True, "soils": OBJ.list_soils(owner=identity)}


@router.post("/soil/{name}")
def soil_save(name: str, profile: dict, identity: str = Depends(require_auth)):
    """Save an operator-authored soil to their per-owner overlay. NO-FABRICATION: a soil missing
    `provenance` or `confidence` is rejected (400). Rate-limited; body-capped (server.py)."""
    if not _draft_quota.allow(identity):
        raise HTTPException(status_code=429, detail="soil-save quota exceeded; slow down")
    try:
        out = OBJ.save_soil(name, profile, owner=identity)
        log_event(identity, "soil.save", out["name"])
        return out
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@router.delete("/missions/{name}")
def mission_delete(name: str, ns: str = "live", identity: str = Depends(require_auth)):
    """AG-06/07: recoverable soft-delete with ownership escalation within the resolved namespace --
    delete your OWN mission; another operator's (or an unowned) mission requires a director."""
    from stewie.server import auth as AUTH
    namespace, owner = namespace_for(identity, ns)
    art_owner = OBJ.owner_of("missions", name, namespace=namespace, owner=owner)
    if not OBJ.deletion_allowed(art_owner, identity, AUTH.role_of(identity) == "director",
                                namespace=namespace):
        # BP-05: a LIVE mission is operational -> director-only; sandbox stays self-service.
        reason = ("deleting a live (operational) mission requires a director" if namespace == "live"
                  else "deleting another operator's mission requires a director")
        return JSONResponse(status_code=403, content={"ok": False, "error": reason})
    ok = OBJ.delete_mission(name, namespace=namespace, owner=owner)
    log_event(identity, "mission.delete", f"{name} ns={namespace}")   # BP-05: audit names the namespace
    return {"ok": ok, "recoverable": True}


@router.post("/missions/{name}/publish")
def mission_publish(name: str, owner: str | None = None,
                    identity: str = Depends(require_role("operator"))):
    """AG-07: promote a sandbox draft into the shared live namespace (operator+). By default publishes
    YOUR OWN sandbox draft; a director may publish another operator's sandbox draft by naming its owner."""
    from stewie.server import auth as AUTH
    target = owner or identity
    if target != identity and AUTH.role_of(identity) != "director":
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "publishing another operator's sandbox draft requires a director"})
    ok = OBJ.publish("missions", name, owner=target)
    if ok:
        log_event(identity, "mission.publish", name)
    return {"ok": ok}


@router.post("/missions/{name}/restore")
def mission_restore(name: str, ns: str = "live", identity: str = Depends(require_role("operator"))):
    """AG-06/07: restore the most-recent trashed copy of a mission within a namespace (operator+)."""
    namespace, owner = namespace_for(identity, ns)
    ok = OBJ.restore("missions", name, namespace=namespace, owner=owner)
    if ok:
        log_event(identity, "mission.restore", name)        # FS-19: operator-action audit
    return {"ok": ok}


@router.get("/admin/trash/missions")
def mission_trash(_auth: str = Depends(require_role("director"))):
    """AG-06: list the live mission trash (director-only) so a purge can name a file."""
    return {"ok": True, "trash": OBJ.list_trash("missions")}


@router.delete("/admin/trash/missions/{filename}")
def mission_purge(filename: str, _auth: str = Depends(require_role("director"))):
    """AG-06: permanent purge of one trashed mission -- director-only (no hard delete otherwise)."""
    ok = OBJ.purge_trash("missions", filename)
    if ok:
        log_event(_auth, "mission.purge", filename)         # FS-19: irreversible-delete audit
    return {"ok": ok}
