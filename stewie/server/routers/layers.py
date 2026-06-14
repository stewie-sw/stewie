"""Map-layers router (ARCH-3): the legend (thresholds read straight from the physics) + the
geographic globe drape -- server-reprojected layer PNGs and their bboxes, rendered via
server.gis_layers (which owns the globe cache). Pure-compute / cache-backed: no shared app state,
no app-module import (no cycle).

The raster layers (/layers, /layers/raster/{kind}.png) deliberately STAY in server.py -- they read
the live _MOON_DEM cache, which is server-owned app state."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

router = APIRouter()


@router.get("/layers/legend")
def layers_legend():
    """Legend values FROM THE PHYSICS (audit P1): hazard thresholds are the hazard-map defaults
    (doc-true 20/15 + the 7.5 cm obstacle), the slope ramp is the renderer's real mapping, the
    shadow legend carries the live solar authority -- the UI never hardcodes a threshold."""
    import inspect

    from dart.hazard_map import build_hazard_map
    from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M
    sig = inspect.signature(build_hazard_map)
    return {
        "ok": True,
        "slope": {"max_deg": 30.0, "ramp": "green 0° → red 30° (opacity rises with steepness)"},
        "hazard": {"nogo_deg": sig.parameters["max_slope_deg"].default,
                   "penalty_deg": sig.parameters["slope_hazard_deg"].default,
                   "obstacle_m": OBSTACLE_HEIGHT_M,
                   "text": "red = no-go (> tested slope limit or rock above the obstacle envelope); "
                           "amber = penalty (> nominal slope)"},
        "illumination": {"sun": "horizon-clipped shadow at the mission-time sun (SPICE)",
                         "text": "blue = shadowed at the selected time"},
        "psr": {"sweep": "never lit across a 0–330° azimuth sweep at 3° elevation",
                "text": "violet = permanently shadowed region (PSR) candidate -- never sunlit; "
                        "the cold traps where water ice survives"},
        "dem": {"text": "cartographic hillshade (315°/45°) from the raw 5 m heightmap"},
    }


@router.get("/layers/globe/{kind}.png")
def globe_layer_png(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                    mission_t_s: float | None = None, color: str = "39ff14"):
    """The GEOGRAPHIC drape (server-reprojected; Aaron's rotated-tile screenshot fix)."""
    from stewie.server.gis_layers import _to_png, render_globe
    if mission_t_s is not None:
        from stewie.specs.solar import sun_az_el
        sun_az, sun_el = sun_az_el(-87.45, float(mission_t_s))
    try:
        out = render_globe(kind, sun_el=sun_el, sun_az=sun_az, grid_color=color[:7])
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM absent: {e}"})
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return Response(content=_to_png(out[0]), media_type="image/png")


@router.get("/layers/globe/{kind}/bbox")
def globe_layer_bbox(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                     mission_t_s: float | None = None):
    from stewie.server.gis_layers import render_globe
    if mission_t_s is not None:
        from stewie.specs.solar import sun_az_el
        sun_az, sun_el = sun_az_el(-87.45, float(mission_t_s))
    out = render_globe(kind, sun_el=sun_el, sun_az=sun_az)
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return {"ok": True, **out[1]}
