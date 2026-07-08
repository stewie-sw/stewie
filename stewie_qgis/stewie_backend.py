"""Pure STEWIE-backend helpers for the QGIS Processing provider (P-A #46) -- fetch + parse, deliberately with
NO ``qgis`` import so this parse logic is unit-testable in plain CI (no QGIS runtime) against a real backend
fixture. The QGIS algorithms in ``stewie_algorithms`` import these and wrap them with QGIS feature output.

Wraps the PUBLIC read endpoints the keyless artemis proxy serves: /world/terramechanics-layers (the physics
spine) and /world/point (per-cell terramechanics). No synthetic data -- the algorithms hit the live backend.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

DEFAULT_API_BASE = "http://127.0.0.1:8000"   # the backend is host-local; the public artemis proxy also works


def fetch_json(url: str, timeout: float = 20.0) -> dict:
    """GET a JSON document. Raises on a transport error; returns the parsed dict otherwise."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (trusted STEWIE endpoint)
        return json.loads(resp.read().decode("utf-8"))


def spine_url(api_base: str, site: str) -> str:
    return api_base.rstrip("/") + "/world/terramechanics-layers?site=" + urllib.parse.quote(site)


def point_url(api_base: str, site: str, lon: float, lat: float) -> str:
    return (api_base.rstrip("/") + "/world/point?site=" + urllib.parse.quote(site)
            + "&lon=" + str(lon) + "&lat=" + str(lat))


def terramechanics_rows(resp: dict) -> list[dict]:
    """A /world/terramechanics-layers response -> the derived-layer rows (layer, group, source terms, backend)."""
    if not resp or not resp.get("ok"):
        raise ValueError("terramechanics spine unavailable: %s" % (resp.get("error") if resp else "no response"))
    rows = []
    for d in resp.get("derived_layers", []):
        lid = str(d.get("layer", ""))
        rows.append({
            "layer": lid,
            "group": lid.split(".")[0] if "." in lid else "",
            "terms": ",".join(d.get("from_terms", []) or []),
            "computes": ",".join(d.get("computed_terms", []) or []),
            "backend": d.get("backend") or resp.get("backend") or "",
        })
    return rows


def point_attributes(resp: dict) -> dict:
    """A /world/point response -> {site, cell, attributes:[{id,label,unit,value,available}]}."""
    if not resp or not resp.get("ok"):
        raise ValueError("point query failed: %s" % (resp.get("error") if resp else "no response"))
    attrs = []
    for a in resp.get("attributes", []) or []:
        attrs.append({
            "id": a.get("id"), "label": a.get("label"), "unit": a.get("unit") or "",
            "value": a.get("value"), "available": bool(a.get("available")),
        })
    return {"site": resp.get("site"), "cell": resp.get("cell") or {}, "attributes": attrs}
