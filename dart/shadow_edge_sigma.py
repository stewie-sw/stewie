"""Measured-edge sigma_n: the REAL shadow-edge localization noise, measured from real imagery.

The earlier shadow-sigma calibration was an ENVELOPE check -- it propagated a MODELLED sub-pixel edge
noise (sigma_edge_px = 1.0) through real DEM cast-shadow geometry. This module measures sigma_edge_px
for real: the dominant localization limit for a shadow boundary is its TRANSITION WIDTH (penumbra +
camera PSF), not a single-row noise/gradient ratio (which is over-optimistic on a sharp step). For each
strong lit->shadow edge it fits an erf and reports the fitted width sigma; the median over many edges
and images is the measured sigma_edge_px. Run on real Chang'e-3 lunar surface imagery (and the Godot
rover render as a sim cross-check). Real images only -- no fabricated edges.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.special import erf


def _erf_edge(x, x0, width, lo, hi):
    return lo + 0.5 * (hi - lo) * (1.0 + erf((x - x0) / (np.sqrt(2.0) * max(width, 1e-3))))


def per_edge_sigma(width_px: float, *, gate_px: float = 1.5) -> float | None:
    """Per-measurement sigma for ONE edge: its own fitted transition width, or None (refuse) when
    the edge is too soft. The measured CE-3 width distribution is bimodal (a sharp population near
    0.35 px and a soft tail to ~3 px), so a global median understates the noise on soft edges; a
    consumer either carries each edge's own fitted width as its sigma_n or refuses past the gate."""
    w = float(width_px)
    return w if 0.0 < w <= float(gate_px) else None


def measure_edge_sigma_px(gray, *, n_edges: int = 120, half: int = 6, min_contrast: float = 60.0,
                          min_grad: float = 20.0) -> dict | None:
    """Measured shadow-edge localization sigma [px] = the median erf transition width of strong
    lit->shadow edges. Returns {sigma_edge_px, n, p25, p75, widths, n_rejected} or None if too
    few edges; widths is the per-edge fitted list (per_edge_sigma consumes it), n_rejected counts
    candidate edges whose fit failed or fell outside the plausible width range."""
    g = np.asarray(gray, float)
    if g.ndim == 3:
        g = g.mean(2)
    h, w = g.shape
    gx = np.abs(g[:, 1:] - g[:, :-1])
    ys, xs = np.where(gx > min_grad)
    if not len(xs):
        return None
    widths = []
    rejected = 0
    for k in np.argsort(gx[ys, xs])[::-1]:
        y, x = int(ys[k]), int(xs[k])
        if x < half + 1 or x >= w - half - 1:
            continue
        prof = g[y, x - half:x + half + 1].astype(float)
        lo, hi = float(prof.min()), float(prof.max())
        if hi - lo < min_contrast or lo > 110.0:          # a real lit->shadow transition (dark side present)
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", OptimizeWarning)
                popt, _ = curve_fit(_erf_edge, np.arange(prof.size), prof,
                                    p0=[half, 1.0, lo, hi], maxfev=2000)
            wfit = abs(float(popt[1]))
        except (RuntimeError, ValueError):
            rejected += 1
            continue
        if 0.2 < wfit < 6.0:
            widths.append(wfit)
        else:
            rejected += 1
        if len(widths) >= n_edges:
            break
    if len(widths) < 5:
        return None
    a = np.array(widths)
    return {"sigma_edge_px": float(np.median(a)), "n": len(a),
            "p25": float(np.percentile(a, 25)), "p75": float(np.percentile(a, 75)),
            "widths": [float(v) for v in a], "n_rejected": rejected}


def calibrate_measured_edge_sigma(image_paths) -> dict:
    """Aggregate the measured edge sigma over a set of REAL images -> the measured sigma_edge_px that
    replaces the modelled 1.0 px envelope assumption."""
    from PIL import Image
    per = []
    rejected = 0
    for p in image_paths:
        try:
            r = measure_edge_sigma_px(Image.open(p).convert("L"))
        except Exception:
            continue
        if r:
            per.append(r["sigma_edge_px"])
            rejected += r["n_rejected"]
    if len(per) < 3:
        raise ValueError(f"too few measurable images ({len(per)}); need real shadow-edge imagery")
    a = np.array(per)
    return {"sigma_edge_px": float(np.median(a)), "n_images": len(per),
            "p25": float(np.percentile(a, 25)), "p75": float(np.percentile(a, 75)),
            "n_edges_rejected": rejected,
            "provenance": "MEASURED erf transition width (penumbra+PSF) of real lit->shadow edges"}
