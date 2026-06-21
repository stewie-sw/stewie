"""GIS export router (ARCH-3, PRD GI-03): standard GIS interop for a mission plan.

GET /export/geojson serializes a plan (build orders, keep-outs, the routed traverse, typed footprints) to
RFC-7946 GeoJSON in selenographic lon/lat via lode.gis_export -- the cockpit toolbox is client annotation,
this is the real interchange format a GIS consumer (QGIS / ArcGIS / web map) can load. The mission comes in
as a JSON-encoded query parameter (so the export is a cacheable GET); the site DEM + anchor resolve exactly
as in /plan (state.moon_dem, with an optional lat/lon globe site-pick override). A terrain raster -> COG
export ships only when rasterio/GDAL is importable (GET /export/cog/available reports that honestly); it is
never stubbed. No app-module import (no cycle)."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from stewie.server import state

router = APIRouter()
log = logging.getLogger("stewie.server")


@router.get("/export/geojson")
def export_geojson(
    mission: str = Query(..., description="the mission/plan as a JSON object (orders, keepouts, charger)"),
    site: str = Query("haworth", max_length=40),
    algorithm: str = Query("nearest", max_length=40),
    objective: str = Query("time", max_length=40),
    lat: float | None = Query(None, ge=-90.0, le=90.0),
    lon: float | None = Query(None, ge=-360.0, le=360.0),
    max_traverse_slope_deg: float = Query(25.0, ge=5.0, le=45.0),
):
    """Export the plan to an RFC-7946 GeoJSON FeatureCollection in lon/lat (PRD GI-03). The mission is a
    JSON object identical to the /plan body. Coordinates are projected from the order frame to selenographic
    lon/lat through the real-DEM IAU_2015:30135 transform; a plan outside the committed tile is a 400. A
    non-Moon body (no lunar DEM) cannot be georeferenced and is rejected with a clear 400."""
    from lode import gis_export as GE
    from lode import mission_planner as MP
    try:
        payload = json.loads(mission)
    except (json.JSONDecodeError, TypeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"mission is not valid JSON: {e}"})
    if not isinstance(payload, dict):
        return JSONResponse(status_code=400, content={"ok": False, "error": "mission must be a JSON object"})
    try:
        m = MP.mission_from_dict(payload)
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": f"bad mission: {e}"})
    if m.body != "moon":
        return JSONResponse(status_code=400, content={"ok": False, "error":
                            f"GeoJSON export needs a georeferenced lunar DEM; body {m.body!r} has none"})
    dem, origin = state.moon_dem(site)
    if dem is None:
        return JSONResponse(status_code=503, content={"ok": False, "error":
                            f"site {site!r} DEM bundle absent; cannot georeference the export"})
    try:
        bundle = MP.bundle_for_site(site)
    except (KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    if lat is not None and lon is not None:                    # M11: a globe site-pick overrides the anchor
        try:
            origin = MP.latlon_to_dem_origin(lat, lon, bundle_dir=bundle)
        except ValueError as e:
            return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
        except ImportError:
            log.warning("pyproj absent ([planner] extra); export lat/lon ignored, using flattest anchor")
    try:
        fc = GE.plan_to_geojson(m, dem=dem, dem_origin=origin, algorithm=algorithm, objective=objective,
                                max_traverse_slope_deg=max_traverse_slope_deg, bundle_dir=bundle)
    except ImportError as e:                                   # pyproj missing -> cannot project
        return JSONResponse(status_code=503, content={"ok": False, "error":
                            f"coordinate transform unavailable (install the [planner] extra): {e}"})
    except ValueError as e:                                    # a coord outside the committed tile
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return JSONResponse(content=fc, media_type="application/geo+json")


@router.get("/export/cog/available")
def export_cog_available():
    """Whether the terrain-raster -> COG (cloud-optimized GeoTIFF) export is available. COG needs the
    rasterio/GDAL stack, which is not a STEWIE dependency; this reports the real state honestly so the
    cockpit can hide/enable the control rather than offering a stub raster (PRD GI-03 / no-stub rule)."""
    from lode import gis_export as GE
    ok, reason = GE.cog_available()
    return {"ok": True, "available": ok, "reason": reason,
            "format": "cloud-optimized GeoTIFF (IAU_2015:30135)"}
