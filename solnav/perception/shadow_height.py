"""Shadow-based rock height -- the south-pole height sensor.

At the lunar south pole the sun grazes at e ~ 0-5 deg, so every rock casts a long shadow whose length L
encodes its height: H = L * tan(e). This measures L by walking the ANTI-SOLAR ray from a detected rock
and counting the contiguous shadowed (dark) pixels, then converts to metres via the known solar elevation
and image GSD. Where the sun is known and grazing this can beat stereo (it works in deep shadow and needs
no disparity). Developed against the faithful dustgym grazing-sun renders (known sun + known clast height);
applies to real NAC/descent imagery where the solar geometry is in the metadata. No synthetic data.

VALIDATION STATUS (honest, definitive): the formula H = L*tan(e) is correct geometry, but per-rock height
could NOT be validated on the dustgym renders by ANY measurement tried -- 1-D ray-walk, 2-D mask
segmentation (masking.detect_shadow_mask), clear-shadow-path filtering, at sun 6 deg AND 25 deg: Pearson
r(est, true) stays ~ -0.1..-0.2 (no correlation), and the empirically recovered shadow azimuth is UNSTABLE
across methods (220/270/310 deg). That instability is the tell: the rendered shadow signal is too weak /
inconsistent relative to terrain darkness for per-rock recovery -- a RENDER/DATA limitation, not just the
algorithm. Conclusion: the method needs imagery with strong, clean grazing-sun shadow contrast (real
ShadowCam PSR / NAC at known low sun), not these renders. Until validated on such data, estimate_height_m
is a REGIME cue only, NOT a calibrated height; the VALIDATED size sources are stereo (obstacle_map) and
DEM residual (dem_cross).
"""
from __future__ import annotations

import math

import numpy as np

from . import rock_taxonomy


def anti_solar_dir(sun_azimuth_deg: float) -> tuple:
    """Unit image-plane direction the shadow points (opposite the sun). Azimuth is measured from +x
    (image right) toward +y (image down); the renderer/metadata fixes the convention."""
    a = math.radians(sun_azimuth_deg + 180.0)
    return math.cos(a), math.sin(a)


def measure_shadow_length_px(gray, u: float, v: float, sun_azimuth_deg: float, *, dark_frac: float = 0.55,
                             max_len_px: int = 300, start_px: int = 2) -> float:
    """Walk the anti-solar ray from (u, v); the shadow is the contiguous run of pixels darker than
    dark_frac x the rock's local brightness. Returns the shadow length in px (0 if none)."""
    h, w = gray.shape
    dx, dy = anti_solar_dir(sun_azimuth_deg)
    r = 6
    x0, x1 = max(0, int(u) - r), min(w, int(u) + r)
    y0, y1 = max(0, int(v) - r), min(h, int(v) + r)
    ref = float(np.median(gray[y0:y1, x0:x1])) if (x1 > x0 and y1 > y0) else float(gray.mean())
    thr = dark_frac * ref
    length = 0
    gap = 0
    for s in range(start_px, max_len_px):
        x = int(round(u + dx * s)); y = int(round(v + dy * s))
        if not (0 <= x < w and 0 <= y < h):
            break
        if gray[y, x] < thr:
            length = s; gap = 0
        elif length > 0:
            gap += 1
            if gap > 2:                       # exited the shadow
                break
    return float(length)


def estimate_height_m(gray, u: float, v: float, *, sun_azimuth_deg: float, sun_elevation_deg: float,
                      m_per_px: float, **kw):
    """Rock height from its shadow: (height_m or None, shadow_length_px). None when no shadow is found."""
    length_px = measure_shadow_length_px(gray, u, v, sun_azimuth_deg, **kw)
    if length_px <= 0:
        return None, 0.0
    return rock_taxonomy.shadow_height_m(length_px * m_per_px, sun_elevation_deg), length_px
