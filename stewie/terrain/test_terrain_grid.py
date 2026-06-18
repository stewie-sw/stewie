"""dem_terrain_grid (REG-01 globe 3D layer): an n x n decimation of a site's REAL LOLA DEM, each node
georeferenced to selenographic lat/lon (IAU_2015:30135) via ONE vectorized inverse projection, for draping
the work-area terrain as a 3D mesh layer on the Cesium globe. Real bundles only (no synthetic DEM)."""
import time

import pytest

from stewie.terrain.site_dem import bundle_for_site, dem_terrain_grid

pytest.importorskip("pyproj")   # the georef needs the [planner] extra; skip cleanly where absent


def test_real_dem_shape_relief_and_vectorized_speed():
    b = bundle_for_site("haworth")
    t = time.time()
    g = dem_terrain_grid(n=48, bundle_dir=b)
    dt = time.time() - t
    n = g["n"]
    assert n == 48
    assert len(g["z"]) == n * n == len(g["lat"]) == len(g["lon"])
    assert g["z_min"] < g["z_max"]        # real relief, not a flat plane
    # per-node reprojection of 48*48 nodes would be ~4 s (~1.8 ms/call); the vectorized path is ~one call
    assert dt < 2.0, f"too slow ({dt:.2f}s) -- reprojection not vectorized?"


def test_georef_lands_in_the_south_polar_tile():
    g = dem_terrain_grid(n=16, bundle_dir=bundle_for_site("haworth"))
    assert all(lat < -80.0 for lat in g["lat"])          # Haworth is a south-pole site
    assert all(-180.0 <= lon <= 180.0 for lon in g["lon"])


def test_distinct_sites_have_distinct_centers():
    h = dem_terrain_grid(n=12, bundle_dir=bundle_for_site("haworth"))
    s = dem_terrain_grid(n=12, bundle_dir=bundle_for_site("shackleton_rim"))
    mid = len(h["lat"]) // 2
    assert (h["lat"][mid], h["lon"][mid]) != (s["lat"][mid], s["lon"][mid])


def test_n_is_bounded():
    b = bundle_for_site("haworth")
    assert dem_terrain_grid(n=1, bundle_dir=b)["n"] == 2        # floored to a usable grid
    assert dem_terrain_grid(n=9999, bundle_dir=b)["n"] == 192   # capped for browser/transport
