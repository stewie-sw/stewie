"""The globe drape must be GEOGRAPHIC: reprojecting polar-stereo rasters for Cesium.

Aaron's screenshot (2026-06-10): the stereographic hillshade draped into a lat/lon rectangle
renders ROTATED and misaligned, and the work-area rasters stretch over the wrong extent. The fix
is the standard GIS one -- resample the raster onto a geographic (lat/lon) grid server-side, and
give every layer ITS OWN bbox.
"""
import numpy as np
import pytest

pyproj = pytest.importorskip("pyproj")

from stewie.server import gis_layers as G


def test_reprojected_tile_has_geographic_bbox_and_content():
    rgba, bbox = G.render_globe("dem")
    assert rgba.shape[2] == 4 and rgba.shape[0] >= 256
    assert bbox["south"] < bbox["north"] <= -85.0          # a south-polar tile
    assert bbox["west"] < bbox["east"]
    interior = rgba[rgba.shape[0]//3:-rgba.shape[0]//3, rgba.shape[1]//3:-rgba.shape[1]//3]
    assert (interior[..., 3] > 0).mean() > 0.9             # the tile's middle is real content
    assert interior[..., 0].std() > 4.0                    # real relief, not flat fill


def test_reprojection_centers_align():
    """The geographic image's CENTER pixel must correspond to the tile's center lat/lon -- the
    alignment property the naive bbox-drape violated (the rotation Aaron saw)."""
    rgba, bbox = G.render_globe("dem")
    from lode.mission_planner import dem_georef_corners, latlon_to_dem_origin
    ctr = dem_georef_corners()["center"]
    # the bbox midpoint should be within a fraction of the tile of the true center
    assert abs((bbox["south"] + bbox["north"]) / 2 - ctr["lat"]) < 0.25
    # and the center pixel must be OPAQUE tile content (the rotated drape had corners there)
    h, w = rgba.shape[:2]
    assert rgba[h // 2, w // 2, 3] > 0


def test_work_area_rasters_get_their_own_bbox():
    rgba, bbox = G.render_globe("slope")
    rgba2, bbox2 = G.render_globe("dem")
    # the work area (640 m) is a SMALL box inside the tile's bbox (10 km)
    assert bbox["north"] - bbox["south"] < (bbox2["north"] - bbox2["south"]) / 3
    assert bbox2["south"] - 1e-6 <= bbox["south"] and bbox["north"] <= bbox2["north"] + 1e-6
