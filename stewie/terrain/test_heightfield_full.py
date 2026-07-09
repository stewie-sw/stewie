"""Pure-logic tests for the full-resolution heightfield sampler (viz.stewie.space data path).

The load-bearing invariant is REGISTRATION: the column/row index formula must be byte-identical to
/dem/workarea.png so an analysis raster over the same window drapes cell-for-cell. That invariant is
pure integer geometry (no DEM values needed), so it is fully exercised in CI. A second test samples a
tiny slice of the REAL Haworth DEM (subsampled real data, per the no-synthetic rule) when the bundle is
present, to confirm the height read + z-range against a direct numpy index.
"""
from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.terrain.heightfield_full import (
    full_grid_spec,
    heightfield_full,
    native_full_window_m,
    suggested_layer_px,
)


def _workarea_indices(width, height, cell, x0, y0, win):
    """The EXACT sampling /dem/workarea.png uses (native, no LOD): the reference registration formula."""
    npx = max(2, int(round(win / cell)) + 1)
    xs = np.linspace(0.0, win, npx)
    cols = np.clip(np.round((x0 + xs) / cell).astype(int), 0, width - 1)
    rows = np.clip(np.round((y0 + xs) / cell).astype(int), 0, height - 1)
    return rows, cols


def test_native_indices_register_with_workarea_png():
    # a 640 m window at 5 m over a 2000x2000 tile, anchored at the flattest-anchor offset (x0,y0).
    W = H = 2000
    cell = 5.0
    x0, y0, win = 300.0, 450.0, 640.0
    spec = full_grid_spec(W, H, cell, x0, y0, win, max_dim=4096)   # cap above native -> no LOD
    ref_rows, ref_cols = _workarea_indices(W, H, cell, x0, y0, win)
    assert spec["n"] == spec["native_n"] == len(ref_cols)          # native px count == workarea.png's
    assert spec["lod"] is False and spec["stride"] == 1.0
    np.testing.assert_array_equal(spec["cols"], ref_cols)          # cell-for-cell registration
    np.testing.assert_array_equal(spec["rows"], ref_rows)


def test_full_tile_default_is_native_resolution():
    # the Haworth default: the whole tile at native 5 m -> exactly the tile dimension across, no clamp dup.
    W = H = 2000
    cell = 5.0
    win = native_full_window_m(W, H, cell)                          # (2000-1)*5 = 9995 m
    spec = full_grid_spec(W, H, cell, 0.0, 0.0, win, max_dim=2048)
    assert spec["n"] == W                                           # 2000 samples across the 10 km tile
    assert spec["cols"][0] == 0 and spec["cols"][-1] == W - 1       # spans 0..1999 with no edge duplication
    assert spec["stride"] == 1.0 and spec["lod"] is False


def test_lod_caps_grid_dim_but_keeps_window_extent():
    # a native window bigger than max_dim decimates to exactly max_dim samples, extent unchanged.
    W = H = 2000
    cell = 5.0
    win = native_full_window_m(W, H, cell)                          # native_n would be 2000
    spec = full_grid_spec(W, H, cell, 0.0, 0.0, win, max_dim=512)
    assert spec["n"] == 512 and spec["native_n"] == W
    assert spec["lod"] is True and spec["stride"] > 1.0
    assert spec["window_m"] == pytest.approx(win)                   # SAME extent -> texture still registers
    assert spec["cols"][0] == 0 and spec["cols"][-1] == W - 1       # first/last cells still hit


def test_window_and_origin_are_clamped_to_the_tile():
    W = H = 2000
    cell = 5.0
    tile = (W - 1) * cell
    # oversized window is clamped to the tile; an origin that would run off-tile is pulled back on.
    spec = full_grid_spec(W, H, cell, x0=999999.0, y0=0.0, window_m=999999.0)
    assert spec["window_m"] == pytest.approx(tile)
    assert 0.0 <= spec["x0"] <= tile - spec["window_m"] + 1e-6


def test_suggested_layer_px_bounds_expensive_kinds():
    assert suggested_layer_px("psr", 2000) == 384                  # horizon-sweep kind capped small
    assert suggested_layer_px("slope", 2000) == 1024               # cheap gradient kind capped at 1024
    assert suggested_layer_px("slope", 300) == 300                 # never exceeds the mesh vertex count


_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "samples", "lunar_dem", "haworth_10km_5m")


@pytest.mark.skipif(not os.path.exists(os.path.join(_BUNDLE, "heightmap.rf32")),
                    reason="real Haworth DEM bundle not present (wheel install / no fetch)")
def test_samples_real_haworth_dem_slice():
    # subsample REAL LOLA data (a small window) and confirm the height read + z-range vs a direct index.
    from stewie.terrain.site_dem import load_haworth_dem
    Z, cell = load_haworth_dem()
    x0, y0, win = 500.0, 500.0, 300.0
    grid, meta = heightfield_full(Z, cell, x0, y0, win, max_dim=4096)
    ref_rows, ref_cols = _workarea_indices(Z.shape[1], Z.shape[0], cell, x0, y0, win)
    ref = np.asarray(Z, dtype=np.float32)[np.ix_(ref_rows, ref_cols)]
    np.testing.assert_array_equal(grid, ref)                        # exact real-DEM sample, registered
    assert meta["z_min"] == pytest.approx(float(ref.min()))
    assert meta["z_max"] == pytest.approx(float(ref.max()))
    assert grid.dtype == np.float32                                 # compact binary payload
