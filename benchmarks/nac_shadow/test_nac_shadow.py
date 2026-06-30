"""Tests for the LROC NAC cast-shadow benchmark helpers, run on TINY REAL fixtures.

The fixtures are small georeferenced crops of the actual downloaded LROC NAC ortho/DEM GeoTIFFs
(Giordano Bruno, two Sun elevations) -- real PDS data subsampled to ~180 m windows, not synthetic.
Not collected by the default suite (benchmarks/ is outside testpaths); run explicitly:
    .venv/bin/python -m pytest benchmarks/nac_shadow/test_nac_shadow.py
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import nac_shadow as ns  # noqa: E402

FX = os.path.join(os.path.dirname(__file__), "fixtures")
ORTHO32 = os.path.join(FX, "gb_ortho_e32_M1190012618.tif")
ORTHO54 = os.path.join(FX, "gb_ortho_e54_M156924032.tif")
DEM = os.path.join(FX, "gb_dem_3m.tif")
# world box the fixtures were cropped to (Equirectangular_Moon metres), and an inner sub-box
BOX = (-1882488.0, 1098962.0, -1882308.0, 1099142.0)
INNER = (-1882458.0, 1098992.0, -1882338.0, 1099112.0)


def test_fixtures_exist():
    for p in (ORTHO32, ORTHO54, DEM):
        assert os.path.exists(p), p


def test_load_window_geometry():
    w = ns.load_window(ORTHO54, INNER)
    assert w.pixels.ndim == 2 and w.pixels.size > 0
    assert math.isclose(w.gsd_m, 0.6, abs_tol=0.05)
    # box centre maps near the window centre
    cx = (INNER[0] + INNER[2]) / 2
    cy = (INNER[1] + INNER[3]) / 2
    r, c = w.world_to_rc(cx, cy)
    assert abs(r - w.pixels.shape[0] / 2) < 3
    assert abs(c - w.pixels.shape[1] / 2) < 3


def test_recover_height_equals_L_tan_e():
    L, e = 12.5, 28.0
    h = ns.recover_height_m(L, e)
    assert math.isclose(h, L * math.tan(math.radians(e)), rel_tol=1e-9)
    # and matches the DART implementation it wraps
    from dart.rock_taxonomy import shadow_height_m
    assert math.isclose(h, shadow_height_m(L, e), rel_tol=1e-12)


def test_coregistration_is_positive_real():
    # the two map-projected frames, sampled at the SAME world coords, register to the same ground
    cc = ns.coregistration_highpass_corr(ORTHO32, ORTHO54, INNER, shape=(120, 120), hp=11)
    assert np.isfinite(cc)
    assert cc > 0.1


def test_dem_relief_is_mound_scale_not_boulder_scale():
    rel = ns.dem_relief(DEM, BOX)
    assert rel["post_spacing_m"] == pytest.approx(3.0, abs=0.1)
    # the DEM cannot resolve features below ~3 posts (~9 m) -> boulder relief is unrecoverable here
    assert rel["min_resolvable_feature_m"] == pytest.approx(9.0, abs=0.5)
    assert rel["relief_m"] > 0.0


def test_directed_shadow_length_is_finite_nonneg():
    w = ns.load_window(ORTHO54, INNER)
    base = (w.pixels.shape[0] // 2, w.pixels.shape[1] // 2)
    L = ns.directed_shadow_length_m(w.pixels, base, 30.0, w.gsd_m)
    assert np.isfinite(L) and L >= 0.0


def test_longest_dark_run_returns_length_and_az():
    w = ns.load_window(ORTHO54, INNER)
    base = (w.pixels.shape[0] // 2, w.pixels.shape[1] // 2)
    L, az = ns.longest_dark_run_any_direction(w.pixels, base, w.gsd_m)
    assert np.isfinite(L) and L >= 0.0
    assert az is None or (0.0 <= az < 360.0)


def test_circular_concentration_bounds():
    assert ns.circular_concentration([10.0, 10.0, 10.0]) == pytest.approx(1.0, abs=1e-9)
    assert ns.circular_concentration([0.0, 90.0, 180.0, 270.0]) == pytest.approx(0.0, abs=1e-9)
    assert ns.circular_concentration([]) == 0.0
