"""[GW-08 / ED-01] Mission-feature EDIT SESSION -- the server-owned, versioned source of truth for the
keep-out set an operator authors in the IDE.

Before GW-08 the no-go / keep-out regions were CLIENT-SIDE only: ``planAuthor.js`` drew them into an
OpenLayers layer and serialized them into the ``/plan`` POST as ``payload.keepouts`` at plan time. There
was no backend edit-session, no versioned audit, no undo -- the map layer WAS the authority. This module
moves that authority server-side: every create / modify / delete of a keep-out goes through a backend
route into a session store that bumps a MONOTONIC version and appends a hash-free but before/after AUDIT
record for each edit, and an UNDO route reverts the last edit by applying its recorded inverse (the DT-03
"compensating" idea -- the audit's before/after IS the compensating data -- applied locally to an
in-memory session rather than to a durable world-log commit).

Doctrine (mirrors ``stewie.twin.versioned``): undo never DELETES history -- it appends an ``undo`` audit
record and reverts the current feature set; a subsequent undo walks to the next-prior live edit (linear
LIFO, no redo). The session's ``current_features`` set is the source of truth; ``/plan`` reads it (by the
opaque session id + the order-frame anchor) and folds it into ``payload.keepouts``, so the planner routes
around an edit-session keep-out through the EXACT same ``planner_routing._apply_keepouts`` path as before
(behavior preserved -- only the SOURCE moved from the client array to this store).

Geometry is stored in the STABLE map CRS (IAU_2015:30135, metres) -- the frame the client draws in -- not
the per-plan order frame (whose anchor is the order centroid and therefore moves as orders change). The
map->order-frame projection (a pure y-flipped translation by the anchor) happens at plan time in
``to_planner_keepouts``, matching ``planAuthor.js`` ``_keepoutsForFrame`` exactly.

SECURITY: sessions are capability-gated by an UNGUESSABLE opaque id (``secrets.token_hex``) -- a client
that holds the id owns the session; there is no enumeration (same pattern as the S-06 opaque report
stems). The store is bounded (per-session feature cap + a global session cap with oldest-first eviction)
so an unauthenticated authoring client cannot grow it without bound. It holds EPHEMERAL mission-authoring
state only -- never the conserved authority, the observed twin, or a rover command -- exactly the class of
state the client already mutated unauthenticated before GW-08.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any

# The planner already caps polygon vertices at this bound (lode.planner_model._MAX_KEEPOUT_VERTS) so a
# keep-out cannot drive an O(cells x verts) routing DoS; the edit session refuses the same at authoring
# time. Kept as a local constant (not imported) so the lightweight server store carries no lode import.
MAX_KEEPOUT_VERTS = 256
MAX_FEATURES_PER_SESSION = 200       # matches the /plan STEWIE_MAX_KEEPOUTS default input cap
MAX_SESSIONS = 512                   # global bound; oldest session evicted past this
MAX_MARKERS_PER_SESSION = 200        # place-object markers are point features; bound them like keep-outs

# Place-object marker types: a small, bounded vocabulary of mission objects an operator drops on the map
# (a nav/comm beacon, a spoil/sample cache, a science instrument, a sample tube, a relay antenna). Kept a
# frozenset so an unknown type is a clean 400 at the boundary (no arbitrary attacker-chosen strings stored).
ALLOWED_MARKER_TYPES = frozenset({"beacon", "cache", "instrument", "sample", "antenna"})
MAX_MARKER_LABEL_LEN = 80


def _finite(v: Any, what: str) -> float:
    """Coerce to a finite float or raise ValueError (no NaN/inf into the stored geometry or the planner)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number (got {v!r})")
    if f != f or f in (float("inf"), float("-inf")):
        raise ValueError(f"{what} must be finite (got {v!r})")
    return f


def _normalize_geometry(kind: str, body: dict) -> dict:
    """Validate + normalize a keep-out geometry in the map frame (30135 metres) into the stored schema:
      circle  -> {"kind": "circle", "cx", "cy", "r"}
      polygon -> {"kind": "polygon", "ring": [[x, y], ...]}   (open ring, 3..MAX_KEEPOUT_VERTS verts)
    Raises ValueError on a bad shape (surfaced by the route as a 400)."""
    k = str(kind or "").lower()
    if k == "circle":
        cx = _finite(body.get("cx"), "circle cx")
        cy = _finite(body.get("cy"), "circle cy")
        r = _finite(body.get("r"), "circle r")
        if r <= 0:
            raise ValueError(f"circle r must be > 0 (got {r})")
        return {"kind": "circle", "cx": cx, "cy": cy, "r": r}
    if k == "polygon":
        ring = body.get("ring")
        if not isinstance(ring, (list, tuple)):
            raise ValueError("polygon needs a 'ring' list of [x, y] vertices")
        if not (3 <= len(ring) <= MAX_KEEPOUT_VERTS):
            raise ValueError(f"polygon needs 3..{MAX_KEEPOUT_VERTS} vertices (got {len(ring)})")
        pts = []
        for i, p in enumerate(ring):
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                raise ValueError(f"polygon vertex {i} must be [x, y]")
            pts.append([_finite(p[0], f"polygon vertex {i} x"), _finite(p[1], f"polygon vertex {i} y")])
        return {"kind": "polygon", "ring": pts}
    raise ValueError(f"unknown keep-out kind {kind!r} (want 'circle' or 'polygon')")


def _normalize_marker(body: dict) -> dict:
    """Validate + normalize a place-object marker in the map frame (30135 metres) into the stored schema:
    ``{"kind": "marker", "x", "y", "otype", "label"}``. A marker is a POINT feature (an operator-dropped
    mission object). The type must be in ALLOWED_MARKER_TYPES; a blank label defaults to the type. Raises
    ValueError on a bad shape/type (surfaced by the route as a 400)."""
    x = _finite(body.get("x"), "marker x")
    y = _finite(body.get("y"), "marker y")
    otype = str(body.get("otype") or "").strip().lower()
    if otype not in ALLOWED_MARKER_TYPES:
        raise ValueError(f"unknown object type {otype!r} (want one of {sorted(ALLOWED_MARKER_TYPES)})")
    label = str(body.get("label") or "").strip()[:MAX_MARKER_LABEL_LEN] or otype.capitalize()
    return {"kind": "marker", "x": x, "y": y, "otype": otype, "label": label}


class EditSession:
    """One operator's mission-feature edit session: an ordered keep-out set + a monotonic version + an
    append-only before/after audit log + a linear undo. Thread-safe (one re-entrant lock guards the whole
    read-modify-append of every mutation, mirroring TwinStore's RC-01 lock)."""

    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.created_at = time.time()
        self.version = 0                         # monotonic; bumped once per edit (incl. undo)
        self._features: dict[str, dict] = {}     # fid -> {"fid", "kind", ...geometry (map frame)} -- keep-outs
        self._markers: dict[str, dict] = {}      # fid -> {"fid", "kind":"marker", "x", "y", "otype", "label"}
        self._audit: list[dict] = []             # {version, op, fid, kind, before, after, ts}
        self._fid_seq = 0
        self._marker_seq = 0
        self._lock = threading.RLock()

    # ---- internal --------------------------------------------------------------------------------
    def _next_fid(self) -> str:
        self._fid_seq += 1
        return f"ko{self._fid_seq}"

    def _next_marker_fid(self) -> str:
        self._marker_seq += 1
        return f"mk{self._marker_seq}"

    def _record(self, op: str, fid: str, kind: str, before: dict | None, after: dict | None) -> int:
        """Bump the version and append one audit record. Caller holds the lock."""
        self.version += 1
        self._audit.append({
            "version": self.version, "op": op, "fid": fid, "kind": kind,
            "before": before, "after": after, "ts": time.time(),
        })
        return self.version

    # ---- edits (each writes through here; the routes are thin wrappers) ---------------------------
    def create(self, kind: str, body: dict) -> dict:
        """Create a keep-out from a map-frame geometry. Returns the stored feature (with its new fid)."""
        geom = _normalize_geometry(kind, body)
        with self._lock:
            if len(self._features) >= MAX_FEATURES_PER_SESSION:
                raise ValueError(f"session is full ({MAX_FEATURES_PER_SESSION} keep-outs); delete some first")
            fid = self._next_fid()
            feature = {"fid": fid, **geom}
            self._features[fid] = feature
            self._record("create", fid, geom["kind"], before=None, after=dict(feature))
            return dict(feature)

    def modify(self, fid: str, kind: str, body: dict) -> dict:
        """Replace an existing keep-out's geometry (audit records the before + after). Returns the new feature."""
        geom = _normalize_geometry(kind, body)
        with self._lock:
            old = self._features.get(fid)
            if old is None:
                raise KeyError(fid)
            new = {"fid": fid, **geom}
            self._features[fid] = new
            self._record("modify", fid, geom["kind"], before=dict(old), after=dict(new))
            return dict(new)

    def delete(self, fid: str) -> dict:
        """Delete a keep-out (audit records its before). Returns the deleted feature."""
        with self._lock:
            old = self._features.pop(fid, None)
            if old is None:
                raise KeyError(fid)
            self._record("delete", fid, old["kind"], before=dict(old), after=None)
            return dict(old)

    # ---- place-object markers (POINT features; kept SEPARATE from the keep-out set so a marker never
    #      becomes a planner keep-out) -- create/delete write through the SAME versioned audit + undo ----
    def create_marker(self, body: dict) -> dict:
        """Create a place-object marker from a map-frame point. Returns the stored feature (with its fid)."""
        geom = _normalize_marker(body)
        with self._lock:
            if len(self._markers) >= MAX_MARKERS_PER_SESSION:
                raise ValueError(f"session is full ({MAX_MARKERS_PER_SESSION} markers); delete some first")
            fid = self._next_marker_fid()
            feature = {"fid": fid, **geom}
            self._markers[fid] = feature
            self._record("marker.create", fid, "marker", before=None, after=dict(feature))
            return dict(feature)

    def delete_marker(self, fid: str) -> dict:
        """Delete a marker (audit records its before, so an undo can restore it). Returns the deleted feature."""
        with self._lock:
            old = self._markers.pop(fid, None)
            if old is None:
                raise KeyError(fid)
            self._record("marker.delete", fid, "marker", before=dict(old), after=None)
            return dict(old)

    def undo(self) -> dict:
        """Revert the last live edit (create/modify/delete) not already undone -- the DT-03 compensating
        idea applied locally: apply the inverse of the recorded before/after, append an ``undo`` audit
        record, and bump the version. History is never deleted. Raises ValueError if nothing to undo."""
        _UNDOABLE = ("create", "modify", "delete", "marker.create", "marker.delete")
        with self._lock:
            undone_targets = {rec["target"] for rec in self._audit if rec["op"] == "undo"}
            live = [rec for rec in self._audit
                    if rec["op"] in _UNDOABLE and rec["version"] not in undone_targets]
            if not live:
                raise ValueError("nothing to undo")
            target = live[-1]
            fid = target["fid"]
            op = target["op"]
            if op == "create":                       # compensate a keep-out create -> remove the feature
                self._features.pop(fid, None)
            elif op in ("delete", "modify"):         # restore the prior keep-out geometry / feature
                self._features[fid] = dict(target["before"])
            elif op == "marker.create":              # compensate a marker create -> remove the marker
                self._markers.pop(fid, None)
            elif op == "marker.delete":              # compensate a marker delete -> restore the marker
                self._markers[fid] = dict(target["before"])
            self.version += 1
            self._audit.append({
                "version": self.version, "op": "undo", "target": target["version"],
                "reverted_op": op, "fid": fid, "kind": target["kind"],
                "before": target["after"], "after": target["before"], "ts": time.time(),
            })
            return {"undone_version": target["version"], "reverted_op": op, "fid": fid}

    # ---- reads -----------------------------------------------------------------------------------
    def current_features(self) -> list[dict]:
        """The live keep-out set (insertion order), each {fid, kind, ...map-frame geometry}. Markers are a
        SEPARATE class (current_markers) and are deliberately excluded here, so a marker never leaks into the
        planner keep-outs the planner reads via to_planner_keepouts."""
        with self._lock:
            return [dict(f) for f in self._features.values()]

    def current_markers(self) -> list[dict]:
        """The live place-object marker set (insertion order), each {fid, kind:'marker', x, y, otype, label}."""
        with self._lock:
            return [dict(m) for m in self._markers.values()]

    def audit(self, limit: int | None = None) -> list[dict]:
        """The versioned audit log (oldest-first). ``limit`` returns only the most recent ``limit`` records."""
        with self._lock:
            recs = [dict(r) for r in self._audit]
        if limit is not None and limit >= 0:
            return recs[-limit:]
        return recs

    def to_planner_keepouts(self, anchor_xy: tuple[float, float]) -> list[dict]:
        """Project the live keep-out set from the map frame (30135 metres) into the ORDER FRAME the planner
        consumes -- the SAME y-flipped translation ``planAuthor.js`` ``_keepoutsForFrame`` applies:
        ``ox = X - anchorX``, ``oy = anchorY - Y``. Emits the exact ``planner_routing`` schema
        (``{x, y, r}`` circle / ``{points: [[x, y], ...]}`` polygon), so a session keep-out routes through
        ``_apply_keepouts`` identically to a client-supplied one (behavior preserved)."""
        ax, ay = float(anchor_xy[0]), float(anchor_xy[1])
        out: list[dict] = []
        for f in self.current_features():
            if f["kind"] == "circle":
                out.append({"x": round(f["cx"] - ax, 1), "y": round(ay - f["cy"], 1), "r": round(f["r"], 1)})
            else:
                out.append({"points": [[round(px - ax, 1), round(ay - py, 1)] for px, py in f["ring"]]})
        return out

    def state(self, audit_limit: int | None = 50) -> dict:
        """The full session view the routes return: id, version, live keep-out features + place-object
        markers, and the audit tail."""
        return {"session": self.id, "version": self.version,
                "features": self.current_features(), "markers": self.current_markers(),
                "audit": self.audit(limit=audit_limit)}


# ---- the process-wide bounded session registry (capability-gated by opaque id) --------------------
_SESSIONS: "dict[str, EditSession]" = {}
_SESSIONS_LOCK = threading.Lock()


def new_session() -> EditSession:
    """Mint a fresh edit session with an unguessable opaque id; evict the oldest if the store is full."""
    sid = secrets.token_hex(8)
    sess = EditSession(sid)
    with _SESSIONS_LOCK:
        if len(_SESSIONS) >= MAX_SESSIONS:
            oldest = min(_SESSIONS.values(), key=lambda s: s.created_at)
            _SESSIONS.pop(oldest.id, None)
        _SESSIONS[sid] = sess
    return sess


def get_session(session_id: str) -> EditSession | None:
    """The session for an opaque id, or None if unknown/expired (the caller decides how to degrade)."""
    with _SESSIONS_LOCK:
        return _SESSIONS.get(str(session_id))


def reset() -> None:
    """Drop every session (test isolation / process reset)."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()
