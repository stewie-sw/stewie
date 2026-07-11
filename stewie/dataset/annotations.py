"""Per-tile annotations: lat/lon + per-layer real-pixel statistics, exported as GeoJSON.

Each tile's record carries its projected extent, center + 4-corner selenographic lat/lon, split
label, geometric ``valid_frac``, and a PER-LAYER statistics section. The layers are REAL producers
over a REAL pixel window (no fabricated stats):

  * ``dem``   -- elevation min/max/mean/std over the window (NoData excluded);
  * ``slope`` -- ``stewie.terrain.site_dem.slope_deg_map`` (gradient magnitude -> degrees);
  * ``aspect``-- ``stewie.server.gis_layers.aspect_deg`` (downslope azimuth [deg]).

Provenance records the source DEM, its citation, the projected CRS, and the R=1737400 m datum read
from the real GeoTIFF GeoKeys. GeoJSON coordinates are selenographic [lon, lat] on that sphere; the
FeatureCollection documents the non-WGS84 CRS in a ``crs`` member.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from stewie.dataset.dem_source import DemGeometry, WindowReader, geographic_crs_authority
from stewie.dataset.tile_grid import Tile

# The real DEM's published provenance (from the PGDA Product 78 metadata / bundle dem_provenance).
_CITATION = ("Barker et al. 2021 (Planet. Space Sci. 203:105119); "
             "Mazarico et al. 2011 (Icarus 211:1066)")
_DEFAULT_LAYERS = ("dem", "slope", "aspect")


@dataclass(frozen=True)
class LayerStats:
    """Summary statistics of one real co-registered layer over a tile's pixel window."""

    name: str
    min: float
    max: float
    mean: float
    std: float
    count: int          # finite (non-NoData) pixels the stats were computed over
    valid_frac: float   # finite / total pixels in the window


@dataclass
class TileAnnotation:
    tile_id: str
    index: int
    row: int
    col: int
    kind: str
    split: str | None
    extent_m: tuple[float, float, float, float]        # (x0, y0, x1, y1) in 30135 metres
    center_latlon: tuple[float, float]                 # (lat, lon)
    corners_latlon: tuple[tuple[float, float], ...]    # NW, NE, SE, SW (lat, lon)
    corner_ring_lonlat: list[list[float]]              # closed GeoJSON ring [lon, lat]
    tile_m: float
    sub_m: float
    valid_frac: float                                  # geometric footprint fraction
    area_m2: float
    px_window: tuple[int, int, int, int]               # (row0, col0, h, w)
    layers: dict[str, LayerStats] = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)


def _stats(name: str, arr: np.ndarray) -> LayerStats:
    """Finite-only min/max/mean/std of a layer window (NoData -> NaN already applied)."""
    a = np.asarray(arr, dtype=float)
    finite = np.isfinite(a)
    n = int(finite.sum())
    total = int(a.size)
    if n == 0:
        nan = float("nan")
        return LayerStats(name, nan, nan, nan, nan, 0, 0.0)
    vals = a[finite]
    return LayerStats(name=name, min=float(vals.min()), max=float(vals.max()),
                      mean=float(vals.mean()), std=float(vals.std()),
                      count=n, valid_frac=float(n / total) if total else 0.0)


def _layer_arrays(z: np.ndarray, cell_m: float, layers) -> dict[str, np.ndarray]:
    """Materialize the requested real co-registered layers from the DEM window ``z``."""
    from stewie.server.gis_layers import aspect_deg
    from stewie.terrain.site_dem import slope_deg_map

    out: dict[str, np.ndarray] = {}
    zf = np.asarray(z, dtype=float)
    can_grad = zf.shape[0] >= 2 and zf.shape[1] >= 2      # np.gradient needs >= 2 along each axis
    for name in layers:
        if name == "dem":
            out["dem"] = zf
        elif name == "slope":
            out["slope"] = slope_deg_map(zf, cell_m) if can_grad else np.full_like(zf, np.nan)
        elif name == "aspect":
            out["aspect"] = aspect_deg(zf, cell_m) if can_grad else np.full_like(zf, np.nan)
        else:
            raise ValueError(f"unknown layer {name!r}; known: dem, slope, aspect")
    return out


def _provenance(geometry: DemGeometry, tile_m: float, sub_m: float) -> dict:
    import os
    return {
        "source_dem": os.path.basename(geometry.path),
        "source_path": geometry.path,
        "crs": geometry.crs_authority,                       # projected frame (IAU_2015:30135)
        "geographic_crs": geographic_crs_authority(),        # lon/lat frame for the coordinates
        "sphere_radius_m": geometry.radius_m,                # R=1737400 m, from the real GeoKeys
        "datum": f"R={geometry.radius_m:g} m sphere (IAU_2015 Moon ocentric)",
        "frame": "south polar stereographic (IAU_2015:30135)",
        "citation": _CITATION,
        "tile_m": float(tile_m),
        "sub_m": float(sub_m),
        "license_basis": "U.S. Government work (NASA GSFC PGDA); public-domain / CC0-compatible.",
    }


def tile_annotation(tile: Tile, reader: WindowReader, geometry: DemGeometry, *,
                    split: str | None = None, layers=_DEFAULT_LAYERS) -> TileAnnotation:
    """Annotate one tile: read its real pixel window, compute per-layer stats, record provenance."""
    z = reader(tile.px_row0, tile.px_col0, tile.px_h, tile.px_w)
    arrays = _layer_arrays(z, geometry.cell_m, layers)
    layer_stats = {name: _stats(name, arr) for name, arr in arrays.items()}
    return TileAnnotation(
        tile_id=tile.tile_id, index=tile.index, row=tile.row, col=tile.col, kind=tile.kind,
        split=split if split is not None else tile.split,
        extent_m=(tile.x0, tile.y0, tile.x1, tile.y1),
        center_latlon=(tile.center_lat, tile.center_lon),
        corners_latlon=tile.corners_latlon,
        corner_ring_lonlat=tile.corner_ring_lonlat(),
        tile_m=tile.tile_m, sub_m=tile.sub_m,
        valid_frac=tile.valid_frac, area_m2=tile.area_m2,
        px_window=(tile.px_row0, tile.px_col0, tile.px_h, tile.px_w),
        layers=layer_stats,
        provenance=_provenance(geometry, tile.tile_m, tile.sub_m),
    )


def annotate_tiles(tiles, reader: WindowReader, geometry: DemGeometry, *,
                   split_result=None, layers=_DEFAULT_LAYERS) -> list[TileAnnotation]:
    """Annotate a batch of tiles; ``split_result`` (a ``SplitResult``) supplies each tile's label."""
    out: list[TileAnnotation] = []
    for t in tiles:
        split = split_result.split_of(t.index) if split_result is not None else None
        out.append(tile_annotation(t, reader, geometry, split=split, layers=layers))
    return out


def to_geojson_feature(ann: TileAnnotation) -> dict:
    """One GeoJSON Feature: the tile's closed corner polygon + flattened per-layer properties."""
    props: dict = {
        "tile_id": ann.tile_id, "index": ann.index, "row": ann.row, "col": ann.col,
        "kind": ann.kind, "split": ann.split,
        "center_lat": ann.center_latlon[0], "center_lon": ann.center_latlon[1],
        "extent_m": list(ann.extent_m), "tile_m": ann.tile_m, "sub_m": ann.sub_m,
        "valid_frac": ann.valid_frac, "area_m2": ann.area_m2,
        "px_window": list(ann.px_window),
    }
    for name, st in ann.layers.items():
        props[f"{name}_min"] = st.min
        props[f"{name}_max"] = st.max
        props[f"{name}_mean"] = st.mean
        props[f"{name}_std"] = st.std
        props[f"{name}_count"] = st.count
        props[f"{name}_valid_frac"] = st.valid_frac
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [ann.corner_ring_lonlat]},
        "properties": props,
    }


def to_geojson_featurecollection(annotations, geometry: DemGeometry, *, provenance=None) -> dict:
    """A GeoJSON FeatureCollection of tile annotations, with a documented (non-WGS84) CRS member.

    Coordinates are selenographic [lon, lat] on the R=1737400 m Moon sphere -- NOT WGS84 -- so a
    ``crs`` name member (the deprecated GeoJSON convention, the only way to state a lunar frame) plus
    a ``provenance`` block make the frame explicit for any consumer."""
    prov = provenance or _provenance(geometry, _first_tile_m(annotations), _first_sub_m(annotations))
    geog = geographic_crs_authority()
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:{geog.replace(':', '::')}"}},
        "provenance": prov,
        "features": [to_geojson_feature(a) for a in annotations],
    }


def _first_tile_m(annotations) -> float:
    return float(annotations[0].tile_m) if annotations else 100.0


def _first_sub_m(annotations) -> float:
    return float(annotations[0].sub_m) if annotations else 25.0
