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
_GLOBE_KINDS = ("dem", "slope", "hazard", "illumination", "incidence", "psr", "grid", "cost", "blocking",
                # LY-05 DEM-derivative analysis drapes: aspect (gradient azimuth) + curvature (Laplacian) from
                # the SAME heightfield gradient the slope drape uses, and roughness (window-RMS-slope, reusing
                # lode.costmap_layers._roughness as the one source of truth). All three render via _layer_rgba.
                "aspect", "curvature", "roughness",
                # T12 PHYSICS (TM) drape: the terramechanics-spine per-cell fields (physics.compaction is
                # OBSERVED state, not a plan-independent per-cell field -> deliberately absent, catalog-only)
                "bearing", "sinkage", "slip_risk", "traction_margin", "energy_cost", "excavation_resistance",
                # TW-11 TRAFFIC drape: the OBSERVED traversal-compaction state (traffic.compaction, the
                # per-site TrafficMemory Dr) draped over the fixed work-area crop -- real where the rover has
                # driven, transparent where it has not (public map data, uncached: it changes as runs fold).
                "traffic",
                # LY-07 CHANGED-TERRAIN drape: the SIGNED as-built-minus-base elevation difference (cut/fill
                # depth) from the composed CurrentTerrainView -- the producer for map.changed_terrain +
                # evidence.before_after_dem (public map data, uncached: it changes as each SIM run folds terrain).
                "changed_terrain")
_HEX6 = re.compile(r"^[0-9a-fA-F]{6}$")
_DEFAULT_GRID = "39ff14"
_MISSION_T_MAX_S = 3.156e10            # +/- ~1000 yr: finite-bounds an arbitrary mission_t_s


def _sanitize_color(color: str) -> str:
    """Restrict the grid color to exactly 6 hex digits (else the default). It is a cache-file
    component for kind='grid', so this bounds the cache key and forbids path/length abuse."""
    c = (color or "")[:6]
    return c if _HEX6.match(c) else _DEFAULT_GRID


def _quantize_sun(sun_el: float, sun_az: float, mission_t_s: float | None, site: str = "haworth"):
    """Clamp + quantize the sun geometry to integer degrees (el in [-90,90], az wrapped to [0,360)).
    A mission time, when given, is finite-bounded then resolved to the CHOSEN site's polar sun geometry
    first (#274/REG-01: site lat+lon feed sun_az_el, not a hardcoded Haworth latitude)."""
    if mission_t_s is not None:
        from stewie.specs.sites import site_latlon
        from stewie.specs.solar import sun_az_el
        mt = max(-_MISSION_T_MAX_S, min(_MISSION_T_MAX_S, float(mission_t_s)))
        _lat, _lon = site_latlon(site)
        sun_az, sun_el = sun_az_el(_lat, mt, site_lon_deg=_lon)
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
    from stewie.server.gis_layers import blocking_legend, physics_legend
    from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M
    sig = inspect.signature(build_hazard_map)
    return {
        "ok": True,
        # T12 PHYSICS (TM) drape: the terramechanics-spine per-cell fields, each a real solver output on the
        # DEM slope (built from the SAME PHYSICS_LAYERS spec the renderer colours with -- one source of truth).
        **physics_legend(),
        # AS-11 costmap analysis drape: the plan-independent traversability COST heatmap + the categorical
        # BLOCKING-REASON grid, both from the REAL 12-layer FORGE costmap (lode.costmap_layers.compose).
        "cost": {"ramp": "green (low) → amber → red (high)",
                 "text": "plan-independent traversability cost -- the summed FORGE costmap "
                         "(slope + roughness + sinkage + slip + illumination + shadow-confidence + energy) "
                         "the planner routes on, MINUS the goal-specific distance-to-goal; redder = costlier "
                         "to cross. Sun-dependent (the illumination/shadow layers follow the sun slider)."},
        "blocking": {"reasons": blocking_legend(),
                     "text": "impassable cells coloured by the FIRST costmap layer that vetoes them "
                             "(transparent where passable): why a route bends or refuses. Sun-dependent "
                             "(the psr veto follows the sun slider)."},
        "slope": {"max_deg": 30.0, "ramp": "green 0° → red 30° (opacity rises with steepness)"},
        # LY-05 DEM-derivative analysis drapes: aspect + curvature from the SAME heightfield gradient the
        # slope drape uses; roughness from lode.costmap_layers._roughness (one source of truth).
        "aspect": {"ramp": "cyclic hue wheel: N red → E chartreuse → S cyan → W violet (0–360°)",
                   "text": "gradient azimuth -- the compass direction the surface faces downhill (steepest "
                           "descent), from the same DEM gradient the slope drape uses; 0°=grid-north, "
                           "90°=east, clockwise. Near-flat cells fade out (aspect is undefined there)."},
        "curvature": {"ramp": "diverging: blue (convex-up ridge, ∇²z<0) → white (planar) → red "
                              "(concave-up hollow, ∇²z>0)",
                      "text": "Laplacian curvature ∇²z = ∂²z/∂x² + ∂²z/∂y² [1/m] from the DEM gradient; "
                              "convex-up ridges/mounds are negative, concave-up hollows/valleys positive; "
                              "near-planar ground is transparent (robustly scaled by the 98th percentile "
                              "of |∇²z|)."},
        "roughness": {"ramp": "sequential: pale (smooth) → deep (rough)",
                      "text": "local RMS-slope roughness -- the 3×3-window standard deviation of the slope "
                              "field, the same definition as the FORGE costmap roughness layer "
                              "(lode.costmap_layers._roughness, one source of truth); higher = rougher "
                              "terrain / mobility risk below the slope cap."},
        "hazard": {"nogo_deg": sig.parameters["max_slope_deg"].default,
                   "penalty_deg": sig.parameters["slope_hazard_deg"].default,
                   "obstacle_m": OBSTACLE_HEIGHT_M,
                   "text": "red = no-go (> tested slope limit or rock above the obstacle envelope); "
                           "amber = penalty (> nominal slope)"},
        "illumination": {"sun": "horizon-clipped shadow at the mission-time sun (SPICE)",
                         "text": "blue = shadowed at the selected time"},
        "incidence": {"sun": "solar incidence angle (DEM normal vs sun direction) at the selected geometry",
                      "text": "amber = grazing / facet-away light (0° normal-on faint → 90°+ grazing opaque); "
                              "washed-out cameras + poor solar flux even where geometrically lit"},
        "psr": {"sweep": "never lit across a 0–330° azimuth sweep at 3° elevation",
                "text": "violet = permanently shadowed region (PSR) candidate -- never sunlit; "
                        "the cold traps where water ice survives"},
        "dem": {"text": "cartographic hillshade (315°/45°) from the raw 5 m heightmap"},
        "traffic": {"bands": [{"dr": "0.0-0.2", "hex": "#f7f7f7", "label": "pristine / lightly trafficked"},
                              {"dr": "0.2-0.4", "hex": "#cccccc", "label": "compacted"},
                              {"dr": "0.4-0.6", "hex": "#969696", "label": "firm road"},
                              {"dr": "0.6-0.8", "hex": "#636363", "label": "firm road"},
                              {"dr": "0.8-1.0", "hex": "#252525", "label": "paved (RHO_DEEP)"}],
                    "text": "traversal hardening (relative density Dr) accumulated from repeated traffic "
                            "(TW-11); color = Dr band, opacity = normalized traversal intensity; Sigma_c "
                            "characteristic cumulative load is [CALIB]"},
        # LY-07 the SIGNED terrain-change / dig-fill-depth drape: the composed as-built/observed surface
        # (compose_terrain_view) minus the pristine base DEM. The producer for map.changed_terrain +
        # evidence.before_after_dem; per-cell depth via /world/point (runtime_evidence.as_built_delta_m).
        "changed_terrain": {"ramp": "diverging: red (cut, as-built below base) → white (no change, "
                                    "transparent) → blue (fill / berm, above base)",
                            "text": "signed terrain change -- the composed as-built/observed surface "
                                    "(compose_terrain_view) minus the pristine base DEM [m]: excavation (cut) "
                                    "is negative/red, deposited material (fill / berm) positive/blue, unworked "
                                    "ground transparent; opacity rises with |change| (robust 98th-pct scale). "
                                    "Per-cell depth via /world/point (as_built_delta_m). The visual producer "
                                    "for the catalog rows map.changed_terrain + evidence.before_after_dem; "
                                    "uncached (it changes as each SIM run folds terrain)."},
    }


@router.get("/layers/globe/{kind}.png")
def globe_layer_png(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                    mission_t_s: float | None = None, color: str = "39ff14",
                    site: str = "haworth", vmax: float = 30.0, classes: int = 0,
                    _auth: str = Depends(globe_quota)):
    """The GEOGRAPHIC drape (server-reprojected; Aaron's rotated-tile screenshot fix).
    GIS-03 (live-fix): PUBLIC base-map drape, per-IP rate-limited (no auth); params clamped/quantized; color sanitized; kind allow-listed.
    REG-01: ``site`` selects the imported tile so the globe drape follows the chosen site.
    G5 (#251): ``vmax``/``classes`` are the slope layer's graduated-renderer controls (clamped; ignored for other kinds)."""
    if kind not in _GLOBE_KINDS:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    from stewie.server.gis_layers import _to_png, render_globe
    el, az = _quantize_sun(sun_el, sun_az, mission_t_s, site)
    import math
    s_vmax = float(max(1.0, min(90.0, vmax))) if math.isfinite(vmax) else 30.0   # clamp [1,90]; NaN/inf -> default
    s_classes = int(max(0, min(12, classes)))            # 0 = continuous; up to 12 equal-interval bands
    try:
        out = render_globe(kind, sun_el=el, sun_az=az, grid_color=_sanitize_color(color), site=site,
                           slope_vmax=s_vmax, slope_classes=s_classes)
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
    el, az = _quantize_sun(sun_el, sun_az, mission_t_s, site)
    try:
        out = render_globe(kind, sun_el=el, sun_az=az, site=site)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM absent: {e}"})
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return {"ok": True, **out[1]}


@router.get("/layers/contours.geojson")
def layers_contours_geojson(site: str = "haworth", interval: float = 50.0,
                            _auth: str = Depends(globe_quota)):
    """[REQ:LY-05] The DEM elevation CONTOURS as a REAL GeoJSON vector product -- isolines traced by
    contourpy on the site's real LOLA heightfield at ``interval`` metres, reprojected to selenographic
    lon/lat (OGC:CRS84). One MultiLineString Feature per level. Display-only (LY-01 base.contours):
    an interpretation overlay, never a planning/release input. PUBLIC + per-IP rate-limited like the
    globe drapes; the interval is clamped so a tiny value cannot explode the trace."""
    import math
    from stewie.server.gis_layers import contour_geojson
    iv = float(interval) if math.isfinite(interval) else 50.0
    iv = max(1.0, min(1000.0, iv))                        # clamp the stated interval to [1, 1000] m
    try:
        fc = contour_geojson(site, iv)
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM absent: {e}"})
    return JSONResponse(content=fc, media_type="application/geo+json")
