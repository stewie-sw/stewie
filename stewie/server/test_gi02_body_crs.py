"""[REQ:GI-02] Planetary map correctness: body-correct ellipsoid/CRS metadata + honest
terrain-vs-imagery layer labeling.

Asserts that the Moon/Mars body records carry the correct reference-ellipsoid radius and
planetary CRS (Moon ~1737.4 km / IAU_2015:30100, Mars ~3396.19 km / IAU_2015:49900), that
every map layer claiming 3D terrain resolves to a REAL on-disk DEM source (the LOLA Haworth
tile, not a smooth WGS84 drape), and that the smooth orbital-imagery drape is flagged
imagery_only. Sources: docs/bodies_sysrev.md; samples/lunar_dem/.../metadata.json
(sphere_radius_m 1737400, IAU_2015:30135); lode/gis_export.py (IAU_2015:30100 Moon geographic).
"""
from __future__ import annotations

import json
import os

import pytest

from stewie.server import map_layers as ML
from stewie.specs import bodies as B

# IAU 2015 reference values (also pinned in samples/.../metadata.json + lode/gis_export.py).
MOON_RADIUS_M = 1737400.0     # IAU mean sphere; == metadata.json dem_provenance.sphere_radius_m
MARS_RADIUS_M = 3396190.0     # IAU 2015 Mars equatorial (semi-major) radius


def test_moon_record_has_body_correct_ellipsoid_and_crs():
    """[REQ:GI-02] Moon carries the ~1737.4 km ellipsoid radius + its planetary CRS."""
    moon = B.BODIES["moon"]
    assert moon.ellipsoid_radius_m == pytest.approx(MOON_RADIUS_M)
    assert moon.crs == "IAU_2015:30100"


def test_mars_record_has_body_correct_ellipsoid_and_crs():
    """[REQ:GI-02] Mars carries the ~3396.19 km ellipsoid radius + its planetary CRS
    (NOT the Moon radius, NOT Earth WGS84)."""
    mars = B.BODIES["mars"]
    assert mars.ellipsoid_radius_m == pytest.approx(MARS_RADIUS_M)
    assert mars.crs == "IAU_2015:49900"
    # bodies are distinct: Mars must not silently inherit the Moon ellipsoid.
    assert mars.ellipsoid_radius_m != B.BODIES["moon"].ellipsoid_radius_m


def test_bodies_json_exports_ellipsoid_and_crs():
    """[REQ:GI-02] The served bodies.json (single source of truth for the browser globe) carries
    the same ellipsoid/CRS the registry does -- so the cockpit renders a body-correct globe."""
    path = os.path.join(os.path.dirname(ML.__file__), "bodies.json")
    with open(path) as f:
        data = json.load(f)
    for key, radius, crs in (("moon", MOON_RADIUS_M, "IAU_2015:30100"),
                             ("mars", MARS_RADIUS_M, "IAU_2015:49900")):
        assert data[key]["ellipsoid_radius_m"] == pytest.approx(radius)
        assert data[key]["crs"] == crs


def test_terrain_layers_resolve_to_a_real_dem_source():
    """[REQ:GI-02] Every layer claiming 3D terrain (group=='terrain') names a dem_source that
    resolves to a REAL on-disk DEM bundle -- not a fabricated or smooth drape."""
    defs = ML.layer_defs()
    terrain = [d for d in defs if d["group"] == "terrain"]
    assert {d["id"] for d in terrain} == {"dem", "topology"}      # the terrain rasters
    for d in terrain:
        assert d.get("dem_source"), d["id"]
        dem_dir = ML.dem_source_dir(d["dem_source"])
        assert os.path.isfile(os.path.join(dem_dir, "metadata.json")), dem_dir
        assert os.path.isfile(os.path.join(dem_dir, "heightmap.rf32")), dem_dir


def test_terrain_dem_is_the_real_lola_tile_matching_moon_ellipsoid():
    """[REQ:GI-02] The terrain DEM is the real LOLA south-polar tile: its metadata sphere radius
    equals the Moon body ellipsoid radius (ties the layer's 3D-terrain claim to real elevation)."""
    dem_dir = ML.dem_source_dir()
    with open(os.path.join(dem_dir, "metadata.json")) as f:
        meta = json.load(f)
    assert meta["dem_provenance"]["sphere_radius_m"] == pytest.approx(B.BODIES["moon"].ellipsoid_radius_m)
    lo, hi = meta["height_range_m"]                              # real relief, not a flat/smooth drape
    assert hi - lo > 100.0


def test_imagery_drape_is_flagged_imagery_only():
    """[REQ:GI-02] The smooth orbital-imagery base drape is labeled imagery_only (imagery, NOT
    3D terrain); the terrain rasters are NOT imagery_only and carry no DEM-less imagery flag."""
    defs = ML.layer_defs()
    by_id = {d["id"]: d for d in defs}
    assert by_id["imagery"].get("imagery_only") is True
    assert by_id["imagery"].get("dem_source") is None            # a drape has no DEM
    for lid in ("dem", "topology"):                              # terrain is the opposite of a drape
        assert by_id[lid].get("imagery_only") is not True
