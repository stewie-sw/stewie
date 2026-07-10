"""Numbered tile grid over the real DEM footprint (100 m tiles + 25 m display sub-graticule).

Pure geometry, built from a :class:`~stewie.dataset.dem_source.DemGeometry` (bounds + cell + CRS) --
no pixel load. Row 0 is at the top (north, max stereo-Y), matching the north-up raster; the linear
``index = row * n_cols + col`` and ``tile_id = "rNNNcNNN"`` are deterministic. Each tile carries its
projected extent (IAU_2015:30135 metres), center + 4-corner selenographic lat/lon (via the shared
transform reused from ``site_dem``), area, ``valid_frac`` (geometric fraction inside the footprint),
and the pixel window a stats pass reads. The 25 m sub-graticule is a DISPLAY concern (minor gridlines
inside the 100 m tiles) and is deliberately separate from the training-chip overlap in ``splits``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from stewie.dataset.dem_source import DemGeometry, selenographic_transformers


@dataclass(frozen=True)
class Tile:
    """One numbered tile (or a sliding chip): projected extent + lat/lon + pixel window."""

    index: int
    row: int
    col: int
    tile_id: str
    x0: float          # west  edge [m, 30135]
    y0: float          # south edge [m]
    x1: float          # east  edge [m]
    y1: float          # north edge [m]
    tile_m: float
    sub_m: float
    center_lat: float
    center_lon: float
    corners_latlon: tuple[tuple[float, float], ...]   # (lat, lon) for NW, NE, SE, SW
    area_m2: float
    valid_frac: float                                  # clamped tile area / nominal tile area
    px_row0: int
    px_col0: int
    px_h: int
    px_w: int
    kind: str = "tile"
    split: str | None = None

    def corner_ring_lonlat(self) -> list[list[float]]:
        """The closed GeoJSON ring [lon, lat] for NW, NE, SE, SW, NW (first == last)."""
        nw, ne, se, sw = self.corners_latlon
        ring = [[nw[1], nw[0]], [ne[1], ne[0]], [se[1], se[0]], [sw[1], sw[0]]]
        ring.append(ring[0])
        return ring


@dataclass(frozen=True)
class TileSpec:
    """A tile/chip's identity + projected extent, before lat/lon + pixel-window resolution."""

    index: int
    row: int
    col: int
    tile_id: str
    x0: float
    y0: float
    x1: float
    y1: float


def build_tiles(geometry: DemGeometry, specs: list[TileSpec], *, tile_m: float, sub_m: float,
                kind: str = "tile", split: str | None = None) -> list[Tile]:
    """Resolve a batch of :class:`TileSpec` extents into full :class:`Tile` records.

    One vectorized pyproj inverse transform for the whole batch (center + 4 corners per spec), so a
    14k-tile grid or a 17k-chip train band is a single projection call, not per-tile. Shared by the
    grid build and the sliding-chip build in ``splits`` so both take the identical lat/lon + pixel-
    window path.
    """
    if not specs:
        return []
    cell = geometry.cell_m
    xs: list[float] = []
    ys: list[float] = []
    for s in specs:
        cx, cy = (s.x0 + s.x1) / 2.0, (s.y0 + s.y1) / 2.0
        xs += [cx, s.x0, s.x1, s.x1, s.x0]     # center, NW, NE, SE, SW
        ys += [cy, s.y1, s.y1, s.y0, s.y0]
    _fwd, inv = selenographic_transformers()
    lon, lat = inv.transform(np.asarray(xs), np.asarray(ys))
    lon = np.asarray(lon, dtype=float).reshape(-1, 5)
    lat = np.asarray(lat, dtype=float).reshape(-1, 5)

    out: list[Tile] = []
    for i, s in enumerate(specs):
        area = (s.x1 - s.x0) * (s.y1 - s.y0)
        corners = (
            (float(lat[i, 1]), float(lon[i, 1])),   # NW
            (float(lat[i, 2]), float(lon[i, 2])),   # NE
            (float(lat[i, 3]), float(lon[i, 3])),   # SE
            (float(lat[i, 4]), float(lon[i, 4])),   # SW
        )
        out.append(Tile(
            index=s.index, row=s.row, col=s.col, tile_id=s.tile_id,
            x0=float(s.x0), y0=float(s.y0), x1=float(s.x1), y1=float(s.y1),
            tile_m=float(tile_m), sub_m=float(sub_m),
            center_lat=float(lat[i, 0]), center_lon=float(lon[i, 0]),
            corners_latlon=corners,
            area_m2=float(area), valid_frac=float(area / (tile_m * tile_m)),
            px_row0=int(round((geometry.y_max - s.y1) / cell)),
            px_col0=int(round((s.x0 - geometry.x_min) / cell)),
            px_h=int(round((s.y1 - s.y0) / cell)),
            px_w=int(round((s.x1 - s.x0) / cell)),
            kind=kind, split=split,
        ))
    return out


class TileGrid:
    """Deterministic numbered grid of ``tile_m`` tiles over ``geometry``'s projected footprint."""

    def __init__(self, geometry: DemGeometry, *, tile_m: float = 100.0, sub_m: float = 25.0):
        if not (tile_m > 0.0 and sub_m > 0.0):
            raise ValueError(f"tile_m ({tile_m}) and sub_m ({sub_m}) must be > 0")
        if sub_m > tile_m:
            raise ValueError(f"sub_m ({sub_m}) must be <= tile_m ({tile_m})")
        self.geometry = geometry
        self.tile_m = float(tile_m)
        self.sub_m = float(sub_m)
        self.n_cols = int(math.ceil(geometry.extent_x_m / tile_m))
        self.n_rows = int(math.ceil(geometry.extent_y_m / tile_m))
        self.tiles: list[Tile] = self._build()

    @property
    def n_tiles(self) -> int:
        return len(self.tiles)

    def tile(self, index: int) -> Tile:
        return self.tiles[index]

    def tile_at(self, row: int, col: int) -> Tile:
        return self.tiles[row * self.n_cols + col]

    # -- geometry construction (vectorized lat/lon: one pyproj call for the whole grid) -----------
    def _build(self) -> list[Tile]:
        specs = []
        for r in range(self.n_rows):
            for c in range(self.n_cols):
                x0 = self.geometry.x_min + c * self.tile_m
                x1 = min(self.geometry.x_min + (c + 1) * self.tile_m, self.geometry.x_max)
                y1 = self.geometry.y_max - r * self.tile_m
                y0 = max(self.geometry.y_max - (r + 1) * self.tile_m, self.geometry.y_min)
                specs.append(TileSpec(
                    index=r * self.n_cols + c, row=r, col=c, tile_id=f"r{r:03d}c{c:03d}",
                    x0=x0, y0=y0, x1=x1, y1=y1))
        return build_tiles(self.geometry, specs, tile_m=self.tile_m, sub_m=self.sub_m)

    # -- 25 m display sub-graticule (minor gridlines inside the 100 m tiles) ----------------------
    def sub_graticule_lines(self) -> dict:
        """Projected positions of the minor (``sub_m``) and major (``tile_m``) gridlines.

        A DISPLAY concern only -- the finer graticule the QWC2 mission layer / 3D viewer draw inside
        each tile. NOT the training-chip overlap (see ``splits``). Uses the same 100 m-major /
        finer-minor scheme as ``stewie.terrain.graticule_order``, driven off the DEM origin."""
        g = self.geometry

        def _lines(lo: float, hi: float, step: float) -> list[float]:
            n = int(math.floor((hi - lo) / step + 1e-9))
            return [lo + k * step for k in range(n + 1)]

        return {
            "tile_m": self.tile_m,
            "sub_m": self.sub_m,
            "x_lines_m": _lines(g.x_min, g.x_max, self.sub_m),
            "y_lines_m": _lines(g.y_min, g.y_max, self.sub_m),
            "x_major_m": _lines(g.x_min, g.x_max, self.tile_m),
            "y_major_m": _lines(g.y_min, g.y_max, self.tile_m),
        }
