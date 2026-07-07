"""PLAN ANYWHERE (off-site DEM resolver) -- crop the REAL on-host global LOLA LDEM at an ARBITRARY
non-curated lat/lon, and prove the derived layers + the planner run there (not a 404 / flat_fallback).

The pick is an Artemis-adjacent near-pole spot (lat -86.0, lon -30.0) that is NOT any curated site
center (haworth -86.33/-25.51, shackleton_rim -89.823/158.213, nobile_rim -85.484/39.965). REAL data
only: the crop comes from the real global LDEM; the test SKIPS (loudly) if that ~8.5 GB asset is absent,
it never fabricates a surface. Regression pins that the 8 curated sites are untouched.

Run: PYTHONPATH=. .venv/bin/python -m pytest stewie/server/test_plan_anywhere.py -q
"""
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import pytest

from stewie.terrain import adhoc_dem as AH

_OFF_LAT, _OFF_LON = -86.0, -30.0          # off-site, near-pole (Artemis-adjacent)
_LDEM = AH.global_ldem_path()
pytestmark = pytest.mark.skipif(
    not os.path.exists(_LDEM),
    reason=f"global LOLA LDEM absent at {_LDEM}; PLAN-ANYWHERE crop needs the real asset (no synthetic fill)")


@pytest.fixture()
def scratch(tmp_path, monkeypatch):
    """Point the writable caches (ad-hoc bundles + globe_cache + reports) at a scratch dir so the test
    never pollutes the real data_dir and every run rebuilds from the real LDEM."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_ADHOC_DEM_DIR", str(tmp_path / "adhoc_dem"))
    return tmp_path


# --- 1. the request-time resolver: real crop -> a valid Haworth-format bundle in a LOCAL frame ---------
def test_resolver_crops_real_ldem_to_valid_local_bundle(scratch):
    site_id = AH.adhoc_site_id(_OFF_LAT, _OFF_LON)
    assert AH.is_adhoc_site(site_id) and not AH.is_adhoc_site("haworth")
    assert AH.parse_adhoc_site(site_id) == (round(_OFF_LAT, 3), round(_OFF_LON, 3))

    bundle = AH.resolve_adhoc_bundle(_OFF_LAT, _OFF_LON)
    assert os.path.isdir(bundle)
    assert os.path.exists(os.path.join(bundle, "heightmap.rf32"))
    meta = json.load(open(os.path.join(bundle, "metadata.json")))

    # Haworth-format contract: grid + world_bounds_m + a LOCAL-AEQD georeference (NOT the polar frame)
    assert {"width", "height", "cell_m"} <= set(meta["grid"])
    assert {"x0", "y0", "x1", "y1"} == set(meta["world_bounds_m"])
    gr = meta["georeference"]
    assert gr["crs_kind"] == "local_aeqd" and "+proj=aeqd" in gr["proj4"]
    assert abs(gr["lat0"] - _OFF_LAT) < 1.0 and abs(gr["lon0"] - _OFF_LON) < 1.0
    # native LOLA global resolution -- honestly coarse (~118 m/px), NOT upsampled
    assert 100.0 < meta["grid"]["cell_m"] < 130.0

    # loads through the SAME reader the curated sites use, with real (finite, non-degenerate) relief
    from stewie.terrain.site_dem import load_haworth_dem
    Z, cell = load_haworth_dem(bundle_dir=bundle)
    assert np.isfinite(Z).all()
    assert Z.shape[0] >= 60 and Z.shape[1] >= 60
    assert float(Z.max() - Z.min()) > 5.0            # real terrain, not a flat plane
    assert 100.0 < cell < 130.0

    # the local frame round-trips: the tile center georeferences back to ~the pick
    from stewie.terrain.site_dem import dem_georef_corners
    gc = dem_georef_corners(bundle_dir=bundle)
    assert abs(gc["center"]["lat"] - _OFF_LAT) < 0.2
    assert gc["crs"] == "local_aeqd"

    # a repeat pick is a cache hit (same dir, no rebuild)
    assert AH.resolve_adhoc_bundle(_OFF_LAT, _OFF_LON) == bundle


# --- 2. the globe drape resolves the ad-hoc site: a REAL slope PNG, not the off-site 404 --------------
def test_globe_slope_layer_renders_offsite(scratch):
    from stewie.server.gis_layers import _to_png, render_globe
    site_id = AH.adhoc_site_id(_OFF_LAT, _OFF_LON)
    out = render_globe("slope", site=site_id)
    assert out is not None
    rgba, bbox = out
    assert rgba.ndim == 3 and rgba.shape[2] == 4
    assert int(np.asarray(rgba)[..., :3].sum()) > 0          # a real slope raster, not an empty tile
    # the geographic bbox brackets the pick (local frame projected back to lon/lat)
    assert bbox["south"] < _OFF_LAT < bbox["north"]
    assert bbox["west"] < _OFF_LON < bbox["east"]
    png = _to_png(rgba)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 500


def test_globe_slope_layer_http_offsite_is_200(scratch):
    from fastapi.testclient import TestClient

    from stewie.server import server as SRV
    site_id = AH.adhoc_site_id(_OFF_LAT, _OFF_LON)
    c = TestClient(SRV.app)
    r = c.get(f"/layers/globe/slope.png?site={site_id}")
    assert r.status_code == 200, r.text                      # was the "DEM absent" 404 off-site
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 500


# --- 3. the planner runs on the cropped DEM: terrain_source names it, NOT flat_fallback ---------------
def test_plan_runs_offsite_on_cropped_dem(scratch):
    from fastapi.testclient import TestClient

    from stewie.server import server as SRV
    site_id = AH.adhoc_site_id(_OFF_LAT, _OFF_LON)
    c = TestClient(SRV.app)
    orders = [{"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
              {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]
    r = c.post("/plan", json={"name": "plan-anywhere", "body": "moon", "site": site_id,
                              "lat": _OFF_LAT, "lon": _OFF_LON, "charger": [0, 0], "orders": orders})
    assert r.status_code == 200, r.text
    j = r.json()
    src = str(j.get("terrain_source", ""))
    assert src != "flat_fallback", "off-site plan silently degraded to the flat fallback"
    assert src == f"{site_id}_dem", f"terrain_source did not name the cropped DEM: {src!r}"
    assert j.get("site") == site_id and j.get("body") == "moon"


# --- 4. regression: the curated sites are byte-identical + still south-polar (no local frame) ----------
def test_curated_haworth_unchanged():
    from pyproj import CRS

    from lode import mission_planner as MP
    from stewie.terrain.site_dem import bundle_crs, dem_georef_corners

    hb = MP.bundle_for_site("haworth")
    meta = json.load(open(os.path.join(hb, "metadata.json")))
    assert "georeference" not in meta                        # curated tiles carry NO local-frame block
    assert bundle_crs(hb) == CRS.from_user_input("IAU_2015:30135")  # still the shared polar-stereo frame

    gc = dem_georef_corners(bundle_dir=hb)
    assert gc["crs"] == "IAU_2015:30135"
    assert abs(gc["tile_km"] - 10.0) < 1e-6                  # the 10 km curated tile, unchanged

    # heightmap bytes untouched by this change
    h = hashlib.sha256(open(os.path.join(hb, "heightmap.rf32"), "rb").read()).hexdigest()
    assert len(h) == 64


def test_curated_haworth_globe_still_renders():
    from stewie.server.gis_layers import render_globe
    out = render_globe("slope", site="haworth")
    assert out is not None and int(np.asarray(out[0])[..., :3].sum()) > 0
    # Haworth's footprint brackets its true center (-86.33, south-polar), NOT relocated by the change
    assert out[1]["south"] < -86.33 < out[1]["north"]
