"""Full-resolution heightfield sampler for the standalone 3D terrain viewer (viz.stewie.space).

The cockpit's /dem/heightfield decimates the work-area to n<=257 samples over a small window -- fine for
the in-cockpit dry-run, too coarse to SEE a site. This module samples a site's REAL LOLA DEM at its NATIVE
cell resolution over an order-frame window, with an optional level-of-detail (LOD) stride so an oversized
window can never blow up the browser mesh. It is a PURE function of the DEM array + the window params (no
I/O, no fabricated terrain), so it is unit-testable without a bundle on disk.

Frame + registration: the window is [x0, x0+window_m] x [y0, y0+window_m] in TILE-PIXEL metres (the same
frame /dem/site_lonlat and latlon_to_dem_origin use -- col = x/cell). The column/row index formula is
byte-identical to /dem/workarea.png (cols = clip(round((x0+xs)/cell), 0, W-1)), so an analysis raster
rendered over the SAME window registers cell-for-cell with this height grid when draped as a texture.
"""
from __future__ import annotations

import numpy as np


def full_grid_spec(width: int, height: int, cell_m: float, x0: float, y0: float,
                   window_m: float, max_dim: int = 2048) -> dict:
    """Resolve the sampling plan for a full-resolution square window over a (width x height) DEM grid.

    Returns the clamped window origin/extent, the native + emitted grid dimension, the emitted vertex
    spacing, and the exact integer row/col index arrays into the DEM. PURE: depends only on the grid
    geometry, not the height values, so the registration contract can be tested without a DEM on disk.

    - ``window_m`` is clamped to [2*cell, min tile extent]; the default caller passes the full native tile.
    - ``x0``/``y0`` (tile-pixel metres) are clamped so the square window stays on the tile.
    - ``max_dim`` caps the emitted grid dimension: a native window larger than ``max_dim`` is decimated to
      exactly ``max_dim`` samples across (the LOD path). The window EXTENT is unchanged, so a draped raster
      over the same extent still registers via UV; only vertex density drops.
    """
    width, height = int(width), int(height)
    cell_m = float(cell_m)
    if width < 2 or height < 2 or not (cell_m > 0):
        raise ValueError(f"degenerate DEM grid {width}x{height} @ cell {cell_m}")
    max_dim = max(2, int(max_dim))
    tile_x = (width - 1) * cell_m
    tile_y = (height - 1) * cell_m
    win = float(window_m)
    win = max(2.0 * cell_m, min(win, tile_x, tile_y))          # square window must fit both axes
    x0 = min(max(float(x0), 0.0), tile_x - win)
    y0 = min(max(float(y0), 0.0), tile_y - win)
    native_n = max(2, int(round(win / cell_m)) + 1)            # /dem/workarea.png's native px count
    n = native_n if native_n <= max_dim else max_dim           # LOD decimation to at most max_dim
    stride = (native_n - 1) / (n - 1)                          # native cells skipped per emitted sample
    xs = np.linspace(0.0, win, n)                              # order-local metres along the window
    cols = np.clip(np.round((x0 + xs) / cell_m).astype(int), 0, width - 1)
    rows = np.clip(np.round((y0 + xs) / cell_m).astype(int), 0, height - 1)
    step_m = win / (n - 1)
    return {"x0": x0, "y0": y0, "window_m": win, "cell_m": cell_m, "n": n, "native_n": native_n,
            "step_m": step_m, "stride": stride, "cols": cols, "rows": rows,
            "width": width, "height": height, "lod": native_n > max_dim}


def heightfield_full(Z: np.ndarray, cell_m: float, x0: float, y0: float, window_m: float,
                     max_dim: int = 2048) -> tuple[np.ndarray, dict]:
    """Sample ``Z`` (real DEM, [row=y(North), col=x(East)]) over the window -> (float32 grid, meta).

    The grid is row-major y-then-x (grid[j, i] at order-local x = i*step_m East, y = j*step_m North), the
    SAME convention as /dem/heightfield and three3d.js, so the existing mesh builder consumes it unchanged.
    """
    Zf = np.asarray(Z)
    H, W = Zf.shape[:2]
    spec = full_grid_spec(W, H, cell_m, x0, y0, window_m, max_dim)
    grid = np.asarray(Zf, dtype=np.float32)[np.ix_(spec["rows"], spec["cols"])]
    meta = {
        "x0": round(spec["x0"], 3), "y0": round(spec["y0"], 3),
        "window_m": round(spec["window_m"], 3), "cell_m": spec["cell_m"],
        "n": spec["n"], "native_n": spec["native_n"], "step_m": round(spec["step_m"], 6),
        "stride": round(spec["stride"], 6), "lod": bool(spec["lod"]),
        "width": spec["width"], "height": spec["height"],
        "z_min": float(grid.min()), "z_max": float(grid.max()),
    }
    return grid, meta


def native_full_window_m(width: int, height: int, cell_m: float) -> float:
    """The largest square window that samples the whole tile at native resolution (the Haworth default:
    the entire 10 km LOLA tile). ``(min(W,H)-1)*cell`` so round(win/cell)+1 == the tile dimension exactly
    (no clamped edge-duplication)."""
    return (min(int(width), int(height)) - 1) * float(cell_m)


def suggested_layer_px(kind: str, n: int) -> int:
    """A bounded raster resolution for the draped analysis layer over the window. The drape is a TEXTURE
    (UV 0..1 over the window extent) so it need not match the mesh vertex count; the expensive horizon-sweep
    kinds (psr/cost/blocking) render small, cheap gradient kinds render larger. Never exceeds the mesh ``n``
    (no fabricated detail beyond the vertices) nor a hard cap."""
    cap = 384 if kind in ("psr", "cost", "blocking") else 1024
    return max(2, min(int(n), cap))
