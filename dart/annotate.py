"""Annotated-measurement evidence: mark a real image, measure it, and show ALL the math.

Each function returns a STRUCTURED annotation -- the marked image points, the measured quantities, and
the worked equations as text (math_lines) -- so a notebook can draw the overlay and a test can verify
the numbers. The measurements reuse the instrument code (shadow_height, articulated_parallax,
shadow_edge_sigma); this module adds the geometry + the human-readable math for dissertation figures.
Real images only.
"""
from __future__ import annotations

import math

import numpy as np

from dart.articulated_parallax import range_from_pixel_parallax
from dart.shadow_edge_sigma import _erf_edge
from dart.shadow_height import anti_solar_dir, measure_shadow_length_px


def shadow_length_annotation(gray, anchor_uv, sun_az_deg: float, *, m_per_px: float,
                             sun_el_deg: float) -> dict:
    """Mark a rock shadow from its base and work the height: L_m = L_px * m_per_px; H = L_m * tan(e).
    Returns the anchor, the shadow tip pixel, the length, the height, and the math lines."""
    L_px = measure_shadow_length_px(gray, anchor_uv[0], anchor_uv[1], sun_az_deg)
    dx, dy = anti_solar_dir(sun_az_deg)
    tip = (anchor_uv[0] + L_px * dx, anchor_uv[1] + L_px * dy)
    L_m = L_px * m_per_px
    H = L_m * math.tan(math.radians(sun_el_deg))
    return {
        "anchor_uv": (float(anchor_uv[0]), float(anchor_uv[1])), "tip_uv": tip,
        "length_px": float(L_px), "length_m": float(L_m), "height_m": float(H),
        "sun_el_deg": float(sun_el_deg), "m_per_px": float(m_per_px),
        "math_lines": [
            f"L = {L_px:.1f} px x {m_per_px:.3f} m/px = {L_m:.2f} m",
            f"H = L * tan(e) = {L_m:.2f} * tan({sun_el_deg:.1f} deg) = {H:.3f} m",
        ]}


def parallax_range_annotation(*, tip_a_v: float, tip_b_v: float, dh_m: float, fx_px: float) -> dict:
    """Work the articulation-parallax range from two shadow-tip image rows: dv = |v_B - v_A|;
    R = fx * dh / dv; depression angle theta = atan(v / fx). Returns the measured range + math."""
    dv = abs(float(tip_b_v) - float(tip_a_v))
    R = range_from_pixel_parallax(dh_m, dv, fx_px)
    th_a = math.degrees(math.atan2(tip_a_v, fx_px))
    th_b = math.degrees(math.atan2(tip_b_v, fx_px))
    return {
        "shift_px": dv, "range_m": float(R), "dh_m": float(dh_m), "fx_px": float(fx_px),
        "depression_a_deg": th_a, "depression_b_deg": th_b,
        "math_lines": [
            f"dv = |{tip_b_v:.1f} - {tip_a_v:.1f}| = {dv:.1f} px",
            f"theta_A = atan(v/fx) = atan({tip_a_v:.0f}/{fx_px:.0f}) = {th_a:.2f} deg",
            f"R = fx * dh / dv = {fx_px:.0f} * {dh_m:.3f} / {dv:.1f} = {R:.2f} m",
        ]}


def edge_fit_annotation(gray, edge_uv, *, half: int = 6) -> dict:
    """Fit an erf across a shadow edge and report the sub-pixel edge location + width (sigma_edge).
    Returns the profile, the fitted curve, the width, and the math for a measured-edge figure."""
    from scipy.optimize import curve_fit
    g = np.asarray(gray, float)
    if g.ndim == 3:
        g = g.mean(2)
    u, v = int(edge_uv[0]), int(edge_uv[1])
    prof = g[v, u - half:u + half + 1].astype(float)
    lo, hi = float(prof.min()), float(prof.max())
    xx = np.arange(prof.size)
    popt, _ = curve_fit(_erf_edge, xx, prof, p0=[half, 1.0, lo, hi], maxfev=4000)
    x0, width = float(popt[0]), abs(float(popt[1]))
    fit = _erf_edge(xx, *popt)
    return {
        "edge_subpx_u": float(u - half + x0), "width_px": width, "contrast_DN": hi - lo,
        "profile": prof.tolist(), "fit": fit.tolist(), "x_local": xx.tolist(),
        "math_lines": [
            f"erf fit: edge at u = {u - half + x0:.2f} px, contrast {hi - lo:.0f} DN",
            f"sigma_edge = transition width = {width:.2f} px (penumbra + PSF)",
        ]}
