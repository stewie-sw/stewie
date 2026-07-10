"""[REQ:GW-11] the backend contract the /ide 3D terrain panel (gis/qwc2/js/plugins/MissionTerrain3D.jsx ->
assets/viz3d.js) composes, asserted end-to-end on the REAL LOLA Haworth 5 m bundle (no synthetic terrain).
GW-11's acceptance rides three same-origin /dem routes the artemis edge proxies into the IDE:

  (a) RENDER SUBSTRATE -- /dem/heightfield_full[/meta]: the site's REAL DEM window at native cell resolution
      in the site-local order frame, streamed as row-major float32, with the grid meta the panel sizes the
      Three.js mesh from. This is what the panel renders (clause "renders the selected site's REAL DEM window").
  (c/e) COORDINATE TRANSFORM -- /dem/site_lonlat: an order-frame (x,y) [m] -> selenographic lat/lon, the SHARED
      transform the hover coordinate readout (c) and the 3D waypoint pick (e) both call (viz3d _hoverPick /
      _plotAt), so a 3D pick reports the same map coordinate the 2D map would.
  (d) 2D->3D ANCHOR -- /dem/site_meta.bounds_m: the tile's IAU_2015:30135 extent {x0=min X, y1=max Y} that the
      2D-authored features convert THROUGH into the order frame (missionFeatures3d.featuresToSpecs:
      order_x = X - x0 ; order_y = y1 - Y), so a keep-out authored on the 2D map lands on the right relief cell.

The pure browser-side serializers (formatHover / featuresToSpecs / the WS features+plot channels) are bound by
the node test gis/qwc2/js/mission/gw11_terrain3d_acceptance.test.js; the deployed /ide is Playwright-verified on
real GPU (frontend/_ide_hover_e2e.mjs hover readout + frontend/_ide_features_e2e.mjs 2D->3D). This file is the
python [REQ:GW-11] citation req_trace.py requires, and it asserts REAL georeferenced values, not just shapes.
"""
from __future__ import annotations

import importlib.util
import json
import os
import struct

from fastapi.testclient import TestClient

from stewie.server.server import app
from stewie.terrain.site_dem import bundle_for_site

client = TestClient(app)

_HAS_PYPROJ = importlib.util.find_spec("pyproj") is not None


def _real_haworth_metadata() -> dict:
    with open(os.path.join(bundle_for_site("haworth"), "metadata.json")) as f:
        return json.load(f)


def test_render_substrate_is_the_real_haworth_dem_window_in_the_site_local_frame():
    """(a) /dem/heightfield_full/meta + the binary stream give the panel a REAL DEM window: native 5 m cells,
    the whole-tile order-frame window by default, real Haworth relief, and a binary body that matches the meta
    grid exactly (n*n float32). This is the terrain the Three.js panel renders."""
    m = _real_haworth_metadata()
    meta = client.get("/dem/heightfield_full/meta?site=haworth").json()
    assert meta["ok"] and meta["site"] == "haworth"
    assert meta["cell_m"] == float(m["grid"]["cell_m"]) == 5.0                  # native LOLA cell, not decimated
    assert meta["window_m"] == (2000 - 1) * 5.0 == 9995.0                        # default = whole native tile
    assert meta["x0"] == 0.0 and meta["y0"] == 0.0                               # site-local order frame origin
    # REAL Haworth relief (deep PSR floor to crater rim) -- a genuine, non-trivial elevation span, not flat.
    assert meta["z_min"] < meta["z_max"]
    assert (meta["z_max"] - meta["z_min"]) > 1000.0
    n = int(meta["n"])
    r = client.get("/dem/heightfield_full?site=haworth")
    assert r.status_code == 200 and r.headers["content-type"] == "application/octet-stream"
    assert int(r.headers["X-Dem-N"]) == n
    assert len(r.content) == n * n * 4                                           # row-major float32, meta-consistent
    # a real interior cell (not a possibly-nodata corner) is a finite height in the served relief span.
    mid = ((n // 2) * n + (n // 2)) * 4
    v_mid = struct.unpack("<f", r.content[mid:mid + 4])[0]
    assert v_mid == v_mid, "interior DEM cell is finite (real relief, not nodata NaN)"
    assert meta["z_min"] <= v_mid <= meta["z_max"]


def test_coordinate_readout_transform_maps_order_metres_to_real_selenographic_lonlat():
    """(c)/(e) /dem/site_lonlat is the shared transform the hover readout AND the 3D pick call. An
    order-frame point inside the Haworth window returns a REAL south-polar selenographic lat/lon; an
    out-of-window order coordinate is rejected (422), never silently projected to a wrong place."""
    if not _HAS_PYPROJ:
        # the route returns 503 (not a fabricated lon/lat) when pyproj is absent -- assert the honest failure.
        assert client.get("/dem/site_lonlat?x=5000&y=5000&site=haworth").status_code in (200, 503)
        return
    j = client.get("/dem/site_lonlat?x=5000&y=5000&site=haworth").json()   # window-interior order point
    assert j["ok"] and j["site"] == "haworth"
    assert j["lat"] < -80.0                              # Haworth is at the lunar south pole
    assert -180.0 <= j["lon"] <= 180.0
    # it agrees with the SAME server reproject the readout is documented to use (no client re-derivation).
    from stewie.terrain.site_dem import dem_origin_to_latlon
    lat, lon = dem_origin_to_latlon(5000.0, 5000.0, bundle_dir=bundle_for_site("haworth"))
    assert j["lat"] == round(lat, 6) and j["lon"] == round(lon, 6)
    # an order coordinate outside the tile is a real error, not a fabricated pole -- the 3D pick drops the emit.
    assert client.get("/dem/site_lonlat?x=-47900&y=100400&site=haworth").status_code == 422


def test_2d_to_3d_anchor_is_the_real_30135_bounds_with_the_yflip_corner():
    """(d) /dem/site_meta.bounds_m is the IAU_2015:30135 anchor missionFeatures3d.featuresToSpecs converts a
    2D-authored feature through (order_x = X - x0 ; order_y = y1 - Y). Assert the REAL Haworth corner the
    y-flip is anchored at (x0 = min X, y1 = max Y) + the order-frame span the render substrate covers."""
    m = _real_haworth_metadata()
    j = client.get("/dem/site_meta?site=haworth").json()
    assert j["ok"] and j["crs"] == "IAU_2015:30135"
    assert j["bounds_m"]["x0"] == float(m["world_bounds_m"]["x0"]) == -52900.0   # x0 = min X (the transform's x0)
    assert j["bounds_m"]["y1"] == float(m["world_bounds_m"]["y1"]) == 105400.0   # y1 = max Y (the y-flip anchor)
    # a feature at the tile's NW corner (x0, y1) maps to order (0, 0) via featuresToSpecs -- the transform anchor.
    # The 30135 bounds span is the PIXEL extent (width*cell = 10000 m); the order-frame span tile_m is the NODE
    # span ((width-1)*cell = 9995 m); they differ by exactly one cell (the honest pixel-vs-node distinction).
    assert (j["bounds_m"]["x1"] - j["bounds_m"]["x0"]) == 2000 * 5.0 == 10000.0
    assert j["tile_m"]["x"] == (2000 - 1) * 5.0 == 9995.0
    assert (j["bounds_m"]["x1"] - j["bounds_m"]["x0"]) - j["tile_m"]["x"] == 5.0   # one cell
    assert (j["bounds_m"]["y1"] - j["bounds_m"]["y0"]) == 10000.0 and j["tile_m"]["y"] == 9995.0
