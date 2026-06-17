"""Map-layers router (ARCH-3): the legend (thresholds read straight from the physics) + the
geographic globe drape -- server-reprojected layer PNGs and their bboxes, rendered via
server.gis_layers (which owns the globe cache). Pure-compute / cache-backed: no shared app state,
no app-module import (no cycle).

The raster layers (/layers, /layers/raster/{kind}.png) deliberately STAY in server.py -- they read
the live _MOON_DEM cache, which is server-owned app state."""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from stewie.server.ratelimit import RateLimiter, client_ip

router = APIRouter()

# GIS-03 fix (live-site map-401): the globe drape is the cockpit's base terrain view -- a map you
# cannot see is worse than the DoS the rate-limit already covers. So it is PUBLIC (no auth, unlike the
# planner's heavy_quota which gated it and 401'd the map), but rate-limited PER CLIENT IP so the heavy
# server-side reprojection still cannot be hammered. Tunable via STEWIE_GLOBE_QUOTA_MAX/_WINDOW_S.
_globe_quota = RateLimiter(int(os.environ.get("STEWIE_GLOBE_QUOTA_MAX", "180")),
                           float(os.environ.get("STEWIE_GLOBE_QUOTA_WINDOW_S", "60")))


def globe_quota(request: Request) -> str:
    ip = client_ip(request)
    if not _globe_quota.allow(ip):
        raise HTTPException(status_code=429, detail="globe-layer render quota exceeded; slow down")
    return ip

# GIS-03: bound the params so an unbounded float/string stream cannot force unbounded renders + cache
# growth (DoS). Sun angles quantize to integer degrees (sub-degree changes are not visible in the
# drape and would otherwise multiply the cache key space); `color` becomes a cache-FILE component for
# kind='grid', so it is restricted to 6 hex digits (rejecting length/path abuse); `kind` is allow-listed.
_GLOBE_KINDS = ("dem", "slope", "hazard", "illumination", "psr", "grid")
_HEX6 = re.compile(r"^[0-9a-fA-F]{6}$")
_DEFAULT_GRID = "39ff14"
_MISSION_T_MAX_S = 3.156e10            # +/- ~1000 yr: finite-bounds an arbitrary mission_t_s


def _sanitize_color(color: str) -> str:
    """Restrict the grid color to exactly 6 hex digits (else the default). It is a cache-file
    component for kind='grid', so this bounds the cache key and forbids path/length abuse."""
    c = (color or "")[:6]
    return c if _HEX6.match(c) else _DEFAULT_GRID


def _quantize_sun(sun_el: float, sun_az: float, mission_t_s: float | None):
    """Clamp + quantize the sun geometry to integer degrees (el in [-90,90], az wrapped to [0,360)).
    A mission time, when given, is finite-bounded then resolved to the polar sun geometry first."""
    if mission_t_s is not None:
        from stewie.specs.solar import sun_az_el
        mt = max(-_MISSION_T_MAX_S, min(_MISSION_T_MAX_S, float(mission_t_s)))
        sun_az, sun_el = sun_az_el(-87.45, mt)
    el = float(max(-90.0, min(90.0, round(float(sun_el)))))
    az = float(round(float(sun_az)) % 360)
    return el, az


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
                    mission_t_s: float | None = None, color: str = "39ff14",
                    site: str = "haworth", _auth: str = Depends(globe_quota)):
    """The GEOGRAPHIC drape (server-reprojected; Aaron's rotated-tile screenshot fix).
    GIS-03 (live-fix): PUBLIC base-map drape, per-IP rate-limited (no auth); params clamped/quantized; color sanitized; kind allow-listed.
    REG-01: ``site`` selects the imported tile so the globe drape follows the chosen site."""
    if kind not in _GLOBE_KINDS:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    from stewie.server.gis_layers import _to_png, render_globe
    el, az = _quantize_sun(sun_el, sun_az, mission_t_s)
    try:
        out = render_globe(kind, sun_el=el, sun_az=az, grid_color=_sanitize_color(color), site=site)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM absent: {e}"})
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return Response(content=_to_png(out[0]), media_type="image/png")


@router.get("/layers/globe/{kind}/bbox")
def globe_layer_bbox(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                     mission_t_s: float | None = None, site: str = "haworth",
                     _auth: str = Depends(globe_quota)):
    """GIS-03 (live-fix): PUBLIC base-map drape, per-IP rate-limited (no auth); sun params clamped/quantized; kind allow-listed.
    REG-01: ``site`` selects the imported tile (the bbox is that site's footprint)."""
    if kind not in _GLOBE_KINDS:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    from stewie.server.gis_layers import render_globe
    el, az = _quantize_sun(sun_el, sun_az, mission_t_s)
    try:
        out = render_globe(kind, sun_el=el, sun_az=az, site=site)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM absent: {e}"})
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return {"ok": True, **out[1]}
