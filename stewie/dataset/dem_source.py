"""DEM geometry + windowed pixel I/O for the ML-dataset tiling core.

Additive layer over ``dart.dem_import`` (the frozen, GDAL/rasterio-free GeoTIFF ingest) and
``stewie.terrain.site_dem`` (the real IAU_2015:30135 <-> selenographic transforms). Nothing here
reimplements the projection or the tag parser -- it REUSES them:

  * geometry (bounds + cell + CRS + raster type + nodata) comes from ``dart.dem_import``'s hand-parsed
    GeoTIFF tags WITHOUT materialising the 140 Mpx pixel array (the DecompressionBomb the full
    ``load_lola_geotiff`` would trip), so a ``TileGrid`` is built from the affine/meta alone;
  * per-tile pixel statistics read only the small WINDOW they need, straight off the uncompressed
    per-row strips (never the whole map);
  * the selenographic transform is the SAME CRS ``stewie.terrain.site_dem.bundle_crs`` resolves for
    every curated Haworth product (the shared south-polar-stereographic 30135 frame). The 1 m v3 DEM
    and the 5 m sim bundle are non-overlapping sub-regions of Haworth, so only the affine differs --
    the projection frame is identical, which is why the transform is shared, not duplicated.

No new gdal/rasterio/pyproj dependency: pyproj is already the ``[planner]`` extra ``site_dem`` uses.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class WindowReader(Protocol):
    """A windowed pixel reader: ``reader(r0, c0, h, w) -> float32`` over a co-registered raster.

    The structural type the annotations pass reads a tile's window through. ``GeoTiffWindowReader``
    (raw GeoTIFF strips) satisfies it, and so does any bundle-backed ``.rf32`` reader -- both are real
    co-registered elevation, so the tiling core is agnostic to which real raster backs a window."""

    def __call__(self, r0: int, c0: int, h: int, w: int) -> np.ndarray: ...


# The real LOLA Haworth 1 m v3 DEM. Not bundled (562 MB, gitignored); resolved at runtime.
_DEM_BASENAME = "Lunar_LROnac_Haworth_sfs-dem_1m_v3.tif"
_CANDIDATES = (
    "/mnt/projects/stewie/code/datasets/lunar_dem/" + _DEM_BASENAME,
    "/mnt/projects/datasets/argus_dem_nav/lunar_dem/" + _DEM_BASENAME,
)


def resolve_dem_path(explicit: str | None = None) -> str | None:
    """Locate the real Haworth 1 m DEM GeoTIFF, or ``None`` if it is not on this host.

    Resolution order: an ``explicit`` path, then ``$STEWIE_DEM_TIF`` / ``$STEWIE_HAWORTH_1M_TIF``,
    then the in-repo ``datasets/lunar_dem`` symlink and the ``argus_dem_nav`` store, then a
    ``datasets/lunar_dem`` path relative to CWD. Returns the first that exists. Callers/tests treat
    ``None`` as "real DEM absent -> skip" (it is intentionally not fabricated)."""
    for cand in (explicit, os.environ.get("STEWIE_DEM_TIF"),
                 os.environ.get("STEWIE_HAWORTH_1M_TIF"), *_CANDIDATES,
                 os.path.join("datasets", "lunar_dem", _DEM_BASENAME)):
        if cand and os.path.exists(cand):
            return os.path.abspath(cand)
    return None


# ---------------------------------------------------------------------------------------------------
# Geometry -- read from the GeoTIFF tags only (no pixel load).
# ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DemGeometry:
    """Placement + footprint of a north-up, axis-aligned GeoTIFF, read from its tags alone.

    Coordinates are in the DEM's projected CRS metres (IAU_2015:30135 south-polar stereographic for
    Haworth). ``(x0_center, y0_center)`` is the FIRST-PIXEL (row 0, col 0) CENTER -- the same
    convention as ``dart.dem_import.Affine`` (PixelIsArea tiepoints are shifted half a pixel inward).
    The footprint bounds are the PIXEL-AREA outer edges: ``x_min = x0_center - cell/2`` .. and the
    grid spans ``width`` cols east and ``height`` rows south.
    """

    path: str
    width: int
    height: int
    cell_m: float
    x0_center: float
    y0_center: float
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    crs_authority: str
    radius_m: float
    nodata: float | None
    raster_type: str

    @property
    def extent_x_m(self) -> float:
        return self.x_max - self.x_min

    @property
    def extent_y_m(self) -> float:
        return self.y_max - self.y_min

    def world_xy(self, row, col):
        """World (X, Y) [m] of a pixel CENTER at (row, col) -- mirrors dem_import.Affine.xy."""
        return (self.x0_center + np.asarray(col) * self.cell_m,
                self.y0_center - np.asarray(row) * self.cell_m)


def read_geotiff_geometry(path: str) -> DemGeometry:
    """Read a GeoTIFF's placement/footprint from its tags WITHOUT loading the pixel array.

    Reuses ``dart.dem_import``'s hand-parsed IFD + GeoKeys (tags 256/257/33550/33922/34735/34736/
    42113). The affine origin follows dem_import exactly: back the tiepoint out to raster (0,0), then
    apply the PGDA half-pixel PixelIsArea shift (GTRasterType=1). The CRS is the shared curated-Haworth
    frame from ``site_dem.bundle_crs`` (all curated sites are IAU_2015:30135), NOT re-derived here.
    """
    from dart.dem_import import _parse_geokeys, _read_tiff_ifd0

    tags, _bo = _read_tiff_ifd0(path)
    scale = tags.get(33550)
    tie = tags.get(33922)
    if scale is None or tie is None:
        raise ValueError(f"{path}: missing ModelPixelScale/ModelTiepoint -- not a placeable GeoTIFF")
    px = float(scale[0])
    W = int(tags[256][0])
    H = int(tags[257][0])
    gk = _parse_geokeys(tags.get(34735), tags.get(34736))
    raster_type = int(gk.get(1025, 2) or 2)
    x0 = tie[3] - tie[1] * px
    y0 = tie[4] + tie[0] * px
    if raster_type == 1:  # PixelIsArea: tiepoint is the NW corner -> shift to first-pixel center
        x0 += px / 2.0
        y0 -= px / 2.0
    radius = float(gk.get(2057, 1737400.0) or 1737400.0)
    nodata = None
    nd = tags.get(42113)
    if nd:
        try:
            nodata = float(nd[0])
        except (TypeError, ValueError):
            nodata = None
    crs = _bundle_crs()
    auth = crs.to_authority()
    crs_authority = ":".join(auth) if auth else "IAU_2015:30135"
    x_min = x0 - px / 2.0
    y_max = y0 + px / 2.0
    return DemGeometry(
        path=os.path.abspath(path), width=W, height=H, cell_m=px,
        x0_center=x0, y0_center=y0,
        x_min=x_min, x_max=x_min + W * px, y_min=y_max - H * px, y_max=y_max,
        crs_authority=crs_authority, radius_m=radius, nodata=nodata,
        raster_type="PixelIsArea" if raster_type == 1 else "PixelIsPoint",
    )


# ---------------------------------------------------------------------------------------------------
# Selenographic transforms -- REUSE site_dem's shared IAU_2015:30135 frame (no reinvention).
# ---------------------------------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _bundle_crs():
    """The shared curated-Haworth CRS (IAU_2015:30135), via site_dem.bundle_crs (cached)."""
    from stewie.terrain.site_dem import bundle_crs
    return bundle_crs()


@lru_cache(maxsize=1)
def selenographic_transformers():
    """``(fwd, inv)`` pyproj Transformers for the shared 30135 frame, built exactly as site_dem does.

    ``fwd``: selenographic (lon, lat) deg -> projected metres. ``inv``: projected metres ->
    (lon, lat) deg. Same CRS object site_dem.dem_origin_to_latlon uses, so a tile centre projected
    here round-trips through site_dem's transform to the bit. ``always_xy=True`` (lon/lat order)."""
    from pyproj import Transformer
    crs = _bundle_crs()
    fwd = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
    inv = Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True)
    return fwd, inv


def geographic_crs_authority() -> str:
    """Authority string of the selenographic (lon/lat) CRS -- the GeoJSON coordinate frame."""
    crs = _bundle_crs().geodetic_crs
    auth = crs.to_authority()
    return ":".join(auth) if auth else "IAU_2015:30100"


def proj_to_latlon(x, y) -> tuple[float, float]:
    """Project 30135 metres -> selenographic ``(lat, lon)`` deg (scalar), via the shared inverse."""
    _fwd, inv = selenographic_transformers()
    lon, lat = inv.transform(float(x), float(y))
    return float(lat), float(lon)


def latlon_to_proj(lat, lon) -> tuple[float, float]:
    """Project selenographic ``(lat, lon)`` deg -> 30135 metres ``(x, y)`` (scalar), shared forward."""
    fwd, _inv = selenographic_transformers()
    x, y = fwd.transform(float(lon), float(lat))
    return float(x), float(y)


# ---------------------------------------------------------------------------------------------------
# Windowed pixel reader -- read only the tile's window off the uncompressed strips.
# ---------------------------------------------------------------------------------------------------

class GeoTiffWindowReader:
    """Read arbitrary ``[r0:r0+h, c0:c0+w]`` windows of an uncompressed float32 GeoTIFF.

    Seeks per-row into the strip data (exactly ``h*w*4`` bytes of I/O for a window), so the full
    array is never materialised -- the same fixed-memory-ceiling discipline as
    ``site_dem.read_dem_window`` for the .rf32 bundle, but for the raw GeoTIFF strips. NoData
    (GDAL_NODATA sentinel) is mapped to NaN, matching ``dart.dem_import.load_lola_geotiff``. Tiled or
    compressed TIFFs raise (the PGDA products are neither)."""

    def __init__(self, path: str):
        from dart.dem_import import _read_tiff_ifd0
        tags, bo = _read_tiff_ifd0(path)
        if int((tags.get(259) or (1,))[0]) != 1:
            raise ValueError(f"{path}: compressed TIFF (Compression!=1) unsupported by the windowed reader")
        if tags.get(322) is not None:
            raise ValueError(f"{path}: tiled TIFF unsupported by the windowed reader (expected strips)")
        if int((tags.get(258) or (0,))[0]) != 32 or int((tags.get(339) or (1,))[0]) != 3:
            raise ValueError(f"{path}: expected single-band float32 (BitsPerSample=32, SampleFormat=3)")
        self.path = path
        self.width = int(tags[256][0])
        self.height = int(tags[257][0])
        self._strip_offsets = tags[273]
        self._rows_per_strip = int(tags[278][0])
        self._dtype = np.dtype(("<f4" if bo == "<" else ">f4"))
        nd = tags.get(42113)
        self.nodata = float(nd[0]) if nd else None

    def __call__(self, r0: int, c0: int, h: int, w: int) -> np.ndarray:
        """Read window ``[r0:r0+h, c0:c0+w]`` as float32 with NoData -> NaN; clamped to the grid."""
        W, H = self.width, self.height
        r0 = max(0, min(int(r0), H)); c0 = max(0, min(int(c0), W))
        h = max(0, min(int(h), H - r0)); w = max(0, min(int(w), W - c0))
        out = np.empty((h, w), dtype=np.float32)
        rps = self._rows_per_strip
        bpr = W * 4  # bytes per full row (chunky, 1 sample)
        with open(self.path, "rb") as f:
            for i in range(h):
                r = r0 + i
                off = self._strip_offsets[r // rps] + (r % rps) * bpr + c0 * 4
                f.seek(off)
                out[i] = np.frombuffer(f.read(w * 4), dtype=self._dtype).astype(np.float32)
        if self.nodata is not None:
            out = np.where(out == np.float32(self.nodata), np.float32("nan"), out)
        return out
