"""Missions router (ARCH-3): build-mission CRUD over the file-backed object store
(server.objects). Auth comes from server.deps, the audit log from server.services -- no
import of the app module (no cycle).

AG-07: every route is namespace-aware (deps.namespace_for). A trainee/guest is confined to their own
sandbox; an operator+ works on live by default and may target their own sandbox with ?ns=sandbox. The
publish route promotes a sandbox draft into the shared live namespace (operator+)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from stewie.server import objects as OBJ
from stewie.server.deps import namespace_for, require_auth, require_role
from stewie.server.services import log_event

router = APIRouter()


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


@router.delete("/missions/{name}")
def mission_delete(name: str, ns: str = "live", identity: str = Depends(require_auth)):
    """AG-06/07: recoverable soft-delete with ownership escalation within the resolved namespace --
    delete your OWN mission; another operator's (or an unowned) mission requires a director."""
    from stewie.server import auth as AUTH
    namespace, owner = namespace_for(identity, ns)
    art_owner = OBJ.owner_of("missions", name, namespace=namespace, owner=owner)
    if not OBJ.deletion_allowed(art_owner, identity, AUTH.role_of(identity) == "director"):
        return JSONResponse(status_code=403, content={
            "ok": False, "error": "deleting another operator's mission requires a director"})
    ok = OBJ.delete_mission(name, namespace=namespace, owner=owner)
    log_event(identity, "mission.delete", name)
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
    return {"ok": OBJ.restore("missions", name, namespace=namespace, owner=owner)}


@router.get("/admin/trash/missions")
def mission_trash(_auth: str = Depends(require_role("director"))):
    """AG-06: list the live mission trash (director-only) so a purge can name a file."""
    return {"ok": True, "trash": OBJ.list_trash("missions")}


@router.delete("/admin/trash/missions/{filename}")
def mission_purge(filename: str, _auth: str = Depends(require_role("director"))):
    """AG-06: permanent purge of one trashed mission -- director-only (no hard delete otherwise)."""
    return {"ok": OBJ.purge_trash("missions", filename)}
