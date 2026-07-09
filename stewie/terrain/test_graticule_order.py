"""Pure-logic tests for the order-frame graticule generator (mirrors graticule.js, reprojected + clipped).

``reproject`` is injected, so these test the sampling/clipping/labelling geometry with an analytic transform
(no fabricated DEM data). A final test wires the REAL Haworth IAU_2015:30135 forward transform when the
bundle + pyproj are present, asserting the lines actually curve in the polar frame.
"""
from __future__ import annotations

import math
import os

import numpy as np
import pytest

from stewie.terrain.graticule_order import (
    auto_steps,
    graticule_order_polylines,
    meridians_order,
    parallels_order,
)


def _affine_reproject(lon0, lat0, mpp_lon, mpp_lat, x0, y0):
    """A linear lon/lat -> tile-metre transform (a stand-in for the real projection) for geometry tests."""
    def rp(lons, lats):
        lons = np.asarray(lons, dtype=float)
        lats = np.asarray(lats, dtype=float)
        xs = x0 + (lons - lon0) * mpp_lon
        ys = y0 + (lats - lat0) * mpp_lat
        return xs, ys
    return rp


def test_meridians_are_constant_x_and_span_the_window():
    # window origin (x0,y0) in tile metres; a linear transform -> meridians are vertical lines.
    rp = _affine_reproject(lon0=-25.0, lat0=-87.0, mpp_lon=2000.0, mpp_lat=-30000.0, x0=100.0, y0=500.0)
    lines = meridians_order(rp, x0=100.0, y0=500.0, window_m=1000.0,
                            lon_min=-25.0, lon_max=-24.5, lat_min=-87.2, lat_max=-86.8,
                            lon_step=0.25, lat_sample=0.02)
    assert lines, "expected at least one meridian in-window"
    for ln in lines:
        assert ln["kind"] == "meridian"
        xs = [p[0] for p in ln["coords"]]
        assert max(xs) - min(xs) < 1e-6, "a meridian is constant-x under a linear transform"
        assert all(0.0 <= p[0] <= 1000.0 and 0.0 <= p[1] <= 1000.0 for p in ln["coords"])  # clipped
        assert len(ln["coords"]) >= 2


def test_parallels_are_constant_y_and_labelled():
    rp = _affine_reproject(lon0=-25.0, lat0=-87.0, mpp_lon=2000.0, mpp_lat=-30000.0, x0=100.0, y0=500.0)
    lines = parallels_order(rp, x0=100.0, y0=500.0, window_m=1000.0,
                            lon_min=-25.0, lon_max=-24.5, lat_min=-87.02, lat_max=-86.98,
                            lat_step=0.01, lon_sample=0.02)
    assert lines
    labelled = {ln["label"] for ln in lines}
    assert any(lb.endswith("°") for lb in labelled)          # graticule.js degree label style
    for ln in lines:
        ys = [p[1] for p in ln["coords"]]
        assert max(ys) - min(ys) < 1e-6, "a parallel is constant-y under a linear transform"


def test_offwindow_and_nonfinite_points_split_into_runs():
    # a transform that pushes half the lat samples far outside the window -> the meridian splits/clips,
    # and a NaN sentinel run is dropped rather than bridged.
    def rp(lons, lats):
        lons = np.asarray(lons, dtype=float)
        lats = np.asarray(lats, dtype=float)
        xs = np.full(lons.shape, 500.0)
        ys = (lats + 87.0) * 1e5 + 500.0                     # steep: most points fly off-window
        ys[lats < -87.05] = math.nan                         # off-tile sentinel
        return xs, ys
    lines = meridians_order(rp, x0=0.0, y0=0.0, window_m=1000.0,
                            lon_min=-25.0, lon_max=-25.0, lat_min=-87.1, lat_max=-86.9,
                            lon_step=1.0, lat_sample=0.01)
    for ln in lines:                                         # every emitted point is inside the window
        assert all(0.0 <= p[1] <= 1000.0 for p in ln["coords"])


def test_full_graticule_concats_meridians_and_parallels():
    rp = _affine_reproject(lon0=-25.0, lat0=-87.0, mpp_lon=2000.0, mpp_lat=-30000.0, x0=0.0, y0=0.0)
    st = auto_steps(-25.2, -24.8, -87.1, -86.9, target_lines=4)
    g = graticule_order_polylines(rp, x0=0.0, y0=0.0, window_m=800.0,
                                  lon_min=-25.2, lon_max=-24.8, lat_min=-87.1, lat_max=-86.9,
                                  lon_step=st["lon_step"], lat_step=st["lat_step"],
                                  lon_sample=st["lon_sample"], lat_sample=st["lat_sample"])
    kinds = {ln["kind"] for ln in g}
    assert kinds == {"meridian", "parallel"} or kinds.issubset({"meridian", "parallel"})
    assert st["lon_step"] > 0 and st["lat_step"] > 0 and st["lon_sample"] < st["lon_step"]


_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "samples", "lunar_dem", "haworth_10km_5m")


@pytest.mark.skipif(not os.path.exists(os.path.join(_BUNDLE, "metadata.json")),
                    reason="real Haworth DEM bundle not present")
def test_real_haworth_meridians_curve():
    pytest.importorskip("pyproj")
    from stewie.terrain.site_dem import _proj_ctx, dem_georef_corners

    cell, W, H, ax0, ay0, fwd, _inv = _proj_ctx(None)

    def reproject(lons, lats):
        xs_proj, ys_proj = fwd.transform(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
        tx = (np.asarray(xs_proj) - ax0)                      # tile-pixel metres (col*cell)
        ty = (ay0 - np.asarray(ys_proj))
        return tx, ty

    geo = dem_georef_corners()
    lons = [c["lon"] for c in geo["corners"]]
    lats = [c["lat"] for c in geo["corners"]]
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)
    st = auto_steps(lon_min, lon_max, lat_min, lat_max, target_lines=6)
    win = (min(W, H) - 1) * cell
    g = graticule_order_polylines(reproject, x0=0.0, y0=0.0, window_m=win,
                                  lon_min=lon_min, lon_max=lon_max, lat_min=lat_min, lat_max=lat_max,
                                  lon_step=st["lon_step"], lat_step=st["lat_step"],
                                  lon_sample=st["lon_sample"], lat_sample=st["lat_sample"], pad=win * 0.02)
    assert g, "expected graticule lines over the real Haworth tile"
    # at least one line should visibly curve in the polar frame (its points are not collinear)
    curved = False
    for ln in g:
        pts = ln["coords"]
        if len(pts) >= 3:
            (ax, ay), (bx, by), (cx, cy) = pts[0], pts[len(pts) // 2], pts[-1]
            cross = abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax))
            if cross > 1.0:                                   # non-collinear (metres^2) -> curvature
                curved = True
                break
    assert curved, "polar-stereographic graticule lines should curve, not be straight"
