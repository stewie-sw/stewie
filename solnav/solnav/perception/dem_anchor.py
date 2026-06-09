"""Correlation-based DEM anchoring: recover the horizontal offset between an observed local
elevation patch and the prior REAL DEM via a correlation peak (NCC and/or phase correlation).

This is the correlation analog of the integer-shift SSD search in `solnav.geometry.dem`. Where that
module minimizes mean-removed SSD by an explicit shift loop, this one reads the offset off a single
normalized cross-correlation surface (`cv2.matchTemplate` `TM_CCOEFF_NORMED`, which is the cosine of
the mean-removed patches), and adds a parabolic sub-cell refinement around the peak plus a Fourier
phase-correlation estimator for equal-size patches. The correlation surface itself is a first-class
return (it is what gets visualized and what `confidence` is read from).

Both estimators operate on the OBSERVED patch (the live sensed heightfield, e.g. stereo->local DEM)
against the PRIOR map. Invariant I3 (truth firewall): no ground-truth pose, slip, or terrain-truth
enters here; the only inputs are the observed elevation patch and the stored DEM window. Ground truth
appears only in eval/scoring code that checks the recovered offset, never in this anchoring path.

The mean-removed correlation makes an absolute datum / height offset irrelevant -- only terrain SHAPE
drives the match -- so a constant elevation bias between the observed patch and the DEM cannot bias
the recovered horizontal offset.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class AnchorResult:
    """Result of a correlation-based DEM anchor.

    offset_cells   : integer (dr, dc) of the observed patch centre relative to the DEM window centre
    offset_subcell : parabola-refined (dr, dc) in fractional cells (|refinement| < 1 cell)
    offset_m       : (dy, dx) in metres if posting_m given, else None (dr*posting, dc*posting)
    peak           : correlation value at the peak (TM_CCOEFF_NORMED in [-1, 1])
    confidence     : peak sharpness, peak - second_local_max, clamped to [0, 1] (flat/ambiguous ~0)
    surface        : the full normalized correlation surface (for visualization)
    method         : "ncc"
    """

    offset_cells: tuple[int, int]
    offset_subcell: tuple[float, float]
    offset_m: tuple[float, float] | None
    peak: float
    confidence: float
    surface: np.ndarray
    method: str = "ncc"


def ncc_surface(observed: np.ndarray, dem_patch: np.ndarray) -> np.ndarray:
    """Normalized cross-correlation surface of `observed` slid over `dem_patch`.

    Uses `cv2.matchTemplate` with `TM_CCOEFF_NORMED`: each cell is the zero-mean normalized
    correlation of the observed patch against the DEM window at that shift, i.e. invariant to an
    additive height datum and to a positive multiplicative scale. Output shape is
    (Hd - Ho + 1, Wd - Wo + 1); the centre cell corresponds to zero offset.
    """
    obs = np.ascontiguousarray(observed, dtype=np.float32)
    dem = np.ascontiguousarray(dem_patch, dtype=np.float32)
    if obs.ndim != 2 or dem.ndim != 2:
        raise ValueError("observed and dem_patch must be 2-D")
    if obs.shape[0] > dem.shape[0] or obs.shape[1] > dem.shape[1]:
        raise ValueError("observed patch must fit inside the DEM window")
    return cv2.matchTemplate(dem, obs, cv2.TM_CCOEFF_NORMED)  # type: ignore[attr-defined]


def _parabolic_peak(values: np.ndarray, i: int) -> float:
    """Sub-cell peak position by 3-point parabola fit around index i; returns i + delta, |delta|<1."""
    if i <= 0 or i >= len(values) - 1:
        return float(i)
    ym1, y0, yp1 = float(values[i - 1]), float(values[i]), float(values[i + 1])
    denom = ym1 - 2.0 * y0 + yp1
    if abs(denom) < 1e-12:
        return float(i)
    delta = 0.5 * (ym1 - yp1) / denom
    if not np.isfinite(delta) or abs(delta) >= 1.0:
        return float(i)
    return float(i) + delta


def _second_peak(surface: np.ndarray, pr: int, pc: int) -> float:
    """Largest correlation value outside a 3x3 neighbourhood of the main peak (ambiguity probe)."""
    masked = surface.copy()
    r0, r1 = max(0, pr - 1), min(surface.shape[0], pr + 2)
    c0, c1 = max(0, pc - 1), min(surface.shape[1], pc + 2)
    masked[r0:r1, c0:c1] = -np.inf
    finite = masked[np.isfinite(masked)]
    return float(finite.max()) if finite.size else -1.0


def anchor_offset(observed: np.ndarray, dem_patch: np.ndarray, *, method: str = "ncc",
                  posting_m: float | None = None, min_relief_m: float = 1e-3) -> AnchorResult:
    """Recover the horizontal offset of `observed` within `dem_patch` from the NCC peak.

    The offset is reported relative to the CENTRE of the DEM search window: a return of (3, -2)
    means the observed patch centre sits 3 cells down and 2 cells left of the DEM-window centre.
    A flat observed patch (relief < `min_relief_m`) is rejected as ambiguous rather than locking
    onto a meaningless peak. With `posting_m`, the metric offset (dy, dx) is also returned.
    """
    if method != "ncc":
        raise ValueError(f"unknown method {method!r}; only 'ncc' is supported here")
    obs = np.asarray(observed, dtype=np.float64)
    if obs.size == 0 or float(np.std(obs)) < min_relief_m:
        raise ValueError("observed patch has no relief; correlation anchor is ambiguous")

    surface = ncc_surface(obs, np.asarray(dem_patch, dtype=np.float64))
    pr_np, pc_np = np.unravel_index(int(np.argmax(surface)), surface.shape)
    pr, pc = int(pr_np), int(pc_np)
    peak = float(surface[pr, pc])

    # the search-window centre, in surface coordinates, is zero offset
    centre_r = (surface.shape[0] - 1) / 2.0
    centre_c = (surface.shape[1] - 1) / 2.0
    dr = pr - centre_r
    dc = pc - centre_c

    rr = _parabolic_peak(surface[:, pc], pr) - centre_r
    cc = _parabolic_peak(surface[pr, :], pc) - centre_c

    confidence = float(np.clip(peak - _second_peak(surface, pr, pc), 0.0, 1.0))
    offset_m = (rr * posting_m, cc * posting_m) if posting_m is not None else None

    # integer offset from the sub-pixel estimate with ROUND-HALF-UP: an even surface dimension makes the
    # centre half-integer, so dr/dc are always +/-0.5-fractional and banker's rounding (round(0.5)=0,
    # round(1.5)=2) mis-rounded them inconsistently by a full cell (audit 2026-06-09)
    return AnchorResult(
        offset_cells=(int(np.floor(rr + 0.5)), int(np.floor(cc + 0.5))),
        offset_subcell=(float(rr), float(cc)),
        offset_m=offset_m,
        peak=peak,
        confidence=confidence,
        surface=surface,
    )


def phase_offset(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """Sub-cell shift of `b` relative to `a` via Fourier phase correlation (equal-size patches).

    Returns (dr, dc, response): the shift that maps `a` onto `b` in fractional cells, and the
    normalized phase-correlation response in (0, 1]. Mean-removed + Hann-windowed so a height datum
    and edge wrap-around do not bias the peak. `b == shift(a)` yields (shift, 1.0)-ish.
    """
    fa = np.asarray(a, dtype=np.float32)
    fb = np.asarray(b, dtype=np.float32)
    if fa.shape != fb.shape or fa.ndim != 2:
        raise ValueError("phase correlation requires two equal-size 2-D patches")
    win = cv2.createHanningWindow((fa.shape[1], fa.shape[0]), cv2.CV_32F)
    fa = fa - float(fa.mean())
    fb = fb - float(fb.mean())
    (shift_x, shift_y), response = cv2.phaseCorrelate(fa, fb, win)
    # cv2 returns (x, y) = (col, row) shift of the FIRST image needed to align with the second;
    # b sampled at (r + dr, c + dc) of a -> a must move by (+dr, +dc) to match b -> negate cv2 sign
    return float(-shift_y), float(-shift_x), float(response)
