"""STEWIE ML-dataset tiling core over the real LOLA Haworth 1 m DEM.

A numbered tile grid (100 m tiles + a 25 m display sub-graticule) over the real DEM's projected
footprint, a leakage-safe spatial-block train/test/val split, and per-tile lat/lon + per-layer
statistics annotations exported as GeoJSON. Real data only: geometry from the GeoTIFF tags, stats
from real pixel windows, the selenographic transform reused from ``stewie.terrain.site_dem``.

Submodules: ``dem_source`` (geometry + windowed pixel I/O + shared 30135 transform), ``tile_grid``
(the numbered grid), ``splits`` (leakage-safe spatial blocks), ``annotations`` (per-tile records +
GeoJSON).
"""
from __future__ import annotations

from stewie.dataset.annotations import (
    LayerStats,
    TileAnnotation,
    annotate_tiles,
    tile_annotation,
    to_geojson_feature,
    to_geojson_featurecollection,
)
from stewie.dataset.dem_source import (
    DemGeometry,
    GeoTiffWindowReader,
    read_geotiff_geometry,
    resolve_dem_path,
)
from stewie.dataset.splits import SplitResult, spatial_block_split
from stewie.dataset.tile_grid import Tile, TileGrid, build_tiles

__all__ = [
    "DemGeometry", "GeoTiffWindowReader", "read_geotiff_geometry", "resolve_dem_path",
    "Tile", "TileGrid", "build_tiles",
    "SplitResult", "spatial_block_split",
    "LayerStats", "TileAnnotation", "annotate_tiles", "tile_annotation",
    "to_geojson_feature", "to_geojson_featurecollection",
]
