"""[REQ:GW-12] Planet-fixed-authoritative + local-render-origin coordinate contract (single-precision safe).

ONE documented, tested contract for STEWIE's coordinates:

  * AUTHORITATIVE coordinates exist ONLY in the lunar CRSs on the server -- IAU_2015:30135 (south-polar
    stereographic) / 30100 (selenographic) for a curated tile, or an ad-hoc tile's LOCAL azimuthal-equidistant
    frame. The persisted form is the DEM ORDER FRAME (site-origin-relative metres, x East / y raster-down), the
    native input of /api/plan, which maps to a lunar CRS through the site_dem.py transforms.
  * Every RENDER surface (cockpit 3D three3d.js, /ide 3D viz3d/frame.js, the Cesium globe, Godot) declares a
    LOCAL origin near the work area and renders float32-relative to it. The cockpit renders directly in the
    order frame (site-origin metres); the /ide frame.js recentres to the tile origin (ENU) or drapes onto the
    body-fixed sphere (globe), keeping the float32 magnitudes small.
  * Every pick/edit/measure converts BACK through the site_dem.py transforms (latlon_to_dem_origin /
    dem_origin_to_latlon) -- or, on the render side, frame.js metresToLonLat -- before persisting. No render
    surface stores its renderer-local (recentred / rotated / body-fixed) frame into a mission feature.

This module is the executable acceptance for that contract, on REAL committed DEM metadata (no fabricated
coordinates):

  (a) coordinate round-trip error < 1 cm at the 30135 theme-extent corners, at each imported site anchor, AND
      at an ad-hoc tile center, using the REAL site_dem transforms.
  (b) the largest coordinate magnitude handed to a float32 render path stays under a documented ulp budget
      (float32 keeps 1 cm representable below ~2^17 m; the ~10 km tile extent fits with an ~8.7x margin).
  (c) a grep/AST guard that no gis/qwc2/js/** or web/assets/** module writes a renderer-local (recentred ENU /
      body-fixed) coordinate straight into a persisted mission feature without converting back to the lunar CRS.

Run: PYTHONPATH=. .venv/bin/python -m pytest stewie/server/test_gw12_coordinate_contract.py -q
"""
from __future__ import annotations

import json
import math
import os
import re

import numpy as np
import pytest

from stewie.specs.sites import SITES
from stewie.terrain.site_dem import (
    dem_georef_corners,
    dem_origin_to_latlon,
    latlon_to_dem_origin,
)

# repo root from stewie/server/test_gw12_coordinate_contract.py -> server -> stewie -> <repo>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: the contract tolerance: a persisted coordinate must survive a render->pick->persist round-trip to < 1 cm.
_ROUND_TRIP_TOL_M = 0.01

#: (b) the documented float32 ulp budget. float32 carries a 23-bit fraction, so the spacing (ULP) at a
#: magnitude x in [2^e, 2^(e+1)) is 2^(e-23). Requiring 1 cm to stay representable -- ULP <= 0.01 m -- gives
#: 2^(e-23) <= 0.01, i.e. e <= 16, so any |coord| strictly below 2^17 = 131072 m has ULP <= 2^-7 = 7.8 mm < 1 cm.
#: The moment |coord| reaches 2^17, ULP jumps to 2^-6 = 15.6 mm > 1 cm. Hence the render-origin-relative extent
#: handed to a float32 render path must stay under this bound; the ~10 km tile extent does, with room to spare.
_FLOAT32_1CM_SAFE_BOUND_M = 2.0**17  # 131072.0 m


def _imported_sites():
    """The registry sites that carry a committed DEM bundle with a readable metadata.json (the transforms
    read ONLY metadata.json -- grid + world_bounds_m + the georeference frame -- so a meta-committed tile with
    no heightmap.rf32 is still a valid coordinate-contract subject)."""
    out = []
    for name, s in SITES.items():
        if not s.bundle_dir:
            continue
        meta_p = os.path.join(s.bundle_dir, "metadata.json")
        if os.path.exists(meta_p):
            out.append((name, s, json.load(open(meta_p))))
    return out


def _grid(meta):
    g = meta["grid"]
    return int(g["width"]), int(g["height"]), float(g["cell_m"])


def _round_trip_error_m(x, y, *, bundle_dir):
    """The render->pick->persist round-trip error [m] of an order-frame coordinate: project it to a
    selenographic lat/lon (dem_origin_to_latlon) then back to the order frame (latlon_to_dem_origin), and
    return the planar distance between the original and the recovered coordinate. Both real site_dem transforms
    are exercised; the recovered lat/lon is returned too so the projection can be shown non-vacuous."""
    lat, lon = dem_origin_to_latlon(x, y, bundle_dir=bundle_dir)
    x2, y2 = latlon_to_dem_origin(lat, lon, bundle_dir=bundle_dir)
    return math.hypot(x - x2, y - y2), (lat, lon)


# --- (a) round-trip < 1 cm on the curated polar-stereographic tiles ------------------------------------------
def test_persisted_coords_round_trip_under_1cm_curated_sites():
    """[REQ:GW-12] (a) A persisted order-frame coordinate round-trips through the site_dem transforms to < 1 cm
    at the theme-extent corners, the tile center, and the site anchor, on every committed curated tile.

    The persisted lattice is the DEM grid (latlon_to_dem_origin quantizes a lat/lon to the nearest pixel -- the
    authoritative 5 m resolution the tile actually stores), so the < 1 cm contract is asserted on the PERSISTED
    coordinates (pixel centers), which is exactly what a render surface reads and a pick writes back. The outer
    pixel EDGES (world_bounds_m corners, col/row = -0.5) fold to the boundary pixel by design; the addressable
    THEME EXTENT is the corner pixel centers, used here."""
    sites = _imported_sites()
    assert sites, "no committed DEM tiles found; the coordinate contract needs real site metadata"
    worst_mm = 0.0
    report = {}
    for name, s, meta in sites:
        W, H, cell = _grid(meta)
        # theme-extent corner pixel centers + tile center (all pixel-aligned = the persisted lattice)
        pts = {
            "corner_00": (0.0, 0.0),
            "corner_W0": ((W - 1) * cell, 0.0),
            "corner_0H": (0.0, (H - 1) * cell),
            "corner_WH": ((W - 1) * cell, (H - 1) * cell),
            "tile_center": ((W // 2) * cell, (H // 2) * cell),
        }
        # the imported-site ANCHOR: the registry center projected into its own tile (a real persisted anchor).
        try:
            ax, ay = latlon_to_dem_origin(s.lat_deg, s.lon_deg, bundle_dir=s.bundle_dir)
        except ValueError as e:  # a registry center must fall inside its own tile
            raise AssertionError(f"{name}: registry center ({s.lat_deg},{s.lon_deg}) is off its own tile: {e}")
        pts["anchor"] = (ax, ay)

        latlons = {}
        for key, (x, y) in pts.items():
            err, latlon = _round_trip_error_m(x, y, bundle_dir=s.bundle_dir)
            latlons[key] = latlon
            assert err < _ROUND_TRIP_TOL_M, f"{name}/{key}: round-trip {err*1000:.4f} mm >= 1 cm"
            worst_mm = max(worst_mm, err * 1000.0)
        report[name] = {k: round(v[0], 6) for k, v in latlons.items()}

        # NON-VACUITY: the transforms genuinely PROJECT (not an identity/stub). The tile center lat/lon must
        # sit inside the tile's georeferenced footprint, and the four corners must span a real ~10 km angular
        # extent (distinct lat/lon), so a zero round-trip reflects a true inverse, not two no-ops.
        gc = dem_georef_corners(bundle_dir=s.bundle_dir)
        c_lat, c_lon = latlons["tile_center"]
        corner_lats = [gc["corners"][i]["lat"] for i in range(4)]
        assert min(corner_lats) - 0.5 <= c_lat <= max(corner_lats) + 0.5, \
            f"{name}: tile-center lat {c_lat} outside the georef footprint {gc['center']}"
        span_lat = abs(latlons["corner_00"][0] - latlons["corner_WH"][0])
        span_lon = abs(latlons["corner_00"][1] - latlons["corner_WH"][1])
        assert span_lat > 1e-3 or span_lon > 1e-3, \
            f"{name}: corners collapsed to one lat/lon ({span_lat},{span_lon}) -- transform is a no-op"

    assert worst_mm < 10.0  # 1 cm, restated as mm for the reported worst case
    print(f"\n[GW-12a curated] worst round-trip = {worst_mm:.4f} mm over {len(sites)} tiles: "
          + ", ".join(sorted(n for n, _, _ in sites)))


# --- (a) round-trip < 1 cm on an AD-HOC local-AEQD tile (PLAN ANYWHERE) --------------------------------------
def test_persisted_coords_round_trip_under_1cm_adhoc_tile(tmp_path, monkeypatch):
    """[REQ:GW-12] (a) The same round-trip < 1 cm holds on an AD-HOC tile whose authoritative frame is a LOCAL
    azimuthal-equidistant CRS (not the shared polar-stereo one), proving the contract is CRS-agnostic: forward
    and inverse resolve the SAME per-tile frame (bundle_crs), so a curated polar tile and an ad-hoc local tile
    both round-trip exactly. REAL data: the crop comes from the on-host global LOLA LDEM; SKIPS loudly if that
    ~8.5 GB asset is absent (never a fabricated surface)."""
    from stewie.terrain import adhoc_dem as AH

    if not os.path.exists(AH.global_ldem_path()):
        pytest.skip(f"global LOLA LDEM absent at {AH.global_ldem_path()}; ad-hoc crop needs the real asset")

    monkeypatch.setenv("STEWIE_ADHOC_DEM_DIR", str(tmp_path / "adhoc_dem"))
    off_lat, off_lon = -86.0, -30.0  # off-site, near-pole (not any curated center); real crop of the global LDEM
    bundle = AH.resolve_adhoc_bundle(off_lat, off_lon)
    meta = json.load(open(os.path.join(bundle, "metadata.json")))
    assert meta["georeference"]["crs_kind"] == "local_aeqd"  # a DIFFERENT authoritative frame than the curated tiles
    W, H, cell = _grid(meta)

    pts = {
        "corner_00": (0.0, 0.0),
        "corner_WH": ((W - 1) * cell, (H - 1) * cell),
        "tile_center": ((W // 2) * cell, (H // 2) * cell),
    }
    worst_mm = 0.0
    center_latlon = None
    for key, (x, y) in pts.items():
        err, latlon = _round_trip_error_m(x, y, bundle_dir=bundle)
        assert err < _ROUND_TRIP_TOL_M, f"adhoc/{key}: round-trip {err*1000:.4f} mm >= 1 cm"
        worst_mm = max(worst_mm, err * 1000.0)
        if key == "tile_center":
            center_latlon = latlon
    # NON-VACUITY: the ad-hoc tile center projects back to ~the pick it was cropped around (a real transform).
    assert abs(center_latlon[0] - off_lat) < 0.2 and abs(center_latlon[1] - off_lon) < 0.2, \
        f"adhoc tile center {center_latlon} not near the pick ({off_lat},{off_lon})"
    assert worst_mm < 10.0
    print(f"\n[GW-12a adhoc] worst round-trip = {worst_mm:.4f} mm on a {W}x{H}@{cell:.1f} m local-AEQD tile; "
          f"center {center_latlon} ~ pick ({off_lat},{off_lon})")


# --- (b) the render-origin-relative extent is float32 1 cm-safe ----------------------------------------------
def test_render_origin_relative_extent_is_float32_1cm_safe():
    """[REQ:GW-12] (b) The largest coordinate magnitude a render surface hands to a float32 path -- the tile's
    render-origin-relative extent (order frame [0, tile_m] plus the true relief) -- stays under the documented
    ulp budget, so 1 cm is representable in single precision. Every render surface recentres to a local origin
    (cockpit: the site origin; /ide frame.js: the tile origin via worldFromBody), so the magnitude is the tile
    extent, NOT the ~1.74e6 m body-fixed radius. Measured on real committed tile metadata."""
    sites = _imported_sites()
    assert sites
    worst_mag = 0.0
    for name, _s, meta in sites:
        W, H, cell = _grid(meta)
        hr = meta.get("height_range_m", [0.0, 0.0])
        relief = float(hr[1]) - float(hr[0])
        tile_x, tile_y = W * cell, H * cell
        # worst render-origin-relative magnitude: the far tile corner (origin at a tile corner, as frame.js
        # _buildRef recentres to x0,y0) plus the full vertical relief -- a conservative upper bound.
        mag = math.sqrt(tile_x**2 + tile_y**2 + relief**2)
        worst_mag = max(worst_mag, mag)

        # the ACTUAL float32 spacing at this magnitude must be < 1 cm ...
        ulp = float(np.spacing(np.float32(mag)))
        assert ulp < _ROUND_TRIP_TOL_M, f"{name}: float32 ULP at {mag:.0f} m is {ulp*1000:.4f} mm >= 1 cm"
        # ... and the magnitude must sit under the documented 1 cm-safe bound.
        assert mag < _FLOAT32_1CM_SAFE_BOUND_M, \
            f"{name}: render extent {mag:.0f} m >= float32 1cm-safe bound {_FLOAT32_1CM_SAFE_BOUND_M:.0f} m"

    # pin the documented bound itself: 1 cm is representable just below 2^17 and NOT at it (the budget's edge).
    assert float(np.spacing(np.float32(_FLOAT32_1CM_SAFE_BOUND_M * 0.999))) <= _ROUND_TRIP_TOL_M
    assert float(np.spacing(np.float32(_FLOAT32_1CM_SAFE_BOUND_M))) > _ROUND_TRIP_TOL_M
    margin = _FLOAT32_1CM_SAFE_BOUND_M / worst_mag
    assert margin > 2.0, f"float32 headroom {margin:.2f}x is thin; a render origin closer to the work area is needed"
    print(f"\n[GW-12b] worst render extent = {worst_mag:.0f} m; float32 ULP there = "
          f"{np.spacing(np.float32(worst_mag))*1000:.4f} mm < 1 cm; bound = {_FLOAT32_1CM_SAFE_BOUND_M:.0f} m "
          f"(margin {margin:.2f}x)")


# --- (c) grep/AST guard: no renderer-local coordinate is persisted straight into a mission feature -----------
# a RENDER-ORIGIN OUTPUT is renderer-local (the recentred ENU / body-fixed-sphere coordinate the /ide 3D frame
# produces) -- distinct from the persisted ORDER FRAME (site-origin metres). These four tokens appear ONLY on
# that render path (frame.js), never in the order-frame serializer.
_RENDER_LOCAL_SRC = re.compile(r"\bworldFromBody\s*\(|\bbodyFixed\w*\s*\(|\bmakeFrame\s*\(|\bSTEWIEFrame\b")
# a PERSISTENCE SINK: a POST that writes a mission feature (order / marker / keep-out / structure) to the backend.
_PERSIST_SINK = re.compile(
    r"/api/plan\b|/api/edit/session/[^\"']*?(?:marker|keepout)|/api/structure\b|['\"]/plan['\"]")
# the sanctioned bridges back to an authoritative frame: reproject to the map/geo CRS, or frame.js metresToLonLat.
_CRS_BRIDGE = re.compile(r"\bmetresToLonLat\s*\(|\breproject\s*\(")

_GUARD_ROOTS = ("gis/qwc2/js", os.path.join("stewie", "server", "web", "assets"))


def _guarded_js_files():
    out = []
    for rel in _GUARD_ROOTS:
        base = os.path.join(_REPO_ROOT, rel)
        for dp, _dirs, files in os.walk(base):
            if "node_modules" in dp:
                continue
            for f in files:
                if f.endswith(".test.js"):
                    continue
                if f.endswith((".js", ".jsx", ".ts")):
                    out.append(os.path.join(dp, f))
    return out


def _classify(text):
    return (bool(_RENDER_LOCAL_SRC.search(text)),
            bool(_PERSIST_SINK.search(text)),
            bool(_CRS_BRIDGE.search(text)))


def test_no_module_persists_renderer_local_coordinate():
    """[REQ:GW-12] (c) No gis/qwc2/js/** or web/assets/** module writes a renderer-local coordinate straight
    into a persisted mission feature. A VIOLATION is a module that BOTH produces a render-origin coordinate
    (worldFromBody / bodyFixed / makeFrame / STEWIEFrame) AND persists a mission feature (POST /api/plan,
    /api/edit .../marker|keepout, /api/structure) WITHOUT a CRS bridge (metresToLonLat / reproject) between
    them. Also pins, positively, that the ONE shared serializer consumes MAP-CRS coordinates and the 3D-pick
    bridges reproject a lon/lat pick to the map CRS before it becomes an order."""
    files = _guarded_js_files()
    assert files, "guard found no JS modules to scan -- the roots moved"

    producers, sinks, violations = [], [], []
    for p in files:
        text = open(p, encoding="utf-8", errors="replace").read()
        is_render, is_persist, has_bridge = _classify(text)
        rel = os.path.relpath(p, _REPO_ROOT)
        if is_render:
            producers.append(rel)
        if is_persist:
            sinks.append(rel)
        if is_render and is_persist and not has_bridge:
            violations.append(rel)
    assert not violations, ("renderer-local coordinate persisted without a CRS bridge (GW-12 contract broken): "
                            + ", ".join(violations))

    # the guard is only meaningful if BOTH sides of the contract are actually present in the tree.
    assert producers, "no render-origin producer found -- the /ide 3D frame path is missing (guard is vacuous)"
    assert sinks, "no persistence sink found -- the mission-feature POST path is missing (guard is vacuous)"

    # NON-VACUITY: the detector DOES fire on a module that persists a render-origin coordinate with no bridge,
    # and does NOT fire once a metresToLonLat bridge is inserted (a real edit would trip this).
    bad = "const p = frame.worldFromBody(bf);\nfetch('/api/plan',{method:'POST',body:JSON.stringify({orders:[{x:p.x,y:p.y}]})});"
    good = ("const p = frame.worldFromBody(bf);\nconst ll = frame.metresToLonLat(e,n);\n"
            "fetch('/api/plan',{method:'POST',body:JSON.stringify({orders:[{lon:ll.lon,lat:ll.lat}]})});")
    br, bp, bb = _classify(bad)
    gr, gp, gbdg = _classify(good)
    assert br and bp and not bb, "guard would NOT catch a raw render-origin persist -- it is vacuous"
    # the SAME producer+persister, once a CRS bridge is inserted, is no longer a violation (the fix works).
    assert gr and gp and gbdg and not (gr and gp and not gbdg), "guard does not clear a bridged persist"

    # POSITIVE pin: the shared /api/plan + marker serializers consume a MAP-CRS coordinate (order.coord in
    # IAU_2015:30135), never a render-origin one -- so every persisted order/marker starts authoritative.
    pt = open(os.path.join(_REPO_ROOT, "gis/qwc2/js/mission/planTools.js"), encoding="utf-8").read()
    ofe = re.search(r"function orderFrameEntry\(.*?\n    \}", pt, re.S).group(0)
    mb = re.search(r"function markerBody\(.*?\n    \}", pt, re.S).group(0)
    assert "order.coord[0] - wc[0]" in ofe and "wc[1] - order.coord[1]" in ofe, \
        "orderFrameEntry no longer derives x/y from the map-CRS order.coord anchored to wc"
    assert "coord[0]" in mb and "coord[1]" in mb, "markerBody no longer derives x/y from the map-CRS coord"

    # POSITIVE pin: the 3D-terrain pick bridges (plotDispatch / adoptRoute) reproject a lon/lat pick to the map
    # CRS BEFORE it becomes an order -- the render surface hands back lon/lat, not its renderer-local frame.
    pd = re.search(r"function plotDispatch\(.*?\n    \}", pt, re.S).group(0)
    ar = re.search(r"function adoptRoute\(.*?\n    \}", pt, re.S).group(0)
    assert "reproject([pt.lon, pt.lat], geoCrs, mapCrs)" in pd, "plotDispatch no longer reprojects the 3D pick to map CRS"
    assert "reproject([q.lon, q.lat], geoCrs, mapCrs)" in ar, "adoptRoute no longer reprojects the 3D route to map CRS"

    # POSITIVE pin: the /ide render frame's only escape back to authoritative space is metresToLonLat, and it
    # never itself persists a feature.
    fj = open(os.path.join(_REPO_ROOT, "stewie/server/web/assets/viz3d/frame.js"), encoding="utf-8").read()
    assert "metresToLonLat:" in fj and not _PERSIST_SINK.search(fj), \
        "frame.js either lost its metresToLonLat escape hatch or started persisting a feature"

    print(f"\n[GW-12c] guard clean: {len(producers)} render-origin producer(s) {producers}, "
          f"{len(sinks)} persist sink(s); 0 renderer-local persists")
