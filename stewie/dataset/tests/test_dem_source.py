"""dem_source: geometry read (no pixel load) + windowed reader + shared 30135 transform.

Cross-checks the tag-only geometry against the frozen ``dart.dem_import.load_lola_geotiff`` on the
real fixture, so the additive geometry reader can never drift from the canonical affine convention.
"""
from __future__ import annotations

import math
import os

import numpy as np

from stewie.dataset import dem_source


def test_geometry_matches_dem_import_affine(fixture_tif):
    """Tag-only geometry must equal the affine dem_import derives from a full load (no drift)."""
    from dart.dem_import import load_lola_geotiff

    g = dem_source.read_geotiff_geometry(fixture_tif)
    Z, aff, meta = load_lola_geotiff(fixture_tif)
    assert (g.height, g.width) == Z.shape
    assert abs(g.cell_m - aff.px) < 1e-9
    assert abs(g.x0_center - aff.x0) < 1e-6
    assert abs(g.y0_center - aff.y0) < 1e-6
    assert g.raster_type == "PixelIsArea"
    assert abs(g.radius_m - 1737400.0) < 1e-3          # real datum from the GeoKeys
    assert g.crs_authority == "IAU_2015:30135"         # reused from site_dem.bundle_crs
    # footprint bounds are the pixel-area outer edges
    assert abs(g.x_min - (aff.x0 - aff.px / 2.0)) < 1e-6
    assert abs(g.y_max - (aff.y0 + aff.px / 2.0)) < 1e-6
    assert math.isclose(g.extent_x_m, g.width * g.cell_m)
    assert math.isclose(g.extent_y_m, g.height * g.cell_m)


def test_windowed_read_equals_full_load(fixture_tif):
    """A window read off the strips must equal the same slice of the full array (real pixels)."""
    from dart.dem_import import load_lola_geotiff

    Z, _aff, _meta = load_lola_geotiff(fixture_tif)
    reader = dem_source.GeoTiffWindowReader(fixture_tif)
    win = reader(30, 40, 50, 60)
    assert win.shape == (50, 60)
    np.testing.assert_array_equal(win, Z[30:80, 40:100])   # rows 30:30+50, cols 40:40+60
    assert np.isfinite(win).all()          # this interior window is fully non-nodata (real)


def test_window_clamped_to_grid(fixture_reader):
    """Windows are clamped to the grid bounds (no over-read past the raster edge)."""
    w = fixture_reader(250, 250, 100, 100)   # only 6x6 remains in a 256x256 grid
    assert w.shape == (6, 6)


def test_shared_transform_roundtrip_and_haworth_range(fixture_geometry):
    """The center of the fixture round-trips through the shared 30135 transform and is deep polar."""
    g = fixture_geometry
    cx, cy = (g.x_min + g.x_max) / 2.0, (g.y_min + g.y_max) / 2.0
    lat, lon = dem_source.proj_to_latlon(cx, cy)
    assert -88.0 < lat < -86.0                       # real Haworth south-polar latitude
    x2, y2 = dem_source.latlon_to_proj(lat, lon)
    assert abs(x2 - cx) < 1e-3 and abs(y2 - cy) < 1e-3

    # the shared inverse must agree with site_dem's own inverse transformer (same CRS object)
    from stewie.terrain.site_dem import bundle_crs
    from pyproj import Transformer
    inv = Transformer.from_crs(bundle_crs(), bundle_crs().geodetic_crs, always_xy=True)
    lon2, lat2 = inv.transform(cx, cy)
    assert abs(lat2 - lat) < 1e-9 and abs(lon2 - lon) < 1e-9


def test_resolve_dem_path_prefers_explicit(fixture_tif):
    assert dem_source.resolve_dem_path(fixture_tif) == os.path.abspath(fixture_tif)
    # a non-existent explicit path is never returned verbatim (falls through to real candidates/None)
    assert dem_source.resolve_dem_path("/no/such/file.tif") != "/no/such/file.tif"
