"""Real lunar DEM I/O + scan-to-DEM registration (the global map tier).

Loads a dustgym/LOLA `.rf32` heightmap + metadata, crops a metric window (e.g.,
100 x 100 m on the south pole), and registers a local height patch against the DEM
by a brute-force shift search (the localization mechanism in algorithm A4/A5). Real
data; no fabricated terrain.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/geometry/dem.py, 2026-06-09 (M2)
from __future__ import annotations

import json
import os

import numpy as np


def load_dem(dem_dir: str):
    """Load heightmap.rf32 + metadata.json. Returns (height[H,W], posting_m, meta)."""
    meta = json.load(open(os.path.join(dem_dir, "metadata.json")))
    h = np.fromfile(os.path.join(dem_dir, "heightmap.rf32"), dtype="<f4")
    n = int(round(len(h) ** 0.5))
    if n * n != len(h):
        grid = meta.get("grid", {})
        n = int(grid.get("rows") or grid.get("height") or n)
    H = h.reshape(n, n)
    posting = (meta.get("base_cell_m") or meta.get("fine_cell_m")
               or (meta.get("grid", {}) or {}).get("cell_m"))
    if posting is None:
        wb = meta.get("world_bounds_m", {})
        span = wb.get("x_max", n) - wb.get("x_min", 0) if wb else n
        posting = span / n
    return H, float(posting), meta


def crop_meters(height: np.ndarray, posting_m: float, size_m: float,
                center_rc=None):
    """Crop a size_m x size_m window centered on (row, col) cell index (default the
    array center). Returns (patch, (r0, c0), n_cells)."""
    n = max(1, int(round(size_m / posting_m)))
    H, W = height.shape
    if center_rc is None:
        cr, cc = H // 2, W // 2
    else:
        cr, cc = int(center_rc[0]), int(center_rc[1])
    r0 = int(np.clip(cr - n // 2, 0, max(0, H - n)))
    c0 = int(np.clip(cc - n // 2, 0, max(0, W - n)))
    return height[r0:r0 + n, c0:c0 + n].copy(), (r0, c0), n


def register_to_dem(local_patch: np.ndarray, dem_patch: np.ndarray,
                    search_radius_cells: int = 8, min_valid_frac: float = 0.5,
                    min_relief_m: float = 1e-3):
    """Brute-force scan-to-DEM: slide local_patch over dem_patch within +/- radius, return
    (best_dr, best_dc, best_rmse). Overlap compared after removing a per-shift mean offset
    (height is relative). NaN-SAFE (HIGH-06): LOLA PSR tiles carry NaN no-data, so means/RMSE use
    nanmean over the FINITE overlap, shifts with < min_valid_frac finite cells are skipped, and a
    flat patch (relief < min_relief_m, MED-04) is rejected as ambiguous instead of silently locking
    onto the first scanned shift."""
    lp = local_patch.astype(np.float64)
    dp = dem_patch.astype(np.float64)
    lh, lw = lp.shape
    if np.isfinite(lp).sum() == 0 or np.nanstd(lp) < min_relief_m:
        raise ValueError("local patch has no relief / no valid cells; DEM registration is ambiguous")
    best = (0, 0, np.inf)
    for dr in range(-search_radius_cells, search_radius_cells + 1):
        for dc in range(-search_radius_cells, search_radius_cells + 1):
            r0, c0 = dr + (dp.shape[0] - lh) // 2, dc + (dp.shape[1] - lw) // 2
            if r0 < 0 or c0 < 0 or r0 + lh > dp.shape[0] or c0 + lw > dp.shape[1]:
                continue
            sub = dp[r0:r0 + lh, c0:c0 + lw]
            # height offset estimated on the COMMON finite overlap (per-array nanmeans over different
            # NaN sets bias the residual and can select a wrong shift -- audit 2026-06-09)
            d = lp - sub
            valid = np.isfinite(d)
            if valid.mean() < min_valid_frac:
                continue
            dv = d[valid]
            rmse = float(np.sqrt(np.mean((dv - dv.mean()) ** 2)))
            if rmse < best[2]:
                best = (dr, dc, rmse)
    if not np.isfinite(best[2]):
        raise ValueError("no registration candidate fit inside the DEM patch (patch too small for the "
                         "search radius?) -- a silent (0,0) fix would be fabricated (audit M17)")
    return best
