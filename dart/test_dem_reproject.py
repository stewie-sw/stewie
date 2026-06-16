"""TW-02: lock dem_import.reproject_cylindrical (the non-polar equirectangular->local-metric reprojection
the global-LOLA 'reproject' DEM sources need -- dem_sources.lola_global_118m). It was shipped but
untested (V=N); these are transform-correctness assertions on real lunar geometry (MOON_ME R=1737400 m)
with a REAL Haworth height sub-patch as the carrier grid -- no synthetic terrain.

Run: <venv>/bin/python -m pytest dart/test_dem_reproject.py -q
"""
import math
import os

import numpy as np
import pytest

from dart.dem_import import reproject_cylindrical

_R = 1737400.0                              # MOON_ME mean radius (the lunar datum)
_HM = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32")


def _real_patch(h=30, w=40):
    """A real HxW sub-window of the bundled Haworth heightmap (real float32 elevations, the carrier grid
    for the coordinate-transform test -- the geometry assertions do not depend on the height values)."""
    flat = np.memmap(_HM, dtype=np.float32, mode="r")
    side = int(round(math.sqrt(flat.size)))            # 2000 x 2000
    grid = np.asarray(flat).reshape(side, side)
    return np.array(grid[100:100 + h, 200:200 + w], dtype=np.float64)


def test_reproject_returns_finite_local_grid():
    z, cell_m = reproject_cylindrical(_real_patch(), lat_top=10.0, lat_bottom=9.7,
                                      lon_left=20.0, lon_right=20.5, radius_m=_R)
    assert z.ndim == 2 and z.size > 0
    assert np.isfinite(z).all() and cell_m > 0


def test_y_extent_matches_lunar_arc_length():
    # a 0.3deg latitude span on R=1737400 m is an arc of R*dlat*pi/180; the local grid's north-south
    # metric extent must match it (this is what proves the reprojection uses the lunar radius, not Earth)
    z, cell_m = reproject_cylindrical(_real_patch(), lat_top=10.0, lat_bottom=9.7,
                                      lon_left=20.0, lon_right=20.5, radius_m=_R)
    expected_arc = _R * math.radians(0.3)
    got = z.shape[0] * cell_m
    assert got == pytest.approx(expected_arc, rel=0.2), (got, expected_arc)


def test_extent_scales_with_radius_not_a_fixed_datum():
    a = reproject_cylindrical(_real_patch(), lat_top=10.0, lat_bottom=9.7, lon_left=20.0, lon_right=20.5,
                              radius_m=_R)
    b = reproject_cylindrical(_real_patch(), lat_top=10.0, lat_bottom=9.7, lon_left=20.0, lon_right=20.5,
                              radius_m=2 * _R)
    ext_a = a[0].shape[0] * a[1]
    ext_b = b[0].shape[0] * b[1]
    assert ext_b / ext_a == pytest.approx(2.0, rel=0.05)     # doubling R doubles the metric extent


def test_target_cell_is_honored():
    _z, cell_m = reproject_cylindrical(_real_patch(), lat_top=10.0, lat_bottom=9.7, lon_left=20.0,
                                       lon_right=20.5, radius_m=_R, target_cell_m=50.0)
    assert cell_m == pytest.approx(50.0)


def test_degenerate_patch_raises():
    with pytest.raises(ValueError):
        reproject_cylindrical(_real_patch(), lat_top=9.7, lat_bottom=10.0,   # top <= bottom
                              lon_left=20.0, lon_right=20.5, radius_m=_R)
