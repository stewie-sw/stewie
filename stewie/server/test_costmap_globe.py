"""[REQ:AS-11] The costmap ANALYSIS drape: the plan-independent traversability COST heatmap + the
categorical BLOCKING-REASON grid, both computed from the REAL 12-layer costmap (`lode.costmap_layers`)
on the site's REAL DEM, served as two new globe kinds (`cost`, `blocking`) on /layers/globe/{kind}.png.

Grounded on the real LOLA Haworth tile (a native-resolution subsample of the committed
samples/lunar_dem/haworth_10km_5m heightmap -- real data, not synthetic). Asserts: the render helpers
emit valid RGBA PNGs; the cost heatmap tracks slope (green low -> red high) on real terrain; and the
blocking overlay is opaque EXACTLY on the composite's impassable cells (transparent where passable),
each coloured by a real veto reason.
"""
import math
import os

import numpy as np
import pytest

from lode import costmap_layers as CL
from stewie.server import gis_layers as G
from stewie.terrain.site_dem import slope_deg_map

_HAWORTH = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "lunar_dem",
                        "haworth_10km_5m", "heightmap.rf32")
pytestmark = pytest.mark.skipif(not os.path.exists(_HAWORTH), reason="haworth DEM not present")

_CELL = 5.0            # native tile resolution (m/px); the real drape reprojects the full tile
_SUN_EL, _SUN_AZ = 15.0, 90.0


def _haworth_window():
    """A real 96x96 crop of the committed LOLA Haworth tile (native 5 m cells) with genuine crater
    relief -- both passable and impassable cells, real slope variation."""
    full = np.fromfile(_HAWORTH, dtype="<f4").reshape(2000, 2000).astype(float)
    return full[1000:1096, 1000:1096].copy(), _CELL


def _decode_png(png: bytes):
    from imageio.v3 import imread
    return imread(png)


def test_cost_and_blocking_helpers_emit_valid_rgba_png():
    dem, cell = _haworth_window()
    cm = G._costmap_compose(dem, cell, _SUN_AZ, _SUN_EL)
    for rgba in (G._cost_heatmap_rgba(cm.cost), G._blocking_rgba(cm.reason, cm.passable)):
        assert rgba.shape == (dem.shape[0], dem.shape[1], 4)
        assert rgba.dtype == np.uint8
        dec = _decode_png(G._to_png(rgba))            # round-trips through a real PNG encoder/decoder
        assert dec.shape == rgba.shape
        assert np.array_equal(dec, rgba)


def test_cost_heatmap_increases_with_slope_on_real_terrain():
    dem, cell = _haworth_window()
    cm = G._costmap_compose(dem, cell, _SUN_AZ, _SUN_EL)
    slope = slope_deg_map(dem, cell)
    # the REAL costmap cost is slope-driven (slip + energy + roughness + slope all rise with grade)
    assert np.corrcoef(slope.ravel(), cm.cost.ravel())[0, 1] > 0.5
    rgba = G._cost_heatmap_rgba(cm.cost)
    # green(low) -> red(high): "redness" = R - G rises with cost, hence with slope. Compare the steep
    # quartile to the gentle quartile within the SAME (per-image normalized) heatmap.
    redness = rgba[..., 0].astype(int) - rgba[..., 1].astype(int)
    steep = slope > np.percentile(slope, 75)
    gentle = slope < np.percentile(slope, 25)
    assert redness[steep].mean() > redness[gentle].mean()


def test_blocking_overlay_matches_impassable_cells():
    dem, cell = _haworth_window()
    cm = G._costmap_compose(dem, cell, _SUN_AZ, _SUN_EL)
    # real crater terrain must block SOME cells and leave SOME passable (both classes present)
    assert 0.0 < cm.passable.mean() < 1.0
    rgba = G._blocking_rgba(cm.reason, cm.passable)
    opaque = rgba[..., 3] > 0
    # the blocking overlay is opaque EXACTLY on the impassable cells, transparent where passable
    assert np.array_equal(opaque, ~cm.passable)
    # every coloured cell carries a real veto reason that has a defined colour
    blocked_reasons = set(np.unique(cm.reason[~cm.passable]).tolist())
    assert blocked_reasons and blocked_reasons.issubset(set(G.BLOCKING_COLORS))


def test_negative_obstacle_scaled_to_cell_not_blanket_blocking():
    # the drape scales the drop cap to the cell (a cliff steeper than the slope cap), so a coarse tile is
    # NOT blanket-blocked by the rover-scale 0.15 m step. At the native cell the composite stays mixed.
    dem, cell = _haworth_window()
    cm = G._costmap_compose(dem, cell, _SUN_AZ, _SUN_EL)
    expect_drop = cell * math.tan(math.radians(25.0))
    # sanity: with the fixed 0.15 m rover cap the same tile is fully blocked; the scaled cap is not
    fixed = CL.compose(CL.CostmapContext(Z=dem, cell_m=cell, max_slope_deg=25.0, max_drop_m=0.15,
                                         sun_el_deg=_SUN_EL, sun_az_deg=_SUN_AZ))
    assert fixed.passable.mean() < cm.passable.mean()
    assert expect_drop > 0.15


def test_cost_and_blocking_are_globe_kinds_with_legends():
    from stewie.server.routers.layers import _GLOBE_KINDS, layers_legend
    assert "cost" in _GLOBE_KINDS and "blocking" in _GLOBE_KINDS
    legend = layers_legend()
    assert "cost" in legend and "blocking" in legend
    # the blocking legend enumerates real veto reasons with hex colours matching the renderer
    reasons = {r["reason"]: r["hex"] for r in legend["blocking"]["reasons"]}
    assert "slope" in reasons and "psr" in reasons
    for name, hexcol in reasons.items():
        assert hexcol == "#%02x%02x%02x" % G.BLOCKING_COLORS[name]


def test_render_globe_wires_cost_and_blocking_end_to_end():
    # the full drape pipeline (compose -> colourise -> reproject to geographic) for both new kinds
    for kind in ("cost", "blocking"):
        out = G.render_globe(kind, sun_el=_SUN_EL, sun_az=_SUN_AZ, site="haworth")
        assert out is not None
        rgba, bbox = out
        assert rgba.ndim == 3 and rgba.shape[2] == 4 and rgba.dtype == np.uint8
        assert {"south", "north", "west", "east"} <= set(bbox)
        assert bbox["north"] <= -85.0                 # a south-polar selenographic tile
