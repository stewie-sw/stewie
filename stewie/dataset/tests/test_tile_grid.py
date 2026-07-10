"""TileGrid: numbered 100 m tiles + 25 m sub-graticule over the real DEM footprint.

Gates (real fixture, and the real full DEM where present):
  * tile count == ceil(extent/tile_m) per axis;
  * a known tile's projected extent is exact;
  * its center lat/lon round-trips through the shared 30135 transform AND lands in the real
    Haworth south-polar range (not 0/NaN);
  * determinism: identical inputs -> byte-identical tile ids + extents + lat/lon;
  * every tile's 4-corner polygon closes; valid_frac is the geometric footprint fraction.
"""
from __future__ import annotations

import math

from stewie.dataset.dem_source import latlon_to_proj, read_geotiff_geometry
from stewie.dataset.tile_grid import TileGrid


def test_tile_count_is_ceil_extent_over_tile_m(fixture_geometry):
    g = fixture_geometry
    grid = TileGrid(g, tile_m=100.0, sub_m=25.0)
    assert grid.n_cols == math.ceil(g.extent_x_m / 100.0) == 3
    assert grid.n_rows == math.ceil(g.extent_y_m / 100.0) == 3
    assert grid.n_tiles == 9 == len(grid.tiles)
    # linear row-major index is stable + contiguous
    assert [t.index for t in grid.tiles] == list(range(9))
    for t in grid.tiles:
        assert t.index == t.row * grid.n_cols + t.col
        assert t.tile_id == f"r{t.row:03d}c{t.col:03d}"


def test_known_tile_extent_is_exact(fixture_geometry):
    g = fixture_geometry
    grid = TileGrid(g, tile_m=100.0, sub_m=25.0)
    t0 = grid.tile(0)                       # row 0, col 0 = NW tile
    assert (t0.x0, t0.y0, t0.x1, t0.y1) == (g.x_min, g.y_max - 100.0, g.x_min + 100.0, g.y_max)
    assert (t0.x0, t0.y0, t0.x1, t0.y1) == (-35120.0, 90220.0, -35020.0, 90320.0)
    assert t0.px_row0 == 0 and t0.px_col0 == 0 and t0.px_h == 100 and t0.px_w == 100
    assert t0.tile_m == 100.0 and t0.sub_m == 25.0
    assert abs(t0.area_m2 - 100.0 * 100.0) < 1e-6 and abs(t0.valid_frac - 1.0) < 1e-12

    # the SE corner tile is partial (56 m) -> clamped extent, valid_frac < 1
    tc = grid.tile_at(grid.n_rows - 1, grid.n_cols - 1)
    assert abs((tc.x1 - tc.x0) - 56.0) < 1e-6 and abs((tc.y1 - tc.y0) - 56.0) < 1e-6
    assert 0.0 < tc.valid_frac < 1.0
    assert tc.px_w == 56 and tc.px_h == 56


def test_center_latlon_roundtrips_and_is_haworth_polar(fixture_geometry):
    grid = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    t0 = grid.tile(0)
    assert math.isfinite(t0.center_lat) and math.isfinite(t0.center_lon)
    assert -88.0 < t0.center_lat < -86.0              # real south-polar Haworth, not 0/NaN
    assert abs(t0.center_lat - (-86.807147)) < 1e-4
    assert abs(t0.center_lon - (-21.231206)) < 1e-4
    x, y = latlon_to_proj(t0.center_lat, t0.center_lon)
    cx, cy = (t0.x0 + t0.x1) / 2.0, (t0.y0 + t0.y1) / 2.0
    assert abs(x - cx) < 1e-3 and abs(y - cy) < 1e-3
    # all four corners resolve to finite polar lat/lon too
    for lat, lon in t0.corners_latlon:
        assert -88.0 < lat < -86.0 and math.isfinite(lon)
    assert len(t0.corners_latlon) == 4


def test_polygon_closes(fixture_geometry):
    grid = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    for t in grid.tiles:
        ring = t.corner_ring_lonlat()       # NW,NE,SE,SW,NW -> closed
        assert len(ring) == 5
        assert ring[0] == ring[-1]


def test_determinism_byte_identical(fixture_geometry):
    g1 = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    g2 = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    a = [(t.tile_id, t.x0, t.y0, t.x1, t.y1, t.center_lat, t.center_lon) for t in g1.tiles]
    b = [(t.tile_id, t.x0, t.y0, t.x1, t.y1, t.center_lat, t.center_lon) for t in g2.tiles]
    assert a == b


def test_sub_graticule_is_finer_than_tiles(fixture_geometry):
    grid = TileGrid(fixture_geometry, tile_m=100.0, sub_m=25.0)
    sub = grid.sub_graticule_lines()        # display sub-gridlines at 25 m
    # 25 m minor lines are 4x denser than the 100 m tile edges within the footprint
    assert sub["sub_m"] == 25.0 and sub["tile_m"] == 100.0
    assert len(sub["x_lines_m"]) > grid.n_cols and len(sub["y_lines_m"]) > grid.n_rows
    # minor lines fall on 25 m multiples from the origin, tile edges on 100 m multiples
    for xv in sub["x_lines_m"]:
        assert abs((xv - fixture_geometry.x_min) % 25.0) < 1e-6


def test_real_full_dem_grid(real_dem_path):
    """The actual dataset: 11660x12060 @ 1 m -> 117x121 tiles; tile 0 is real Haworth polar."""
    g = read_geotiff_geometry(real_dem_path)
    assert (g.width, g.height) == (11660, 12060)
    grid = TileGrid(g, tile_m=100.0, sub_m=25.0)
    assert grid.n_cols == 117 and grid.n_rows == 121 and grid.n_tiles == 14157
    t0 = grid.tile(0)
    assert -88.0 < t0.center_lat < -86.0
    assert abs(t0.center_lat - (-86.5926)) < 1e-3
    assert abs(t0.center_lon - (-22.8113)) < 1e-3
