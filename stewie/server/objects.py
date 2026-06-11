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


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:64] or "unnamed"


def _dir(kind: str) -> str:
    from stewie.specs import config as CFG
    d = os.path.join(CFG.data_dir(), kind)
    os.makedirs(d, exist_ok=True)
    return d


# ---- missions -----------------------------------------------------------------------------
_MISSION_KEYS = {"body", "orders", "keepouts", "precedence", "vehicle", "tools", "soil", "lander",
                 "mission_t0_s", "note"}


def save_mission(name: str, doc: dict) -> dict:
    unknown = set(doc) - _MISSION_KEYS
    if unknown:
        raise ValueError(f"unknown mission fields {sorted(unknown)}")
    slug = _slug(name)
    path = os.path.join(_dir("missions"), f"{slug}.json")
    from stewie.twin.io_fields import atomic_write_bytes
    atomic_write_bytes(path, json.dumps({"name": slug, "title": name, **doc},
                                        indent=1, sort_keys=True).encode())   # RC-05: atomic (.part->replace)
    return {"name": slug}


def list_missions() -> list:
    out = []
    for fn in sorted(os.listdir(_dir("missions"))):
        if fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(_dir("missions"), fn)))
                out.append({"name": d.get("name", fn[:-5]), "title": d.get("title", ""),
                            "body": d.get("body", "?"), "n_orders": len(d.get("orders", []))})
            except (json.JSONDecodeError, OSError):
                continue
    return out


def load_mission(name: str) -> dict | None:
    path = os.path.join(_dir("missions"), f"{_slug(name)}.json")
    return json.load(open(path)) if os.path.exists(path) else None


def delete_mission(name: str) -> bool:
    path = os.path.join(_dir("missions"), f"{_slug(name)}.json")
    if os.path.exists(path):
        os.unlink(path)
        return True
    return False


# ---- custom structure templates ------------------------------------------------------------
_ENTRY_KEYS = {"kind", "dx", "dy", "footprint_m2", "depth_m"}


def save_structure(name: str, doc: dict) -> dict:
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
    from stewie.twin.io_fields import atomic_write_bytes
    atomic_write_bytes(path, json.dumps({"name": slug, "title": name, "kind_list": entries,
               "note": str(doc.get("note", ""))}, indent=1, sort_keys=True).encode())   # RC-05: atomic
    return {"name": slug}


def list_structures() -> list:
    out = []
    for fn in sorted(os.listdir(_dir("structures"))):
        if fn.endswith(".json"):
            try:
                d = json.load(open(os.path.join(_dir("structures"), fn)))
                out.append({"name": d["name"], "title": d.get("title", ""),
                            "n_entries": len(d.get("kind_list", []))})
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
    path = os.path.join(_dir("structures"), f"{_slug(name)}.json")
    if os.path.exists(path):
        os.unlink(path)
        return True
    return False
