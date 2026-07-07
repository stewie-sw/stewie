"""Edit-session router (GW-08 / ED-01): the mission-feature EDIT SESSION surface -- create / modify /
delete / undo the keep-out set through backend routes, with a versioned audit, replacing the former
client-side-only ``planAuthor.js`` keepout array. The session store (``server.edit_session``) is the source
of truth; ``/plan`` reads a session's current set by its opaque id + the order-frame anchor and folds it
into the planner keep-outs, so a keep-out authored here routes the mission around it exactly as a
client-supplied ``payload.keepouts`` did (``planner_routing._apply_keepouts``).

AUTH POSTURE: these routes are KEYLESS and capability-gated by the UNGUESSABLE opaque session id (a client
that holds the id owns the session; there is no enumeration). This matches the reality that keep-out
authoring was 100% client-side unauthenticated before GW-08, and it is what lets the public IDE reach the
routes through the artemis ``/api/`` proxy (which injects the director-equivalent key only for specific
exact-match routes like ``/api/plan`` -- a NEW route falls through the generic block with NO credential, so
an auth-gated edit route would 401 there). The store holds EPHEMERAL mission-authoring state only (never
the conserved authority, the observed twin, or a rover command) and is bounded (per-session + global caps),
so this adds no privilege over the prior client-only authoring. Operator-gating would require an nginx
exact-match key-injection block (an ops/deploy change, out of this router's scope)."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from stewie.server import edit_session as ES
from stewie.server.services import log_event

log = logging.getLogger("stewie.server")
router = APIRouter()


class KeepoutIn(BaseModel):
    """A keep-out geometry in the map frame (IAU_2015:30135, metres): a ``circle`` {cx,cy,r} or a
    ``polygon`` {ring:[[x,y],...]}. Validated in the store (a bad shape is a 400)."""
    model_config = ConfigDict(extra="forbid")
    kind: str
    cx: float | None = None
    cy: float | None = None
    r: float | None = None
    ring: list | None = None


class MarkerIn(BaseModel):
    """A place-object marker in the map frame (IAU_2015:30135, metres): a POINT {x,y} plus an object type
    (beacon/cache/instrument/sample/antenna) and an optional label. Validated in the store (bad type -> 400)."""
    model_config = ConfigDict(extra="forbid")
    x: float
    y: float
    otype: str
    label: str | None = None


def _not_found(sid: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"ok": False, "error": f"no edit session {sid!r}"})


@router.post("/edit/session")
def create_session():
    """Mint a fresh mission-feature edit session; returns its opaque id + the (empty) initial state."""
    sess = ES.new_session()
    log_event("ide", "edit.session.create", sess.id)
    return {"ok": True, **sess.state()}


@router.get("/edit/session/{sid}")
def get_session(sid: str):
    """The session's current keep-out set + version + audit tail (the source of truth the map renders)."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    return {"ok": True, **sess.state()}


@router.get("/edit/session/{sid}/audit")
def get_audit(sid: str):
    """The full versioned audit log for the session (every create/modify/delete/undo, before/after)."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    return {"ok": True, "session": sess.id, "version": sess.version, "audit": sess.audit()}


@router.post("/edit/session/{sid}/keepout")
def create_keepout(sid: str, req: KeepoutIn):
    """Create a keep-out in the session (writes through the backend, not the map layer). Returns the new
    feature + the authoritative post-edit state (version + full feature set the client re-renders from)."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    try:
        feature = sess.create(req.kind, req.model_dump())
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event("ide", "edit.keepout.create", f"{sess.id}:{feature['fid']}")
    return {"ok": True, "feature": feature, **sess.state()}


@router.patch("/edit/session/{sid}/keepout/{fid}")
def modify_keepout(sid: str, fid: str, req: KeepoutIn):
    """Modify a keep-out's geometry (the audit records before + after). Returns the new feature + state."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    try:
        feature = sess.modify(fid, req.kind, req.model_dump())
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no keep-out {fid!r}"})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event("ide", "edit.keepout.modify", f"{sess.id}:{fid}")
    return {"ok": True, "feature": feature, **sess.state()}


@router.delete("/edit/session/{sid}/keepout/{fid}")
def delete_keepout(sid: str, fid: str):
    """Delete a keep-out (the audit records its before, so an undo can restore it). Returns the post state."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    try:
        sess.delete(fid)
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no keep-out {fid!r}"})
    log_event("ide", "edit.keepout.delete", f"{sess.id}:{fid}")
    return {"ok": True, **sess.state()}


@router.post("/edit/session/{sid}/marker")
def create_marker(sid: str, req: MarkerIn):
    """Create a place-object marker (a mission object -- beacon/cache/instrument/sample/antenna) in the
    session. Persists through the SAME versioned-audit store the keep-outs use, but as a POINT feature kept
    SEPARATE from the keep-out set (a marker annotates the map; it never routes the planner around it).
    Returns the new marker + the authoritative post-edit state (version + features + markers)."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    try:
        marker = sess.create_marker(req.model_dump())
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event("ide", "edit.marker.create", f"{sess.id}:{marker['fid']}")
    return {"ok": True, "marker": marker, **sess.state()}


@router.delete("/edit/session/{sid}/marker/{fid}")
def delete_marker(sid: str, fid: str):
    """Delete a place-object marker (the audit records its before, so an undo can restore it). Returns state."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    try:
        sess.delete_marker(fid)
    except KeyError:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no marker {fid!r}"})
    log_event("ide", "edit.marker.delete", f"{sess.id}:{fid}")
    return {"ok": True, **sess.state()}


@router.post("/edit/session/{sid}/undo")
def undo_edit(sid: str):
    """Undo the last edit (create/modify/delete) -- the DT-03 compensating inverse from the audit's
    before/after. History is never deleted (an ``undo`` record is appended). Returns the post state."""
    sess = ES.get_session(sid)
    if sess is None:
        return _not_found(sid)
    try:
        undone = sess.undo()
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event("ide", "edit.undo", f"{sess.id}:v{undone['undone_version']}")
    return {"ok": True, "undone": undone, **sess.state()}
