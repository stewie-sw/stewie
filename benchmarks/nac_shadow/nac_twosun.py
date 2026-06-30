"""Two-Sun self-consistency of the cast-shadow height metric H = L*tan(e) on REAL LROC NAC imagery.

This extends ``benchmarks/nac_shadow`` (Giordano Bruno, a single cluttered fresh crater) to the one
untested, promising regime the prior run flagged: SPARSE MARE boulder fields imaged at two Sun
elevations. The two-Sun idea is the ARGUS Niche-1 core novelty -- if the SAME isolated boulder yields
the same recovered height H from two independent Sun angles, the metric is validated ground-truth-free,
sidestepping the scarce per-boulder-height problem.

It reuses the committed, tested pipeline (``nac_shadow``: georeferenced window I/O, co-registration,
directed shadow length, H = L*tan(e)) and the DART shadow front-end (``dart.shadow_extract``) and adds
only the SPARSE-MARE-specific glue: a gate-R scan over map-projected orthos, an isolated-boulder
detector, and the per-boulder two-Sun measurement.

The two-Sun map-projected coverage that exists for free is overlapping NAC stereo-DTM ortho bundles
imaged at different epochs (e.g. Messier1@e45 + Messier3@e21; Reiner5@e15 + Reinerphot@e47). Each ortho
is an Equirectangular_Moon GeoTIFF, so the same ground point is the same world coordinate in both and
co-registration is automatic. Sun elevation per ortho = 90 - INCIDENCE_ANGLE of its source NAC frame
(from the ODE CDRNAC4 geometry index); GSD from the GeoTIFF transform.

No synthetic data, no fabricated heights. Heights are recovered only from measured shadow pixels and
metadata Sun elevation; where no isolated boulder clears the metric's own gate (R >= 0.30) with a
separable, two-Sun-consistent shadow, the code records the specific blocker rather than inventing one.
"""
# PROVENANCE: STEWIE benchmark over real LROC NAC PDS products (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from scipy.ndimage import maximum_filter, uniform_filter

import nac_shadow as ns
from dart.shadow_extract import extract_shadow_azimuth

# Real, freely-public LROC NAC stereo-DTM ortho bundles (LRO-L-LROC-5-RDR). Each site is a TWO-SUN pair:
# two map-projected orthos of the SAME mare ground at two Sun elevations (90 - incidence). URLs are the
# im-ldi PDS mirror. Plus A12 (Apollo 12 ascent-impact site) as a single-epoch sparse-mare POSITIVE
# CONTROL: it has no usable second Sun (its two orthos are same-day), but it shows the gate CAN clear on
# sparse mare. Geometry from the ODE CDRNAC4 index (incidence/emission, SPICE-derived).
_BASE = "https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/BROWSE/NAC_DTM"
PRODUCTS_TWOSUN: dict[str, dict] = {
    "messier": {
        "site": "Messier / Messier A, Mare Fecunditatis (~1.9 S, 47.7 E)",
        "terrain": "fresh-crater ejecta blanket on mare",
        "low_sun": {"frame": "M165530748", "incidence_deg": 68.11, "sun_elevation_deg": 21.89,
                    "gsd_m_per_px": 0.6, "file": "messier_m3_lowsun_60cm.TIF",
                    "url": f"{_BASE}/MESSIER3/NAC_DTM_MESSIER3_M165530748_60CM.TIF"},
        "high_sun": {"frame": "M1098530546", "incidence_deg": 44.77, "sun_elevation_deg": 45.23,
                     "gsd_m_per_px": 1.3, "file": "messier_m1_highsun_130cm.TIF",
                     "url": f"{_BASE}/MESSIER1/NAC_DTM_MESSIER1_M1098530546_130CM.TIF"},
    },
    "reiner": {
        "site": "Reiner Gamma swirl, Oceanus Procellarum (~7.4 N, 301.0 E)",
        "terrain": "smooth-mare magnetic swirl, densely small-cratered",
        "low_sun": {"frame": "M102536848", "incidence_deg": 73.16, "sun_elevation_deg": 16.84,
                    "gsd_m_per_px": 1.3, "file": "reiner_r5_lowsun15_130cm.TIF",
                    "url": f"{_BASE}/REINER5/NAC_DTM_REINER5_M102536848_130CM.TIF"},
        "high_sun": {"frame": "M1167547085", "incidence_deg": 43.29, "sun_elevation_deg": 46.71,
                     "gsd_m_per_px": 1.2, "file": "reiner_rp_highsun47_120cm.TIF",
                     "url": f"{_BASE}/REINERPHOT/NAC_DTM_REINERPHOT_M1167547085_120CM.TIF"},
    },
    "a12_control": {
        "site": "Apollo 12 ascent-stage impact site, Mare Cognitum (~3.9 S, 338.7 E)",
        "terrain": "sparse mare (POSITIVE CONTROL; single epoch -- no usable second Sun)",
        "high_sun": {"frame": "M1243793524", "incidence_deg": 50.49, "sun_elevation_deg": 39.51,
                     "gsd_m_per_px": 1.1, "file": "a12_o1_110cm.TIF",
                     "url": f"{_BASE}/A12LMAS/NAC_DTM_A12LMAS_M1243793524_110CM.TIF"},
    },
}

GATE_R = 0.30  # the metric's own front-end azimuth gate (dart.shadow_extract.extract_shadow_azimuth)


@dataclass(frozen=True)
class GateHit:
    """One sampled crop scored by the DART shadow-azimuth gate, with its georeferenced location."""

    confidence_R: float
    n_support: int
    shadow_az_deg: float
    col: int
    row: int
    world_x: float
    world_y: float
    surround_std: float


def gate_on_crop(crop: np.ndarray) -> tuple[float, int, float]:
    """Run the DART shadow-azimuth front-end on a crop (gate disabled so we read the raw score).

    Returns ``(R, n_support, shadow_az_deg)``; ``(-1.0, 0, nan)`` if the crop has too little structure
    for the front-end (too few shadow-boundary pixels)."""
    try:
        obs = extract_shadow_azimuth(crop.astype(np.float32), gate=False)
    except Exception:
        return -1.0, 0, float("nan")
    return float(obs.confidence), int(obs.n_support), float(obs.z_shadow_image_deg)


def scan_gate_windows(arr: np.ndarray, transform: rasterio.Affine, *, win: int = 256,
                      step: int = 200, min_std: float = 6.0) -> list[GateHit]:
    """Slide a window over a map-projected ortho and score each with the gate; returns hits sorted by R.

    A high R means shadow edges in the window point one consistent way (the isolated-boulder signature
    the metric wants); a low R means clutter (many features at varied orientations). Used to ask whether
    ANY window on a sparse-mare ortho clears ``GATE_R``."""
    hits: list[GateHit] = []
    h, w = arr.shape
    for y in range(0, h - win, step):
        for x in range(0, w - win, step):
            c = arr[y:y + win, x:x + win]
            if (c > 0).mean() < 0.98:
                continue
            cf = c.astype(np.float32)
            std = float(cf.std())
            if std < min_std:
                continue
            r, n, az = gate_on_crop(cf)
            if r < 0:
                continue
            wx, wy = transform * (x + win / 2.0, y + win / 2.0)
            hits.append(GateHit(r, n, az, x, y, float(wx), float(wy), round(std, 1)))
    hits.sort(key=lambda hh: hh.confidence_R, reverse=True)
    return hits


def detect_isolated_boulders(arr: np.ndarray, transform: rasterio.Affine, *, crop: int = 80,
                             smooth_max: float = 8.0, max_eval: int = 600) -> list[GateHit]:
    """Find bright compact peaks on SMOOTH surroundings (isolated-boulder candidates) and gate each tight
    crop. This is the proposal's literal design: an isolated boulder whose crop clears ``GATE_R``.

    A boulder is a bright local maximum well above the local mean; ``smooth_max`` bounds the surrounding
    roughness (so we keep boulders on smooth mare, not features inside crater rubble). Returns the
    gated candidates sorted by R."""
    a = arr.astype(np.float32)
    h, w = a.shape
    valid = a > 0
    loc_mean = uniform_filter(a, 31)
    loc_std = np.sqrt(np.maximum(uniform_filter(a * a, 31) - loc_mean ** 2, 0.0))
    big_std = uniform_filter(loc_std, 121)
    contrast = a - loc_mean
    peaks = (a == maximum_filter(a, 9)) & (contrast > 4.0 * np.maximum(loc_std, 4.0)) & valid & (big_std < smooth_max)
    ys, xs = np.where(peaks)
    order = np.argsort(-(contrast[ys, xs] / np.maximum(big_std[ys, xs], 3.0)))
    out: list[GateHit] = []
    ev = 0
    for idx in order:
        if ev >= max_eval:
            break
        y, x = int(ys[idx]), int(xs[idx])
        if y < crop or y >= h - crop or x < crop or x >= w - crop:
            continue
        c = a[y - crop:y + crop, x - crop:x + crop]
        if (c > 0).mean() < 0.99:
            continue
        ev += 1
        r, n, az = gate_on_crop(c)
        wx, wy = transform * (x + 0.5, y + 0.5)
        out.append(GateHit(r, n, az, x, y, float(wx), float(wy), round(float(big_std[y, x]), 1)))
    out.sort(key=lambda hh: hh.confidence_R, reverse=True)
    return out


def _refine_peak(a: np.ndarray, rc: tuple[int, int], rad: int = 8) -> tuple[int, int]:
    r, c = rc
    r0, r1 = max(0, r - rad), min(a.shape[0], r + rad + 1)
    c0, c1 = max(0, c - rad), min(a.shape[1], c + rad + 1)
    sub = a[r0:r1, c0:c1]
    j = int(np.argmax(sub))
    dr, dc = divmod(j, sub.shape[1])
    return r0 + dr, c0 + dc


def _local_crop(ds: rasterio.DatasetReader, wx: float, wy: float, half_px: int) -> tuple[np.ndarray, float]:
    col, row = ~ds.transform * (wx, wy)
    c0, r0 = int(round(col)) - half_px, int(round(row)) - half_px
    win = rasterio.windows.Window(c0, r0, 2 * half_px, 2 * half_px)
    a = ds.read(1, window=win).astype(np.float32)
    return a, float(ds.transform.a)


def measure_two_sun(ds_lo: rasterio.DatasetReader, e_lo_deg: float,
                    ds_hi: rasterio.DatasetReader, e_hi_deg: float,
                    world_xy: tuple[float, float], *, half_px: int = 60) -> dict:
    """Measure a candidate boulder at one world point in BOTH Sun-angle orthos and recover H each way.

    For each frame: read a local crop, get the frame's anti-solar azimuth from the gate, refine the
    bright boulder peak, walk the shadow length L along that azimuth (reusing
    ``nac_shadow.directed_shadow_length_m``), and recover H = L*tan(e). Reports the per-frame gate R,
    the measured L and H, and the two-Sun spread. A boulder is BRIGHT (positive ``peak_over_bg``) in
    both frames; ``H_lo ~ H_hi`` validates. No height is reported where the shadow is unmeasurable
    (L = 0)."""
    out: dict[str, object] = {"world_xy": [float(world_xy[0]), float(world_xy[1])]}
    heights: list[float] = []
    for name, ds, elev in (("low_sun", ds_lo, e_lo_deg), ("high_sun", ds_hi, e_hi_deg)):
        a, gsd = _local_crop(ds, world_xy[0], world_xy[1], half_px)
        r, n, az = gate_on_crop(a)
        pr, pc = _refine_peak(a, (half_px, half_px))
        bg = float(np.median(a[a > 0])) if (a > 0).any() else 0.0
        peak = float(a[pr, pc])
        length_m = ns.directed_shadow_length_m(a, (pr, pc), az, gsd) if math.isfinite(az) else 0.0
        height_m = ns.recover_height_m(length_m, elev) if length_m > 0 else 0.0
        if height_m > 0:
            heights.append(height_m)
        out[name] = {"sun_elevation_deg": elev, "gate_R": round(r, 3),
                     "shadow_az_deg": round(az, 1) if math.isfinite(az) else None,
                     "peak_over_bg": round(peak - bg, 1), "shadow_len_m": round(length_m, 2),
                     "H_m": round(height_m, 2), "gsd_m_per_px": round(gsd, 3)}
    if len(heights) == 2:
        spread = abs(heights[0] - heights[1])
        mean = 0.5 * (heights[0] + heights[1])
        out["two_sun"] = {"H_low_m": round(heights[0], 2), "H_high_m": round(heights[1], 2),
                          "abs_spread_m": round(spread, 2),
                          "pct_spread": round(100.0 * spread / mean, 1) if mean > 0 else None,
                          "both_measurable": True}
    else:
        out["two_sun"] = {"both_measurable": False,
                          "note": "shadow not separately measurable in both frames (L=0 in >=1 frame)"}
    return out


def coreg_corr(path_lo: str, path_hi: str, box: ns.WorldBox, *, shape: tuple[int, int] = (600, 600)) -> float:
    """Thin wrapper over the committed ``nac_shadow.coregistration_highpass_corr`` for a site overlap box."""
    return ns.coregistration_highpass_corr(path_lo, path_hi, box, shape=shape)
