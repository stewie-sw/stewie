"""S-4: the object store -- named missions + custom structure templates (server CRUD).

The catalog the GIS pathway calls for: missions save the FULL authoring state (orders, keep-outs,
precedence, body) as one JSON document per slugged name under data_dir/missions/; custom structure
templates (a list of kind/offset/footprint entries) under data_dir/structures/, expandable at any
(x, y) into queue-ready orders. Names are slugged -- no path traversal by construction. These
files live on the same data_dir volume the W-1..W-3 journal/snapshot/replication machinery covers.
"""
from __future__ import annotations

import json
import os
import re
import time


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:64] or "unnamed"


def _owner_meta(path: str, owner: str) -> dict:
    """AG-05 (PRD §7.12): the created_by/created_at to write. On the FIRST save of a slug the supplied
    owner is stamped; on a re-save the ORIGINAL creator is preserved (no ownership theft via re-save).
    A pre-AG-05 file with no created_by is treated as first-owned-now by whoever re-saves it -- the
    listing surfaces legacy files as 'unknown' rather than backfilling them on disk."""
    if os.path.exists(path):
        try:
            prev = json.load(open(path))
            if prev.get("created_by"):
                return {"created_by": prev["created_by"], "created_at": prev.get("created_at", time.time())}
        except (json.JSONDecodeError, OSError):
            pass
    return {"created_by": owner, "created_at": time.time()}


def _dir(kind: str) -> str:
    from stewie.specs import config as CFG
    d = os.path.join(CFG.data_dir(), kind)
    os.makedirs(d, exist_ok=True)
    return d


# ---- AG-06: ownership-aware recoverable soft-delete -------------------------------------------
def owner_of(kind: str, name: str) -> str | None:
    """The created_by of a stored artifact, or None if it does not exist. A stored-but-unowned
    (pre-AG-05) artifact reads as 'unknown'."""
    path = os.path.join(_dir(kind), f"{_slug(name)}.json")
    if not os.path.exists(path):
        return None
    try:
        return json.load(open(path)).get("created_by", "unknown")
    except (json.JSONDecodeError, OSError):
        return "unknown"


def deletion_allowed(owner: str | None, identity: str, is_director: bool) -> bool:
    """AG-06 escalation policy: you may delete your OWN artifact; another operator's -- or an
    unowned/'unknown' -- artifact requires a director. A missing artifact (owner None) is a
    harmless no-op (allowed). (AG-07 will additionally require director for live-namespace artifacts.)"""
    if owner is None:
        return True
    return is_director or owner == identity


def _trash_dir(kind: str) -> str:
    d = os.path.join(_dir(kind), ".trash")          # not a *.json -> invisible to the live listing
    os.makedirs(d, exist_ok=True)
    return d


def soft_delete(kind: str, name: str) -> bool:
    """Move an artifact into the per-kind .trash (recoverable) instead of unlinking it."""
    slug = _slug(name)
    src = os.path.join(_dir(kind), f"{slug}.json")
    if not os.path.exists(src):
        return False
    os.replace(src, os.path.join(_trash_dir(kind), f"{slug}.{int(time.time() * 1000)}.json"))
    return True


def restore(kind: str, name: str) -> bool:
    """Restore the most-recent trashed copy of `name` back into the live store (slugs carry no '.',
    so the '.'-delimited timestamp suffix cannot collide a prefix slug)."""
    slug = _slug(name)
    hits = sorted(f for f in os.listdir(_trash_dir(kind))
                  if f.startswith(f"{slug}.") and f.endswith(".json"))
    if not hits:
        return False
    os.replace(os.path.join(_trash_dir(kind), hits[-1]),
               os.path.join(_dir(kind), f"{slug}.json"))
    return True


def list_trash(kind: str) -> list:
    return sorted(f for f in os.listdir(_trash_dir(kind)) if f.endswith(".json"))


def purge_trash(kind: str, filename: str) -> bool:
    """Permanently delete ONE trashed file (director-only, enforced by the route). Basename-confined:
    no path traversal out of .trash."""
    safe = os.path.basename(filename)
    p = os.path.join(_trash_dir(kind), safe)
    if safe.endswith(".json") and os.path.exists(p):
        os.unlink(p)
        return True
    return False


# ---- missions -----------------------------------------------------------------------------
_MISSION_KEYS = {"body", "orders", "keepouts", "precedence", "vehicle", "tools", "soil", "lander",
                 "mission_t0_s", "note"}


def save_mission(name: str, doc: dict, owner: str = "unknown") -> dict:
    unknown = set(doc) - _MISSION_KEYS                    # created_by/created_at are store-stamped, not client fields
    if unknown:
        raise ValueError(f"unknown mission fields {sorted(unknown)}")
    slug = _slug(name)
    path = os.path.join(_dir("missions"), f"{slug}.json")
    meta = _owner_meta(path, owner)
    from stewie.twin.io_fields import atomic_write_bytes
    atomic_write_bytes(path, json.dumps({"name": slug, "title": name, **meta, **doc},
                                        indent=1, sort_keys=True).encode())   # RC-05: atomic (.part->replace)
    return {"name": slug, "created_by": meta["created_by"]}


def list_missions() -> list:
    out = []
    for fn in sorted(os.listdir(_dir("missions"))):
        if fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(_dir("missions"), fn)))
                out.append({"name": d.get("name", fn[:-5]), "title": d.get("title", ""),
                            "body": d.get("body", "?"), "n_orders": len(d.get("orders", [])),
                            "owner": d.get("created_by", "unknown"), "created_at": d.get("created_at")})
            except (json.JSONDecodeError, OSError):
                continue
    return out


def load_mission(name: str) -> dict | None:
    path = os.path.join(_dir("missions"), f"{_slug(name)}.json")
    return json.load(open(path)) if os.path.exists(path) else None


def delete_mission(name: str) -> bool:
    """AG-06: recoverable soft-delete (moves to .trash, not unlink). The route enforces the
    ownership-escalation policy (deletion_allowed) before calling this."""
    return soft_delete("missions", name)


# ---- custom structure templates ------------------------------------------------------------
_ENTRY_KEYS = {"kind", "dx", "dy", "footprint_m2", "depth_m"}


def save_structure(name: str, doc: dict, owner: str = "unknown") -> dict:
    entries = doc.get("kind_list")
    if not isinstance(entries, list) or not entries or len(entries) > 64:
        raise ValueError("kind_list must be a non-empty list (max 64 entries)")
    for i, e in enumerate(entries):
        missing = _ENTRY_KEYS - set(e)
        if missing:
            raise ValueError(f"entry {i} missing {sorted(missing)}")
        if e["kind"] not in ("cut", "fill", "goto"):
            raise ValueError(f"entry {i} kind {e['kind']!r} not in cut/fill/goto")
    slug = _slug(name)
    path = os.path.join(_dir("structures"), f"{slug}.json")
    meta = _owner_meta(path, owner)
    from stewie.twin.io_fields import atomic_write_bytes
    atomic_write_bytes(path, json.dumps({"name": slug, "title": name, "kind_list": entries,
               "note": str(doc.get("note", "")), **meta}, indent=1, sort_keys=True).encode())   # RC-05: atomic
    return {"name": slug, "created_by": meta["created_by"]}


def list_structures() -> list:
    out = []
    for fn in sorted(os.listdir(_dir("structures"))):
        if fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(_dir("structures"), fn)))
                out.append({"name": d["name"], "title": d.get("title", ""),
                            "n_entries": len(d.get("kind_list", [])),
                            "owner": d.get("created_by", "unknown"), "created_at": d.get("created_at")})
            except (json.JSONDecodeError, OSError, KeyError):
                continue
    return out


def expand_structure(name: str, x: float, y: float) -> list | None:
    path = os.path.join(_dir("structures"), f"{_slug(name)}.json")
    if not os.path.exists(path):
        return None
    d = json.load(open(path))
    orders = []
    for i, e in enumerate(d["kind_list"]):
        o = {"action": f"{d['name']}-{i + 1}", "kind": e["kind"],
             "x": float(x) + float(e["dx"]), "y": float(y) + float(e["dy"])}
        if e["kind"] != "goto":
            o["footprint_m2"] = float(e["footprint_m2"])
            o["depth_m"] = float(e["depth_m"])
        orders.append(o)
    return orders


def delete_structure(name: str) -> bool:
    """AG-06: recoverable soft-delete (moves to .trash). Route enforces deletion_allowed first."""
    return soft_delete("structures", name)
