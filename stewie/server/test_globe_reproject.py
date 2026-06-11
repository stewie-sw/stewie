"""The globe drape must be GEOGRAPHIC: reprojecting polar-stereo rasters for Cesium.

Aaron's screenshot (2026-06-10): the stereographic hillshade draped into a lat/lon rectangle
renders ROTATED and misaligned, and the work-area rasters stretch over the wrong extent. The fix
is the standard GIS one -- resample the raster onto a geographic (lat/lon) grid server-side, and
give every layer ITS OWN bbox.
"""
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
    # Aaron's 2nd screenshot: the drape was the matplotlib PREVIEW FIGURE (axis labels + white
    # margins on the Moon). The drape must be a CLEAN raster over the WHOLE footprint.
    lit = rgba[rgba[..., 3] > 0]
    assert (lit[..., 0] >= 250).mean() < 0.02              # <2% near-white: no figure margins


def test_reprojection_centers_align():
    """The geographic image's CENTER pixel must correspond to the tile's center lat/lon -- the
    alignment property the naive bbox-drape violated (the rotation Aaron saw)."""
    rgba, bbox = G.render_globe("dem")
    from lode.mission_planner import dem_georef_corners
    ctr = dem_georef_corners()["center"]
    # the bbox midpoint should be within a fraction of the tile of the true center
    assert abs((bbox["south"] + bbox["north"]) / 2 - ctr["lat"]) < 0.25
    # and the center pixel must be OPAQUE tile content (the rotated drape had corners there)
    h, w = rgba.shape[:2]
    assert rgba[h // 2, w // 2, 3] > 0


def test_work_area_rasters_get_their_own_bbox():
    """SUPERSEDED 2026-06-10 by Aaron's full-tile directive: globe rasters now cover the WHOLE
    tile (the small-bbox behavior was the bug he screenshotted); kept as the bbox-consistency pin."""
    rgba, bbox = G.render_globe("slope")
    rgba2, bbox2 = G.render_globe("dem")
    assert abs((bbox["north"] - bbox["south"]) - (bbox2["north"] - bbox2["south"])) < 0.02


def test_globe_rasters_cover_the_full_tile():
    """Aaron (desktop image): clicking hazard loaded only the 640 m work-area patch -- analysis
    layers on the GLOBE must cover the FULL 10 km tile (the inset keeps the work-area crop)."""
    rgba_s, bb_s = G.render_globe("slope")
    rgba_d, bb_d = G.render_globe("dem")
    span = lambda b: b["north"] - b["south"]
    assert abs(span(bb_s) - span(bb_d)) < 0.02             # slope bbox == the tile bbox
    rgba_h, bb_h = G.render_globe("hazard")
    assert abs(span(bb_h) - span(bb_d)) < 0.02
    # full-tile slope must contain steep content (Haworth's walls), not just the flat work area
    lit = rgba_s[rgba_s[..., 3] > 0]
    assert lit.size and float(rgba_s[..., 3].max()) > 150


def test_site_grid_drapes_the_full_tile():
    """#54: the MGRS-analog site grid -- 100 m minor / 500 m major site-frame lines as a drape."""
    rgba, bbox = G.render_globe("grid")
    rgba_d, bbox_d = G.render_globe("dem")
    assert abs((bbox["north"] - bbox["south"]) - (bbox_d["north"] - bbox_d["south"])) < 0.02
    frac = float((rgba[..., 3] > 0).mean())
    assert 0.005 < frac < 0.30                             # lines, not fill; not empty
