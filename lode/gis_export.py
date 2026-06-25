"""GI-03: standard GIS interop -- serialize a mission plan to RFC-7946 GeoJSON in selenographic lon/lat.

The cockpit toolbox is client-side annotation; this module is the real GIS export the PRD GI-03 item asks
for. A plan's build orders, keep-outs, the routed traverse, and the typed-footprint geometry are emitted
as a GeoJSON FeatureCollection with every coordinate projected from the local order frame to selenographic
lon/lat through the SAME IAU_2015:30135 south-polar stereographic transform the cockpit georef uses
(mission_planner.dem_origin_to_latlon) -- so the export lands on the real Haworth tile, not a fabricated
grid. RFC-7946 fixes the axis order to [lon, lat]; Polygon rings are closed.

A terrain raster -> COG (cloud-optimized GeoTIFF) export ships ONLY when a real raster backend
(rasterio/GDAL) is importable. When it is not, ``cog_available`` reports that honestly and ``plan_to_cog``
raises -- no stub raster is ever written (per the no-stub rule).
"""
from __future__ import annotations

import math
from typing import Any

from lode import mission_planner as MP

#: RFC-7946 6.1: the default CRS is WGS84 lon/lat (decimal degrees). The Moon is NOT WGS84, so the
#: document carries a provenance member naming the actual selenographic frame (the DEM is south-polar
#: stereographic on the R=1737400 m IAU mean sphere; lon/lat are geodetic on that sphere). A consumer
#: treating it as planetographic lunar coordinates is correct; treating it as Earth WGS84 is not.
_CRS_NAME = "IAU_2015:30100"  # Moon 2015 geographic (lon/lat on the IAU mean-sphere); DEM CRS = IAU_2015:30135


def _xy_to_lonlat(x: float, y: float, dem_origin, *, bundle_dir=None) -> list[float]:
    """Project a LOCAL order-frame point (x, y) [m] to selenographic [lon, lat] (deg), RFC-7946 axis order.

    A local order point is offset from the DEM order-frame origin by ``dem_origin`` (the same convention
    route_leg uses: DEM-frame metres = order metres + dem_origin), so the DEM->lon/lat inverse transform
    consumes ``(x + ox, y + oy)``. Raises ValueError if the point falls outside the committed tile and
    ImportError if pyproj (the [planner] extra) is absent -- the export never fabricates coordinates."""
    ox, oy = dem_origin
    lat, lon = MP.dem_origin_to_latlon(float(x) + float(ox), float(y) + float(oy), bundle_dir=bundle_dir)
    return [round(lon, 8), round(lat, 8)]


def _lonlat_to_xy(lon: float, lat: float, dem_origin, *, bundle_dir=None) -> tuple[float, float]:
    """Inverse of ``_xy_to_lonlat``: project a selenographic [lon, lat] (deg) back to a LOCAL order-frame
    point (x, y) [m], through the SAME IAU_2015:30135 transform (``latlon_to_dem_origin`` gives DEM-frame
    metres; subtract ``dem_origin`` to land in the order frame route_leg uses). Raises ValueError if the
    point falls outside the committed tile and ImportError if pyproj is absent -- it never fabricates a
    local coordinate."""
    ox, oy = dem_origin
    dx, dy = MP.latlon_to_dem_origin(float(lat), float(lon), bundle_dir=bundle_dir)
    return (float(dx) - float(ox), float(dy) - float(oy))


def _feature(geometry: dict, properties: dict) -> dict:
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _keepout_ring_xy(k: dict, *, n: int = 32) -> list[tuple[float, float]]:
    """The closed boundary ring (local order-frame metres) of a keep-out, as the planner stores it:
    a circle {x,y,r} (sampled), an axis-aligned rectangle {x0,y0,x1,y1}, or a polygon {points:[[x,y]...]}.
    First vertex repeated last so the GeoJSON linear ring is closed (RFC-7946 3.1.6)."""
    if "points" in k:
        ring = [(float(px), float(py)) for px, py in k["points"]]
    elif all(f in k for f in ("x0", "y0", "x1", "y1")):
        x0, y0, x1, y1 = float(k["x0"]), float(k["y0"]), float(k["x1"]), float(k["y1"])
        ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:                                                       # circle {x,y,r}
        cx, cy, r = float(k["x"]), float(k["y"]), float(k["r"])
        ring = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                for i in range(n)]
    if ring and ring[0] != ring[-1]:
        ring = ring + [ring[0]]                                 # close the ring
    return ring


def _footprint_ring_xy(order, *, n: int = 32) -> list[tuple[float, float]] | None:
    """The closed boundary ring (local order-frame metres) of a build order's typed footprint shape
    (CP-05: rectangle/circle/corridor/polygon, with orientation), centred on the order's (x, y). Returns
    None for a bare scalar-area order (no shape) -- only a typed shape yields real geometry, never a
    fabricated square."""
    shape = getattr(order, "shape", None)
    if not shape:
        return None
    cx, cy = float(order.x), float(order.y)
    kind = str(shape.get("kind", "")).lower()
    theta = math.radians(float(shape.get("theta_deg", 0.0)))
    ct, st = math.cos(theta), math.sin(theta)

    def _place(local: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(cx + lx * ct - ly * st, cy + lx * st + ly * ct) for lx, ly in local]

    if kind == "rectangle":
        w, h = float(shape["w"]) / 2.0, float(shape["h"]) / 2.0
        ring = _place([(-w, -h), (w, -h), (w, h), (-w, h)])
    elif kind == "corridor":
        length, width = float(shape["length"]) / 2.0, float(shape["width"]) / 2.0
        ring = _place([(-length, -width), (length, -width), (length, width), (-length, width)])
    elif kind == "circle":
        r = float(shape["r"])
        ring = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                for i in range(n)]
    elif kind == "polygon":
        ring = _place([(float(vx), float(vy)) for vx, vy in shape["vertices"]])
    else:
        return None
    if ring and ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    return ring


def plan_to_geojson(mission, *, dem, dem_origin, algorithm: str = "nearest", objective: str = "time",
                    max_traverse_slope_deg: float = 25.0, bundle_dir=None) -> dict[str, Any]:
    """Serialize a mission plan to an RFC-7946 GeoJSON FeatureCollection in selenographic lon/lat.

    Features (each tagged with a ``feature`` property so a GIS client can style by layer):
      - ``order``    : a Point per build order, carrying action/kind/footprint_m2/depth_m.
      - ``footprint``: a Polygon per typed-shape order (CP-05), the order's real footprint outline.
      - ``keepout``  : a Polygon per keep-out obstacle (circle sampled, rect, or polygon).
      - ``charger``  : a Point at the charger / safe-haven.
      - ``route``    : a LineString per routed GoTo leg (the DEM-aware traverse polyline from plan_ir).

    The route geometry is taken from the canonical plan IR (mission_planner.plan_ir) so the exported
    traverse is exactly the one the planner produced -- not an independent re-route. ``dem`` must be the
    real site DEM (the order frame is anchored at ``dem_origin``). Raises ImportError if pyproj is absent
    and ValueError if a coordinate falls outside the committed tile."""
    features: list[dict] = []

    # build orders -> Points (+ typed footprints -> Polygons)
    for o in mission.orders:
        pt = _xy_to_lonlat(o.x, o.y, dem_origin, bundle_dir=bundle_dir)
        features.append(_feature(
            {"type": "Point", "coordinates": pt},
            {"feature": "order", "action": o.action, "kind": o.kind,
             "footprint_m2": float(o.footprint_m2), "depth_m": float(o.depth_m)}))
        ring_xy = _footprint_ring_xy(o)
        if ring_xy is not None:
            ring = [_xy_to_lonlat(px, py, dem_origin, bundle_dir=bundle_dir) for px, py in ring_xy]
            features.append(_feature(
                {"type": "Polygon", "coordinates": [ring]},
                {"feature": "footprint", "action": o.action, "kind": o.kind}))

    # keep-out obstacles -> Polygons
    for i, k in enumerate(mission.keepouts):
        ring_xy = _keepout_ring_xy(k)
        ring = [_xy_to_lonlat(px, py, dem_origin, bundle_dir=bundle_dir) for px, py in ring_xy]
        features.append(_feature(
            {"type": "Polygon", "coordinates": [ring]},
            {"feature": "keepout", "index": i}))

    # charger / safe haven -> Point
    cx, cy = mission.charger
    features.append(_feature(
        {"type": "Point", "coordinates": _xy_to_lonlat(cx, cy, dem_origin, bundle_dir=bundle_dir)},
        {"feature": "charger"}))

    # routed traverse -> LineStrings (the canonical plan IR's DEM-aware GoTo polylines)
    ir = MP.plan_ir(mission, dem=dem, dem_origin=dem_origin, algorithm=algorithm, objective=objective,
                    max_traverse_slope_deg=max_traverse_slope_deg)
    for a in ir.get("actions", []):
        if a.get("op") != "GoTo":
            continue
        wp = a.get("waypoints") or []
        if len(wp) < 2:                                        # a blocked/degenerate leg has no polyline
            continue
        line = [_xy_to_lonlat(px, py, dem_origin, bundle_dir=bundle_dir) for px, py in wp]
        features.append(_feature(
            {"type": "LineString", "coordinates": line},
            {"feature": "route", "leg_id": a.get("id"), "vehicle": a.get("vehicle"),
             "reached": bool(a.get("reached", True))}))

    return {
        "type": "FeatureCollection",
        "crs_note": (f"selenographic lon/lat ({_CRS_NAME}); DEM source CRS IAU_2015:30135 "
                     "(Moon south-polar stereographic, R=1737400 m). NOT Earth WGS84."),
        "properties": {"mission": mission.name, "body": mission.body,
                       "algorithm": algorithm, "objective": objective,
                       "feasible": bool(ir.get("feasible", True))},
        "features": features,
    }


def geojson_to_features(fc: dict, *, dem_origin, bundle_dir=None) -> dict[str, Any]:
    """GI-03 IMPORT: parse an RFC-7946 GeoJSON FeatureCollection (selenographic lon/lat, the form
    ``plan_to_geojson`` emits, or any GIS client producing the same ``feature``-tagged layers) back into
    LOCAL order-frame geometry [m] -- the faithful inverse of ``plan_to_geojson`` through the SAME
    IAU_2015:30135 transform (``_lonlat_to_xy``).

    Returns the importable mission geometry grouped by the ``feature`` layer tag:
      - ``orders``  : ``{action, kind, x, y, footprint_m2, depth_m}`` per Point order.
      - ``keepouts``: ``{points: [[x, y]...], index}`` per keep-out Polygon (the outer ring in local m).
      - ``charger`` : ``[x, y]`` (or None if absent).
      - ``route``   : ``{leg_id, vehicle, waypoints: [[x, y]...]}`` per route LineString.
    Untagged / unknown layers and the ``footprint`` derived-geometry layer are ignored (the orders carry the
    authoritative shape). Raises ValueError on a non-FeatureCollection or a coordinate outside the committed
    tile, ImportError if pyproj is absent -- it never fabricates a local coordinate."""
    if not isinstance(fc, dict) or fc.get("type") != "FeatureCollection":
        raise ValueError("geojson_to_features expects an RFC-7946 FeatureCollection")
    out: dict[str, Any] = {"orders": [], "keepouts": [], "charger": None, "route": []}
    for f in fc.get("features", []) or []:
        props = (f or {}).get("properties") or {}
        geom = (f or {}).get("geometry") or {}
        layer, gtype, coords = props.get("feature"), geom.get("type"), geom.get("coordinates")
        if coords is None:                                  # a feature with no geometry carries nothing to import
            continue
        if layer == "order" and gtype == "Point":
            x, y = _lonlat_to_xy(coords[0], coords[1], dem_origin, bundle_dir=bundle_dir)
            out["orders"].append({"action": props.get("action"), "kind": props.get("kind"),
                                  "x": x, "y": y, "footprint_m2": float(props.get("footprint_m2", 0.0)),
                                  "depth_m": float(props.get("depth_m", 0.0))})
        elif layer == "keepout" and gtype == "Polygon":
            ring = [_lonlat_to_xy(lon, lat, dem_origin, bundle_dir=bundle_dir) for lon, lat in coords[0]]
            out["keepouts"].append({"points": [[x, y] for x, y in ring], "index": props.get("index")})
        elif layer == "charger" and gtype == "Point":
            x, y = _lonlat_to_xy(coords[0], coords[1], dem_origin, bundle_dir=bundle_dir)
            out["charger"] = [x, y]
        elif layer == "route" and gtype == "LineString":
            wp = [list(_lonlat_to_xy(lon, lat, dem_origin, bundle_dir=bundle_dir)) for lon, lat in coords]
            out["route"].append({"leg_id": props.get("leg_id"), "vehicle": props.get("vehicle"),
                                 "waypoints": wp})
    return out


# ---- terrain raster -> COG (cloud-optimized GeoTIFF) -------------------------------------------------
def cog_available() -> tuple[bool, str]:
    """Whether a real COG raster backend is importable. Returns (ok, reason). COG export needs rasterio
    (GDAL) -- it is NOT a STEWIE dependency, so on a default install this is (False, <why>). No stub
    raster is ever produced; the caller surfaces the blocked reason to the client."""
    try:
        import rasterio  # noqa: F401
    except ImportError as e:
        return False, (f"COG export needs the rasterio/GDAL stack (not a STEWIE dependency): {e}. "
                       "Install rasterio to enable cloud-optimized GeoTIFF export.")
    return True, "rasterio available"


def plan_to_cog(*_args, **_kwargs):
    """Export a terrain raster to a cloud-optimized GeoTIFF. Implemented only when rasterio/GDAL is
    importable (see cog_available); otherwise raises RuntimeError rather than writing a stub raster."""
    ok, reason = cog_available()
    if not ok:
        raise RuntimeError(reason)
    return _plan_to_cog_rasterio(*_args, **_kwargs)


def _plan_to_cog_rasterio(dem, dem_origin, out_path: str, *, bundle_dir=None) -> str:
    """Write the site DEM heightfield to a cloud-optimized GeoTIFF in the DEM's south-polar stereographic
    CRS (IAU_2015:30135). Tiled + overviews = the COG layout. Reached only when rasterio is importable."""
    import json as _json
    import os as _os

    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import from_origin

    from stewie.terrain import site_dem as SD
    Z, cell = dem
    Z = np.asarray(Z, dtype="float32")
    with open(_os.path.join(SD._haworth_bundle(bundle_dir), "metadata.json")) as _f:
        meta = _json.load(_f)
    b = meta["world_bounds_m"]
    transform = from_origin(float(b["x0"]), float(b["y1"]), float(cell), float(cell))   # north-up raster
    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 1,
        "height": Z.shape[0], "width": Z.shape[1], "transform": transform,
        "crs": "IAU_2015:30135", "tiled": True, "blockxsize": 256, "blockysize": 256,
        "compress": "deflate",
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(Z, 1)
        factors = [2, 4, 8, 16]
        dst.build_overviews(factors, Resampling.average)
        dst.update_tags(ns="rio_overview", resampling="average")
    return out_path
