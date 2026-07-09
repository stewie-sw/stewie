"""Order-frame selenographic graticule for the 3D terrain viewer.

Mirrors gis/qwc2/js/mission/graticule.js: selenographic meridians (constant lon, sampled in lat) and
parallels (constant lat, sampled in lon) are sampled DENSELY then reprojected, so they curve correctly in
the polar-stereographic frame. The difference from the 2D map: the injected ``reproject`` maps a
selenographic (lon, lat) to the DEM's TILE-PIXEL metre frame (the same frame latlon_to_dem_origin returns);
this module subtracts the window origin (x0, y0) to get order-LOCAL metres and clips the polylines to the
[0, window_m]^2 window, splitting a line into runs wherever it leaves the window or the transform returns
a non-finite point. PURE: ``reproject`` is injected, so the geometry is node-of-a-transform-agnostic and
unit-testable without pyproj. The endpoint wires ``reproject`` to the real IAU_2015:30135 forward transform.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np

# reproject: (lons, lats) arrays [deg] -> (xs, ys) arrays [tile-pixel metres]; non-finite for off-tile.
Reproject = Callable[[Sequence[float], Sequence[float]], tuple[Sequence[float], Sequence[float]]]


def _frange(a: float, b: float, step: float) -> list[float]:
    """Inclusive float range mirroring graticule.js `_range` (rounded to 1e-6, hard iteration cap)."""
    if not (step > 0) or not math.isfinite(a) or not math.isfinite(b):
        return [round(a, 6)] if math.isfinite(a) else []
    out, v, i = [], a, 0
    while v <= b + 1e-9 and i < 100000:
        out.append(round(v, 6))
        v += step
        i += 1
    return out


def _line_runs(xs, ys, win: float, pad: float, min_pts: int) -> list[list[list[float]]]:
    """Split one sampled line into runs of consecutive points that are finite AND inside the padded window.
    A polyline that dips off the window and returns yields two runs (never a segment jumping across the gap)."""
    runs, cur = [], []
    lo, hi = -pad, win + pad
    for x, y in zip(xs, ys):
        inside = math.isfinite(x) and math.isfinite(y) and lo <= x <= hi and lo <= y <= hi
        if inside:
            cur.append([round(float(x), 3), round(float(y), 3)])
        elif cur:
            if len(cur) >= min_pts:
                runs.append(cur)
            cur = []
    if len(cur) >= min_pts:
        runs.append(cur)
    return runs


def _fmt_deg(v: float) -> str:
    """graticule.js label style: integer degrees as '30°', a fractional step as '-88.5°'."""
    return (f"{int(round(v))}°" if abs(v - round(v)) < 1e-6 else f"{round(v, 3)}°")


def meridians_order(reproject: Reproject, *, x0: float, y0: float, window_m: float,
                    lon_min: float, lon_max: float, lat_min: float, lat_max: float,
                    lon_step: float, lat_sample: float, pad: float = 0.0, min_pts: int = 2) -> list[dict]:
    """Constant-lon lines over [lon_min, lon_max], each sampled in lat and reprojected to order-local metres."""
    out = []
    for lon in _frange(lon_min, lon_max, lon_step):
        lats = _frange(lat_min, lat_max, lat_sample)
        if len(lats) < min_pts:
            continue
        rx, ry = reproject([lon] * len(lats), lats)
        lx = np.asarray(rx, dtype=float) - float(x0)
        ly = np.asarray(ry, dtype=float) - float(y0)
        for run in _line_runs(lx, ly, float(window_m), pad, min_pts):
            out.append({"coords": run, "label": _fmt_deg(lon), "value": lon, "kind": "meridian"})
    return out


def parallels_order(reproject: Reproject, *, x0: float, y0: float, window_m: float,
                    lon_min: float, lon_max: float, lat_min: float, lat_max: float,
                    lat_step: float, lon_sample: float, pad: float = 0.0, min_pts: int = 2) -> list[dict]:
    """Constant-lat circles over [lat_min, lat_max], each sampled in lon and reprojected to order-local metres."""
    out = []
    for lat in _frange(lat_min, lat_max, lat_step):
        lons = _frange(lon_min, lon_max, lon_sample)
        if len(lons) < min_pts:
            continue
        rx, ry = reproject(lons, [lat] * len(lons))
        lx = np.asarray(rx, dtype=float) - float(x0)
        ly = np.asarray(ry, dtype=float) - float(y0)
        for run in _line_runs(lx, ly, float(window_m), pad, min_pts):
            out.append({"coords": run, "label": _fmt_deg(lat), "value": lat, "kind": "parallel"})
    return out


def graticule_order_polylines(reproject: Reproject, *, x0: float, y0: float, window_m: float,
                              lon_min: float, lon_max: float, lat_min: float, lat_max: float,
                              lon_step: float, lat_step: float, lon_sample: float, lat_sample: float,
                              pad: float = 0.0, min_pts: int = 2) -> list[dict]:
    """The full order-frame graticule: meridians + parallels, clipped to the window (the 3D analog of
    graticule.js `selenographic`)."""
    return (meridians_order(reproject, x0=x0, y0=y0, window_m=window_m, lon_min=lon_min, lon_max=lon_max,
                            lat_min=lat_min, lat_max=lat_max, lon_step=lon_step, lat_sample=lat_sample,
                            pad=pad, min_pts=min_pts)
            + parallels_order(reproject, x0=x0, y0=y0, window_m=window_m, lon_min=lon_min, lon_max=lon_max,
                              lat_min=lat_min, lat_max=lat_max, lat_step=lat_step, lon_sample=lon_sample,
                              pad=pad, min_pts=min_pts))


def auto_steps(lon_min: float, lon_max: float, lat_min: float, lat_max: float,
               target_lines: int = 6) -> dict:
    """Pick round-number lon/lat line steps + a finer sample step for a tile's lon/lat span, so a small
    polar tile gets a few visible, labelled lines rather than the whole-Moon 30-degree grid."""
    def _round_step(span, n):
        raw = max(span, 1e-9) / max(1, n)
        # snap to a 1/2/5 x 10^k ladder so labels read as round numbers
        k = math.floor(math.log10(raw)) if raw > 0 else -3
        base = raw / (10 ** k)
        mult = 1 if base < 1.5 else (2 if base < 3.5 else 5)
        return mult * (10 ** k)

    lon_step = _round_step(lon_max - lon_min, target_lines)
    lat_step = _round_step(lat_max - lat_min, target_lines)
    return {"lon_step": lon_step, "lat_step": lat_step,
            "lon_sample": lon_step / 12.0, "lat_sample": lat_step / 12.0}
