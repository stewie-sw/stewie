"""[REQ:GW-04] Asset Library -- the durable-asset REGISTRY for the GIS mission workbench.

STEWIE persists several kinds of DURABLE asset under ``$STEWIE_DATA_DIR`` (+ the real LOLA DEM
bundles in ``samples/lunar_dem/``). The GIS workbench needs to browse/search/inspect/export/recover
them SEPARATELY from the visible map layers (a layer is a rendered view; an asset is a stored object
with provenance). This module is the pure enumerator over the EXISTING persistence -- it invents no
new store: it reads the same on-disk artifacts the object store (``server.objects``), the reports
directory (``config.reports_dir``), the versioned observed-twin journals (``twin/*.journal``), the
per-site Terrain-Memory world model (``twin.terrain_memory``), and the DEM sample bundles already own.

Scope + honesty (the S-06 boundary):
  * The PUBLIC registry lists the LIVE/SHARED + world/map durable assets -- live missions, shared
    structure templates, mission-control reports, per-site Terrain Memory, the observed-twin journals,
    and the real DEM bundles -- as a MANIFEST (type / id / created / provenance / size). It exposes
    metadata + provenance, NOT the sensitive payloads: the mission ORDER list and the report BYTES stay
    behind the auth-gated ``/missions/{name}`` and ``/reports/{name}`` (like ``/world/layer-manifest`` is
    the public projection of the auth-gated ``/world``).
  * PER-OWNER SANDBOX scratch (autosave drafts, per-owner sim runs, per-owner soil overlays) is PRIVATE
    and is NOT listed here -- it is a private scratch space, not a shared durable asset.

Every record carries a ``provenance`` string (the acceptance requires every durable object to trace to
provenance). Recovery reuses the existing recoverable soft-delete (``server.objects.restore``): a
soft-deleted mission/structure lives in its ``.trash`` and is restored in place; the observed-twin
journal is cold-restorable (``TwinStore.from_journal``). No fabricated assets: an empty store yields an
empty list, never a placeholder.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from stewie.server import objects as OBJ

# The durable asset TYPES this registry enumerates (stable ids used by the routes + the frontend panel).
ASSET_TYPES = ("mission", "structure", "report", "site", "twin", "dem")

# report file formats surfaced as a single report asset (the pdf is the deliverable, the md its source).
_REPORT_EXTS = (".pdf", ".md")


def _repo_root() -> str:
    # stewie/server/asset_library.py -> stewie/server -> stewie -> <repo>
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _size(path: str) -> int:
    try:
        return int(os.path.getsize(path))
    except OSError:
        return 0


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            total += _size(os.path.join(root, f))
    return total


# ---- per-type enumerators (each reads the EXISTING persistence) --------------------------------
def _mission_assets() -> list[dict[str, Any]]:
    """LIVE (shared, command-eligible) missions -- the durable authoring state (server.objects). The
    order PAYLOAD stays auth-gated at /missions/{name}; here we carry only the manifest metadata."""
    d0 = OBJ._ns_dir("missions", "live")
    out: list[dict[str, Any]] = []
    for m in OBJ.list_missions(namespace="live"):
        name = m.get("name", "")
        out.append({
            "type": "mission",
            "id": name,
            "title": m.get("title") or name,
            "created": m.get("created_at"),
            "provenance": f"authored by {m.get('owner', 'unknown')} (live namespace)",
            "size_bytes": _size(os.path.join(d0, f"{name}.json")),
            "namespace": "live",
            "recoverable": True,                          # soft-delete/restore (server.objects.restore)
            "detail": {"body": m.get("body", "?"), "n_orders": m.get("n_orders", 0),
                       "owner": m.get("owner", "unknown")},
            "inspect_href": f"/library/mission/{name}",
            "export_href": f"/library/mission/{name}/export",
            "payload_href": f"/missions/{name}",          # the auth-gated full order payload
        })
    return out


def _structure_assets() -> list[dict[str, Any]]:
    """SHARED custom structure templates (server.objects, live namespace)."""
    d0 = OBJ._ns_dir("structures", "live")
    out: list[dict[str, Any]] = []
    for s in OBJ.list_structures(namespace="live"):
        name = s.get("name", "")
        out.append({
            "type": "structure",
            "id": name,
            "title": s.get("title") or name,
            "created": s.get("created_at"),
            "provenance": f"authored by {s.get('owner', 'unknown')} (shared template)",
            "size_bytes": _size(os.path.join(d0, f"{name}.json")),
            "namespace": "live",
            "recoverable": True,
            "detail": {"n_entries": s.get("n_entries", 0), "owner": s.get("owner", "unknown")},
            "inspect_href": f"/library/structure/{name}",
            "export_href": f"/library/structure/{name}/export",
        })
    return out


def _report_assets() -> list[dict[str, Any]]:
    """Mission-control reports (PDF + md) under config.reports_dir. Grouped by stem so a report is ONE
    asset with the formats it has; the BYTES stay auth-gated at /reports/{name}."""
    from stewie.specs.config import reports_dir
    rdir = reports_dir()
    if not os.path.isdir(rdir):
        return []
    stems: dict[str, dict[str, Any]] = {}
    for fn in sorted(os.listdir(rdir)):
        stem, ext = os.path.splitext(fn)
        if ext not in _REPORT_EXTS:
            continue
        path = os.path.join(rdir, fn)
        rec = stems.setdefault(stem, {"formats": {}, "created": None, "size_bytes": 0})
        rec["formats"][ext.lstrip(".")] = fn
        rec["size_bytes"] += _size(path)
        try:
            mt = os.path.getmtime(path)
            rec["created"] = mt if rec["created"] is None else max(rec["created"], mt)
        except OSError:
            pass
    out: list[dict[str, Any]] = []
    for stem, rec in sorted(stems.items()):
        fmts = rec["formats"]
        out.append({
            "type": "report",
            "id": stem,
            "title": stem.replace("_", " "),
            "created": rec["created"],
            "provenance": "mission-control report (derived from a plan run)",
            "size_bytes": rec["size_bytes"],
            "namespace": "derived",
            "recoverable": False,                         # regenerable from the plan, not trash-restored
            "detail": {"formats": sorted(fmts)},
            "inspect_href": f"/library/report/{stem}",
            "export_href": f"/library/report/{stem}/export",
            # the auth-gated deliverable bytes (opaque report id); pdf preferred, else md
            "payload_href": "/reports/" + (fmts.get("pdf") or fmts.get("md") or stem),
        })
    return out


def _site_assets() -> list[dict[str, Any]]:
    """Per-site Terrain Memory -- the authoritative persisted world-model change (twin.terrain_memory,
    a .npz under data_dir/terrain_memory/). The summary (version / cells changed / net volume) is
    world-model map data; the underlying grid stays server-side."""
    from stewie.specs.config import data_dir
    from stewie.twin import terrain_memory as TM
    tdir = os.path.join(data_dir(), "terrain_memory")
    if not os.path.isdir(tdir):
        return []
    out: list[dict[str, Any]] = []
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".npz"):
            continue
        site = fn[:-4]
        path = os.path.join(tdir, fn)
        detail: dict[str, Any] = {}
        try:
            mem = TM.load_site(data_dir(), site)
            if mem is not None:
                s = mem.summary()
                detail = {"version": s.get("version", 0), "cells_changed": s.get("cells_changed", 0),
                          "net_volume_m3": s.get("net_volume_m3", 0.0), "chain_valid": mem.verify_chain(),
                          "n_missions": len(s.get("missions", []))}
        except Exception:  # noqa: BLE001 -- a torn/legacy .npz still lists as an asset (no fabricated summary)
            detail = {}
        out.append({
            "type": "site",
            "id": site,
            "title": f"{site} terrain memory",
            "created": (os.path.getmtime(path) if os.path.exists(path) else None),
            "provenance": ("terrain-memory world model (hash-chained, "
                           + str(detail.get("n_missions", 0)) + " recorded missions)"),
            "size_bytes": _size(path),
            "namespace": "world",
            "recoverable": False,                         # the authoritative persisted state (re-openable)
            "detail": detail,
            "inspect_href": f"/library/site/{site}",
            "export_href": f"/library/site/{site}/export",
        })
    return out


def _twin_assets() -> list[dict[str, Any]]:
    """Per-site observed-twin JOURNALS (data_dir/twin/*.journal) -- the append-only, hash-chained edit
    log the versioned observed terrain replays. Cold-restorable via TwinStore.from_journal."""
    from stewie.specs.config import data_dir
    tdir = os.path.join(data_dir(), "twin")
    if not os.path.isdir(tdir):
        return []
    out: list[dict[str, Any]] = []
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".journal"):
            continue
        site = fn[:-len(".journal")]
        path = os.path.join(tdir, fn)
        try:
            with open(path, encoding="utf-8") as fh:
                n_events = sum(1 for ln in fh if ln.strip())
        except OSError:
            n_events = 0
        out.append({
            "type": "twin",
            "id": site,
            "title": f"{site} observed-twin journal",
            "created": (os.path.getmtime(path) if os.path.exists(path) else None),
            "provenance": f"observed-terrain event journal (hash-chained, {n_events} events)",
            "size_bytes": _size(path),
            "namespace": "world",
            "recoverable": True,                          # cold restore (TwinStore.from_journal)
            "detail": {"n_events": n_events},
            "inspect_href": f"/library/twin/{site}",
            "export_href": f"/library/twin/{site}/export",
        })
    return out


def _dem_assets() -> list[dict[str, Any]]:
    """The real LOLA DEM sample bundles (samples/lunar_dem/<id>/) -- durable input map assets with
    provenance from each bundle's metadata.json. Absent in a stripped wheel deploy -> simply omitted
    (no fabricated DEM). $STEWIE_DEM_DIR points a deployment at the (large, unpackaged) bundle root."""
    root = os.environ.get("STEWIE_DEM_DIR")
    base = os.path.dirname(root) if root else os.path.join(_repo_root(), "samples", "lunar_dem")
    if not os.path.isdir(base):
        return []
    out: list[dict[str, Any]] = []
    for name in sorted(os.listdir(base)):
        bundle = os.path.join(base, name)
        meta_path = os.path.join(bundle, "metadata.json")
        if not (os.path.isdir(bundle) and os.path.isfile(meta_path)):
            continue
        producer = grid = None
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
            producer = meta.get("producer")
            grid = meta.get("grid")
        except (json.JSONDecodeError, OSError):
            meta = {}
        out.append({
            "type": "dem",
            "id": name,
            "title": name.replace("_", " "),
            "created": (os.path.getmtime(meta_path)),
            "provenance": (producer or "real LOLA DEM bundle"),
            "size_bytes": _dir_size(bundle),
            "namespace": "prior",
            "recoverable": False,
            "detail": {"grid": grid} if grid else {},
            "inspect_href": f"/library/dem/{name}",
            "export_href": f"/library/dem/{name}/export",
        })
    return out


_ENUMERATORS = {
    "mission": _mission_assets,
    "structure": _structure_assets,
    "report": _report_assets,
    "site": _site_assets,
    "twin": _twin_assets,
    "dem": _dem_assets,
}


# ---- public API --------------------------------------------------------------------------------
def _matches(rec: dict[str, Any], q: str) -> bool:
    """Case-insensitive substring search over the fields a browser searches: type / id / title /
    provenance."""
    hay = " ".join(str(rec.get(k, "")) for k in ("type", "id", "title", "provenance")).lower()
    return q.lower() in hay


def list_assets(*, q: str | None = None, atype: str | None = None) -> list[dict[str, Any]]:
    """Browse (+ optional search ``q`` / type filter ``atype``) the durable assets. Returns a flat list
    of records, each with type / id / title / created / provenance / size_bytes / namespace / recoverable
    + type-specific detail + inspect/export hrefs. Deterministic order: by (type, id)."""
    types = (atype,) if atype in _ENUMERATORS else ASSET_TYPES
    out: list[dict[str, Any]] = []
    for t in types:
        try:
            out.extend(_ENUMERATORS[t]())
        except Exception:  # noqa: BLE001 -- one broken store must not blank the whole library
            continue
    if q:
        out = [r for r in out if _matches(r, q)]
    out.sort(key=lambda r: (r["type"], str(r["id"])))
    return out


def counts(assets: list[dict[str, Any]]) -> dict[str, int]:
    """Per-type counts for the panel summary (browse header)."""
    c: dict[str, int] = {}
    for r in assets:
        c[r["type"]] = c.get(r["type"], 0) + 1
    return c


def get_asset(atype: str, aid: str) -> dict[str, Any] | None:
    """Inspect ONE asset: its manifest record + safe type-specific detail. None if not found. Never
    returns a sensitive payload (mission orders / report bytes stay auth-gated)."""
    if atype not in _ENUMERATORS:
        return None
    for r in _ENUMERATORS[atype]():
        if str(r["id"]) == aid:
            return r
    return None


def trash_assets() -> list[dict[str, Any]]:
    """The recoverable SOFT-DELETED assets (missions + structures) -- what a 'recover' can restore. Each
    carries the trashed filename so the recover route (or an admin purge) can name it."""
    out: list[dict[str, Any]] = []
    for kind, atype in (("missions", "mission"), ("structures", "structure")):
        try:
            trash = OBJ.list_trash(kind, namespace="live")
        except Exception:  # noqa: BLE001
            trash = []
        for fn in trash:
            # trashed filename is "<slug>.<ms>.json" (restore keys on the slug prefix)
            slug = fn.split(".", 1)[0]
            out.append({"type": atype, "id": slug, "trash_file": fn, "deleted": True,
                        "recoverable": True, "provenance": f"soft-deleted {atype} (recoverable from .trash)"})
    return out


def recover_asset(atype: str, aid: str) -> dict[str, Any]:
    """RECOVER (restore) a soft-deleted durable asset from its .trash, in place. Delegates to the
    existing recoverable soft-delete (server.objects.restore) for missions + structures. Returns
    {ok, restored, type, id}. The observed-twin journal recovers by cold restore (server lifecycle,
    not a per-request op), so it reports ok=False with a reason rather than pretending."""
    kind = {"mission": "missions", "structure": "structures"}.get(atype)
    if kind is None:
        return {"ok": False, "restored": False, "type": atype, "id": aid,
                "reason": f"{atype} is not trash-recoverable (a report is regenerated; a twin cold-restores)"}
    restored = OBJ.restore(kind, aid, namespace="live")
    return {"ok": bool(restored), "restored": bool(restored), "type": atype, "id": aid,
            "reason": None if restored else "no trashed copy to restore"}


def export_record(atype: str, aid: str) -> dict[str, Any] | None:
    """The EXPORTABLE descriptor for one asset: its full manifest record + an ``exported_at`` stamp,
    suitable for a JSON download (the durable-asset provenance record). The heavy payload (report PDF,
    mission orders) is referenced by ``payload_href`` (auth-gated), never inlined here."""
    rec = get_asset(atype, aid)
    if rec is None:
        return None
    return {"schema": "stewie.asset_library.v1", "exported_at": time.time(), **rec}
