"""[REQ:FR-12] The ArcGIS integration BOUNDARY -- a named, honest boundary, NOT a claim that STEWIE is a
complete ArcGIS platform.

STEWIE does GIS-oriented lunar planning: OGC-WMS-style layer serving (routers/ogc.py, routers/layers.py) +
GeoJSON/COG export (lode.gis_export) + body-aware CRS + open mission packages (lode.mission_package). A LIVE
ArcGIS Feature Service (network read/query/edit with auth) is the GATED leg -- it needs an external ArcGIS
server + a token. This module provides the parts that ARE real here -- a GeoJSON<->ArcGIS-Feature
schema-mapped round-trip and the per-layer display-vs-planning eligibility check (reusing FR-10's WorldLayer)
-- and DECLARES the live-service surface as a boundary so nothing over-claims it, and a displayable layer is
never silently treated as planning-valid.
"""
from __future__ import annotations

#: Precise product language -- the positioning to use in UI/labels/docs (not "ArcGIS platform complete").
GIS_PRODUCT_LANGUAGE = (
    "GIS-oriented lunar planning: OGC-WMS-style layer serving + GeoJSON/COG export + body-aware CRS + open "
    "mission packages; ArcGIS Online basemap TILES for imagery. NOT a complete ArcGIS platform integration "
    "-- a live ArcGIS Feature Service is a gated adapter boundary (see ARCGIS_ADAPTER_BOUNDARY)."
)

#: the ArcGIS Feature Service integration surface a LIVE adapter would need. Declared as a boundary; the
#: network read/query/edit is GATED (needs a real ArcGIS server + auth token) -- not implemented here.
ARCGIS_ADAPTER_BOUNDARY = {
    "feature_service": {"read": "gated", "query": "gated", "edit": "gated"},
    "auth": "token (gated -- external ArcGIS server)",
    "schema_map": "supported (feature_to_arcgis / arcgis_to_feature)",
    "crs": "body-aware (WorldLayer.crs); per-layer vertical datum",
    "offline_package": "supported (lode.mission_package -- open GeoJSON/COG/STAC)",
    "round_trip": "supported (GeoJSON <-> ArcGIS Feature, this module)",
}


def _geom_to_arcgis(g: dict) -> dict:
    t, c = g.get("type"), g.get("coordinates")
    if c is None:
        raise ValueError(f"geometry has no coordinates: {t!r}")
    if t == "Point":
        return {"x": c[0], "y": c[1]}
    if t == "LineString":
        return {"paths": [[list(p) for p in c]]}
    if t == "Polygon":
        return {"rings": [[list(p) for p in ring] for ring in c]}
    raise ValueError(f"unsupported geometry type for ArcGIS: {t!r}")


def _geom_from_arcgis(g: dict) -> dict:
    if "x" in g and "y" in g:
        return {"type": "Point", "coordinates": [g["x"], g["y"]]}
    if "paths" in g:
        return {"type": "LineString", "coordinates": [list(p) for p in g["paths"][0]]}
    if "rings" in g:
        return {"type": "Polygon", "coordinates": [[list(p) for p in ring] for ring in g["rings"]]}
    raise ValueError("unsupported ArcGIS geometry")


def feature_to_arcgis(feature: dict, *, schema_map: dict | None = None, oid: int = 1) -> dict:
    """Map a GeoJSON Feature -> an ArcGIS Feature (attributes + geometry). ``schema_map`` renames GeoJSON
    property keys to ArcGIS attribute field names (identity when None)."""
    sm = schema_map or {}
    attrs = {sm.get(k, k): v for k, v in (feature.get("properties") or {}).items()}
    attrs["OBJECTID"] = oid
    return {"attributes": attrs, "geometry": _geom_to_arcgis(feature.get("geometry") or {})}


def arcgis_to_feature(af: dict, *, schema_map: dict | None = None) -> dict:
    """Inverse of feature_to_arcgis: ArcGIS Feature -> GeoJSON Feature (drops the OBJECTID)."""
    inv = {v: k for k, v in (schema_map or {}).items()}
    attrs = dict(af.get("attributes") or {})
    attrs.pop("OBJECTID", None)
    props = {inv.get(k, k): v for k, v in attrs.items()}
    return {"type": "Feature", "properties": props, "geometry": _geom_from_arcgis(af.get("geometry") or {})}


def layer_planning_eligible(world_layer) -> bool:
    """[REQ:FR-12] display-eligibility and planning-eligibility are SEPARATE (FR-10 WorldLayer): a layer may
    be displayable but not valid for planning. The planner must consult THIS, not mere displayability."""
    return bool(getattr(world_layer, "planning", False))


def assert_planning_eligible(world_layer) -> None:
    """Refuse a display-only layer for planning use, so it is never silently treated as planning-valid."""
    if not layer_planning_eligible(world_layer):
        raise ValueError(f"layer {getattr(world_layer, 'layer_id', '?')!r} is display-only, not planning-valid")
