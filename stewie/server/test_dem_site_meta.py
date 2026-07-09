"""viz3d geospatial upgrade (design §5): /dem/site_meta returns the tile's REAL georeference metadata so
the browser frame manager (viz3d/frame.js) can place the DEM on the body-fixed globe + build its coarse
metres->lonlat grid WITHOUT re-deriving the 30135 CRS transform client-side (the #1 offset trap).

Every asserted value is the REAL committed Haworth bundle metadata (samples/lunar_dem/haworth_10km_5m/
metadata.json + the pyproj reproject) -- nothing fabricated. The route is require_auth-gated like the other
/dem transform routes; the suite runs keyless dev-open (conftest), so the TestClient reaches it.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest
from fastapi.testclient import TestClient

from stewie.server.server import app
from stewie.terrain.site_dem import bundle_for_site

client = TestClient(app)

_HAS_PYPROJ = importlib.util.find_spec("pyproj") is not None


def _real_haworth_metadata() -> dict:
    """The ground truth: the committed Haworth bundle's own metadata.json (not a copy of the route's output)."""
    with open(os.path.join(bundle_for_site("haworth"), "metadata.json")) as f:
        return json.load(f)


def test_site_meta_returns_real_crs_pixel_and_bounds_for_haworth():
    m = _real_haworth_metadata()
    r = client.get("/dem/site_meta?site=haworth")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["site"] == "haworth"
    # CRS: the south-polar stereographic frame the whole pipeline reprojects through.
    assert j["crs"] == "IAU_2015:30135"
    # pixel size + grid dims come straight from metadata.grid (real: 5 m, 2000 x 2000).
    assert j["pixel_size_m"] == float(m["grid"]["cell_m"]) == 5.0
    assert j["width"] == int(m["grid"]["width"]) == 2000
    assert j["height"] == int(m["grid"]["height"]) == 2000
    # projected bounds == metadata.world_bounds_m exactly (the REAL non-zero tile offsets).
    assert j["bounds_m"] == {"x0": m["world_bounds_m"]["x0"], "y0": m["world_bounds_m"]["y0"],
                             "x1": m["world_bounds_m"]["x1"], "y1": m["world_bounds_m"]["y1"]}
    assert j["bounds_m"]["x0"] == -52900.0 and j["bounds_m"]["y1"] == 105400.0
    # order-frame native extent = (dim-1)*cell -> the [0, tile_m] span the viewer's coarse grid covers.
    assert j["tile_m"]["x"] == (2000 - 1) * 5.0 == 9995.0
    assert j["tile_m"]["y"] == 9995.0


def test_site_meta_nodata_is_the_served_heightfield_convention():
    """dart.dem_import converts the source GDAL_NODATA sentinel to float NaN on ingest, so the served
    /dem/heightfield_full stream carries NaN for a nodata cell. The bundle records no explicit sentinel,
    so site_meta reports that convention ('NaN') -- the value the viewer masks with Number.isNaN, not a
    fabricated number."""
    m = _real_haworth_metadata()
    assert "nodata" not in m                                  # the real bundle carries no explicit sentinel
    j = client.get("/dem/site_meta?site=haworth").json()
    assert j["nodata"] == "NaN"


def test_site_meta_vertical_datum_is_the_moon_me_sphere():
    m = _real_haworth_metadata()
    j = client.get("/dem/site_meta?site=haworth").json()
    vd = j["vertical_datum"]
    assert vd["name"] == "MOON_ME"
    # sphere radius == the REAL dem_provenance value (1737400 m, the IAU_2015:30135 MOON_ME sphere).
    assert vd["sphere_radius_m"] == float(m["dem_provenance"]["sphere_radius_m"]) == 1737400.0
    assert vd["z_semantics"] == m["dem_provenance"]["z_semantics"]
    assert "height above sphere" in vd["z_semantics"]


@pytest.mark.skipif(not _HAS_PYPROJ, reason="pyproj ([planner] extra) absent")
def test_site_meta_origin_lonlat_matches_the_reproject():
    """origin_lonlat is the selenographic lon/lat of the order-frame origin (0,0) via the SAME reproject
    the hover/plot readout uses (dem_origin_to_latlon) -- so the frame's globe placement registers with
    the server transform, not a client re-derivation."""
    from stewie.terrain.site_dem import dem_origin_to_latlon
    lat0, lon0 = dem_origin_to_latlon(0.0, 0.0, bundle_dir=bundle_for_site("haworth"))
    j = client.get("/dem/site_meta?site=haworth").json()
    assert j["origin_lonlat"] is not None
    assert j["origin_lonlat"]["lon"] == round(lon0, 6) == -26.651421
    assert j["origin_lonlat"]["lat"] == round(lat0, 6) == -86.112509


def test_site_meta_is_site_specific_across_bundled_tiles():
    """Each real bundled tile returns its OWN bounds + origin lon/lat (the meta follows the selected site,
    not always Haworth) -- the REG-01 site-aware contract the other /dem routes hold."""
    bounds, origins = {}, {}
    for site in ("haworth", "shackleton_rim", "nobile_rim"):
        j = client.get(f"/dem/site_meta?site={site}").json()
        assert j["ok"] and j["site"] == site
        bounds[site] = tuple(sorted(j["bounds_m"].items()))
        if j["origin_lonlat"] is not None:
            origins[site] = (round(j["origin_lonlat"]["lon"], 3), round(j["origin_lonlat"]["lat"], 3))
    assert len(set(bounds.values())) == 3, f"bounds not distinct per site: {bounds}"
    if origins:
        assert len(set(origins.values())) == len(origins), f"origins not distinct per site: {origins}"


def test_site_meta_unknown_site_404():
    assert client.get("/dem/site_meta?site=not_a_real_site").status_code == 404
    # a path-traversal ?site= is rejected by the SITES registry validation (never touches the FS), like
    # the other site-aware /dem routes.
    assert client.get("/dem/site_meta?site=../../etc/passwd").status_code == 404


def test_site_meta_declared_before_param_route():
    """/dem/site_meta must resolve as the literal compute route, not be captured by /dem/{name} as a
    preview named 'site_meta' (which would 404). A 200 here proves the declaration order holds."""
    assert client.get("/dem/site_meta?site=haworth").status_code == 200
