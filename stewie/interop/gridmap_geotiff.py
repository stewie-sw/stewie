"""[REQ:BA-06] GridMap <-> GeoTIFF interop (part of the BA-06 converter set).

A GridMap (the grid_map_msgs geometry: cell resolution, side lengths, center position, frame) round-trips
through a georeferenced GeoTIFF with its GEOREFERENCE preserved -- the GeoTIFF's affine transform encodes the
pixel size (resolution) and the north-up origin, so reading it back recovers the resolution + center position
exactly. Pure Python (rasterio, already a dep); NO ROS dependency -- the GridMap is a plain dataclass matching
grid_map_msgs semantics, so this converter runs on-host (no container). rasterio (the GeoTIFF I/O) is
LAZY-imported inside the two I/O functions so importing this module needs only numpy (it is in the `server`
extra, not the lean `dev`/`core` profiles -- ADR-0006); a test that exercises the round-trip importorskip's it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from rasterio.transform import Affine


@dataclass
class GridMap:
    """A minimal grid_map_msgs-shaped grid: a stack of named float layers over a common geometry. `position`
    is the map CENTER in `frame_id` metres; `length_x`/`length_y` are the side lengths; `resolution` is the
    cell size. Row 0 is the NORTH (max-y) edge (north-up raster convention)."""
    resolution: float
    length_x: float
    length_y: float
    position: tuple[float, float]
    frame_id: str
    layers: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def cols(self) -> int:
        return int(round(self.length_x / self.resolution))

    @property
    def rows(self) -> int:
        return int(round(self.length_y / self.resolution))


def _transform(gm: GridMap) -> Affine:
    """North-up affine: the GridMap center + side lengths -> the raster's top-left origin + pixel size."""
    from rasterio.transform import Affine
    west = gm.position[0] - gm.length_x / 2.0
    north = gm.position[1] + gm.length_y / 2.0
    return Affine.translation(west, north) * Affine.scale(gm.resolution, -gm.resolution)


def gridmap_to_geotiff(gm: GridMap, layer: str, path: str) -> None:
    """Write one GridMap layer to a georeferenced GeoTIFF. The affine transform carries the georeference
    (resolution + origin); the frame id is stored in a tag so a CRS-less local frame round-trips."""
    import rasterio
    data = np.asarray(gm.layers[layer], dtype=np.float32)
    if data.shape != (gm.rows, gm.cols):
        raise ValueError(f"layer {layer!r} shape {data.shape} != geometry ({gm.rows}, {gm.cols})")
    with rasterio.open(
        path, "w", driver="GTiff", height=gm.rows, width=gm.cols, count=1, dtype="float32",
        transform=_transform(gm), nodata=None,
    ) as dst:
        dst.write(data, 1)
        dst.update_tags(STEWIE_FRAME_ID=gm.frame_id, STEWIE_LAYER=layer)


def geotiff_to_gridmap(path: str, layer: str | None = None) -> GridMap:
    """Read a georeferenced GeoTIFF back into a GridMap, recovering resolution + center position from the
    affine transform (the inverse of gridmap_to_geotiff)."""
    import rasterio
    with rasterio.open(path) as src:
        data = src.read(1).astype(np.float32)
        t = src.transform
        res = float(t.a)                                   # pixel width == resolution (t.e == -res)
        rows, cols = src.height, src.width
        length_x, length_y = cols * res, rows * res
        west, north = float(t.c), float(t.f)
        position = (west + length_x / 2.0, north - length_y / 2.0)
        frame_id = src.tags().get("STEWIE_FRAME_ID", "map")
        name = layer or src.tags().get("STEWIE_LAYER", "elevation")
    return GridMap(resolution=res, length_x=length_x, length_y=length_y, position=position,
                   frame_id=frame_id, layers={name: data})
