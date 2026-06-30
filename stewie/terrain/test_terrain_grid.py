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


def test_pole_touching_grid_is_continuous_in_ecef_no_mesh_tear():  # #293
    """#293 alleged the Cesium globe drape (loadTerrain3D -> Cesium.Cartesian3.fromDegreesArrayHeights)
    SHREDS for a pole-touching tile because grid-adjacent nodes' LONGITUDE jumps ~356 deg near the pole.
    VERIFIED FALSE and guarded here: fromDegrees converts (lon, lat) to ECEF, where those same nodes are
    physically CLOSE (a few-degree lon step at lat -89.8 is metres on the ground, not a globe-spanning
    jump), so the triangulated mesh is continuous. shackleton_rim touches the south pole (the worst case);
    the max ECEF gap between grid-adjacent nodes must stay ~the node spacing, not a globe-scale tear."""
    import math
    g = dem_terrain_grid(n=64, bundle_dir=bundle_for_site("shackleton_rim"))
    n, lat, lon = g["n"], g["lat"], g["lon"]
    assert min(lat) < -89.5                                     # the tile genuinely reaches the pole region
    R = 1737400.0                                              # selenographic sphere (the fromDegrees ellipsoid)

    def ecef(k):
        la, lo = math.radians(lat[k]), math.radians(lon[k])
        return (R * math.cos(la) * math.cos(lo), R * math.cos(la) * math.sin(lo), R * math.sin(la))
    spacing = g["tile_m"][0] / (n - 1)                         # ~159 m at n=64 on a 10 km tile
    worst = 0.0
    for j in range(n):
        for i in range(n):
            if i < n - 1:
                worst = max(worst, math.dist(ecef(j * n + i), ecef(j * n + i + 1)))    # right neighbour
            if j < n - 1:
                worst = max(worst, math.dist(ecef(j * n + i), ecef((j + 1) * n + i)))  # down neighbour
    assert worst < 5.0 * spacing, f"pole-touching mesh tears in ECEF: {worst:.0f} m vs ~{spacing:.0f} m (#293)"
