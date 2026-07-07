"""PLAN ANYWHERE -- the request-time DEM resolver for an ARBITRARY lunar lat/lon (not just the curated
Artemis sites).

The curated sites (haworth / shackleton_rim / nobile_rim) ship a pre-imported 5 m / 1 m polar-stereo DEM
bundle. This module produces an equivalent Haworth-format bundle ON DEMAND for any picked (lat, lon), by
cropping a square work-area tile out of the on-host GLOBAL LOLA LDEM and reprojecting it to a LOCAL frame
centred on THAT spot. Same on-disk contract (heightmap.rf32 + metadata.json with grid + world_bounds_m), so
``bundle_for_site`` / ``load_site_dem`` / the globe drape / the planner consume it exactly like a curated
bundle -- the off-site "0 loadable layers" 404 / silent flat_fallback becomes a real cropped DEM.

ACCURACY (Aaron's warp question). The crop is reprojected to a LOCAL azimuthal-equidistant frame centred on
the pick (``+proj=aeqd +lat_0/+lon_0``), NOT the shared south-polar-stereographic frame. Polar-stereo scale
error is ~0.2% at the Artemis pole sites but ~2x at the equator; a local frame keeps distortion ~0 at ANY
latitude. Same lunar sphere R=1737400 m as the curated tiles -> no datum error. Native resolution is the
global LDEM's own ~118 m/px -- honestly COARSE off-site vs the 5 m/1 m curated sites; the DEM is NOT upsampled
or infilled (no fabricated detail).

REUSE (no re-implemented reprojection). rasterio does the windowed read of the global GeoTIFF;
``dart.dem_import.reproject_cylindrical(..., return_frame=True)`` does the equirectangular->local-AEQD
reprojection AND reports the local frame; ``dart.dem_import.crop_square`` trims to the pick-centred square;
``dart.dem_import.ingest_to_bundle`` writes the Haworth-format bundle. This module only orchestrates them +
writes the georeference metadata.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import threading

import numpy as np

MOON_RADIUS_M = 1737400.0                 # IAU_2015 mean-sphere radius (matches the curated bundles)
DEFAULT_EXTENT_M = 10000.0                # match the curated 10 km work-area tile extent
_HALO_FRAC = 0.30                         # read a slightly larger lat/lon window so the AEQD crop has full edge coverage
_MAX_ABS_LAT = 89.9                       # a local equirectangular crop degenerates at the pole itself; curated polar tiles serve there

# the on-host global LOLA LDEM (SimpleCylindrical / Equirectangular Moon, ~118 m/px, int16 scale 0.5); the
# path is overridable so a deployment / a test can point elsewhere. Real data only -- absence is an honest
# error, never a synthesized surface.
_DEFAULT_GLOBAL_LDEM = "/mnt/projects/datasets/argus_dem_nav/lunar_dem/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif"

_BUILD_LOCK = threading.Lock()

__all__ = ["adhoc_site_id", "is_adhoc_site", "parse_adhoc_site", "resolve_adhoc_bundle",
           "global_ldem_path", "adhoc_root"]


def global_ldem_path() -> str:
    """The on-host global LOLA LDEM GeoTIFF ($STEWIE_GLOBAL_LDEM override)."""
    return os.environ.get("STEWIE_GLOBAL_LDEM", _DEFAULT_GLOBAL_LDEM)


def adhoc_root() -> str:
    """The writable cache root for ad-hoc bundles ($STEWIE_ADHOC_DEM_DIR, else data_dir()/adhoc_dem)."""
    d = os.environ.get("STEWIE_ADHOC_DEM_DIR")
    if d:
        return d
    from stewie.specs import config as _CFG
    return os.path.join(_CFG.data_dir(), "adhoc_dem")


def _norm_lon(lon: float) -> float:
    """Wrap a longitude into [-180, 180) so the ad-hoc id is canonical (a spot has ONE id)."""
    return ((float(lon) + 180.0) % 360.0) - 180.0


def adhoc_site_id(lat: float, lon: float) -> str:
    """The deterministic ad-hoc site id for a pick, keyed to milli-degree (~30 m) granularity so a repeat
    pick within a cell reuses the cached crop. Reversible: ``parse_adhoc_site`` recovers (lat, lon)."""
    lat_mdeg = int(round(float(lat) * 1000.0))
    lon_mdeg = int(round(_norm_lon(lon) * 1000.0))
    return f"adhoc_{lat_mdeg}_{lon_mdeg}"


def is_adhoc_site(site: str) -> bool:
    """True if ``site`` is an ad-hoc lat/lon-derived id (vs a curated registry name)."""
    return isinstance(site, str) and site.startswith("adhoc_")


def parse_adhoc_site(site: str) -> tuple[float, float]:
    """Recover (lat_deg, lon_deg) from an ad-hoc site id. Raises ValueError on a malformed id."""
    if not is_adhoc_site(site):
        raise ValueError(f"not an ad-hoc site id: {site!r}")
    parts = site[len("adhoc_"):].split("_")
    if len(parts) != 2:
        raise ValueError(f"malformed ad-hoc site id: {site!r}")
    return int(parts[0]) / 1000.0, int(parts[1]) / 1000.0


def resolve_adhoc_bundle(lat: float, lon: float, *, extent_m: float = DEFAULT_EXTENT_M,
                         data_root: str | None = None) -> str:
    """Return the on-disk bundle DIRECTORY for a picked (lat, lon), cropping the global LDEM on first use
    and caching it (keyed by the ad-hoc id) so repeat picks are a fast cache hit. The bundle is written in
    the Haworth format (heightmap.rf32 + metadata.json with grid + world_bounds_m + a local-AEQD
    georeference), so ``bundle_for_site`` / ``load_site_dem`` / the globe drape read it like a curated site.

    Raises FileNotFoundError if the global LDEM asset is absent (honest -- no synthesized surface),
    ValueError for a pole-adjacent pick a local equirectangular crop cannot serve."""
    lon = _norm_lon(lon)
    if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > _MAX_ABS_LAT:
        raise ValueError(f"lat {lat} out of range for an off-site crop (|lat| must be <= {_MAX_ABS_LAT}); "
                         "the curated polar-stereographic tiles serve the immediate pole")
    root = data_root or adhoc_root()
    bundle_dir = os.path.join(root, adhoc_site_id(lat, lon))
    if os.path.exists(os.path.join(bundle_dir, "heightmap.rf32")) and \
            os.path.exists(os.path.join(bundle_dir, "metadata.json")):
        return bundle_dir                                   # fast path: already cropped (no lock)
    with _BUILD_LOCK:                                       # one builder; re-check under the lock
        if os.path.exists(os.path.join(bundle_dir, "heightmap.rf32")) and \
                os.path.exists(os.path.join(bundle_dir, "metadata.json")):
            return bundle_dir
        _build_adhoc_bundle(lat, lon, bundle_dir, float(extent_m))
    return bundle_dir


def _build_adhoc_bundle(lat: float, lon: float, bundle_dir: str, extent_m: float) -> None:
    """Crop + reproject + ingest a pick-centred work-area tile from the global LDEM into ``bundle_dir``
    (written atomically via a temp dir + os.replace)."""
    import rasterio
    from rasterio.transform import rowcol, xy
    from rasterio.windows import Window
    from pyproj import CRS, Transformer

    import dart.dem_import as di

    ldem = global_ldem_path()
    if not os.path.exists(ldem):
        raise FileNotFoundError(
            f"global LOLA LDEM not found at {ldem}; PLAN ANYWHERE needs the real global DEM "
            "(set $STEWIE_GLOBAL_LDEM). No synthesized surface is substituted.")

    with rasterio.open(ldem) as ds:
        proj_crs = CRS.from_wkt(ds.crs.to_wkt())            # equirectangular (SimpleCylindrical) projected metres
        geo_crs = proj_crs.geodetic_crs                     # selenographic lon/lat on the same sphere
        to_proj = Transformer.from_crs(geo_crs, proj_crs, always_xy=True)
        from_proj = Transformer.from_crs(proj_crs, geo_crs, always_xy=True)
        cell_native = float(abs(ds.transform.a))            # ~118.45 m/px -- the honest native resolution (NOT upsampled)
        scale = float((ds.scales or (1.0,))[0])
        offset = float((ds.offsets or (0.0,))[0])
        nodata = ds.nodata

        # lat/lon window (deg) covering extent + halo. Near the pole cos(lat) shrinks -> the east-west
        # longitude span grows; cap the half-window so it never wraps past +/-180.
        half = 0.5 * extent_m * (1.0 + _HALO_FRAC)
        dlat = half / (MOON_RADIUS_M * math.pi / 180.0)
        dlon = half / (MOON_RADIUS_M * math.cos(math.radians(lat)) * math.pi / 180.0)
        dlon = min(dlon, 89.0)
        lat_top, lat_bot = lat + dlat, lat - dlat
        lon_left, lon_right = lon - dlon, lon + dlon

        xs, ys = to_proj.transform([lon_left, lon_right, lon_left, lon_right],
                                   [lat_top, lat_top, lat_bot, lat_bot])
        rows, cols = rowcol(ds.transform, xs, ys)
        r0, r1 = max(0, min(rows)), min(ds.height - 1, max(rows))
        c0, c1 = max(0, min(cols)), min(ds.width - 1, max(cols))
        if r1 <= r0 or c1 <= c0:
            raise ValueError(f"empty crop window for (lat={lat}, lon={lon}); outside the global LDEM")
        win = Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
        raw = ds.read(1, window=win).astype(np.float64)
        if nodata is not None and np.any(raw == nodata):
            raise ValueError(f"global LDEM has NoData in the ({lat}, {lon}) window; cannot crop honestly "
                             "(no fabricated fill)")
        heights = raw * scale + offset                       # int16 DN -> metres above sphere

        # the ACTUAL window edge lat/lon (pixel centres) -> feed the reprojection its true bounds
        x_tl, y_tl = xy(ds.transform, r0, c0)
        x_br, y_br = xy(ds.transform, r1, c1)
        lon_tl, lat_tl = from_proj.transform(x_tl, y_tl)
        lon_br, lat_br = from_proj.transform(x_br, y_br)

    # reproject the equirectangular patch to a LOCAL AEQD frame centred on the window (reuse dem_import;
    # return_frame exposes the frame this same call already computed -- no second reprojection)
    Z_local, cell, frame = di.reproject_cylindrical(
        heights, lat_top=lat_tl, lat_bottom=lat_br, lon_left=lon_tl, lon_right=lon_br,
        radius_m=MOON_RADIUS_M, target_cell_m=cell_native, return_frame=True)
    if not np.isfinite(Z_local).all():
        raise ValueError(f"non-finite terrain in the reprojected ({lat}, {lon}) crop")

    # trim to a pick-centred extent_m square (reuse crop_square). The AEQD frame's pixel(0,0) CENTRE is
    # (frame x0, frame y1); the pick projects to (pick_x, pick_y) in that frame.
    affine = di.Affine(x0=float(frame["x0"]), y0=float(frame["y1"]), px=float(cell))
    aeqd = CRS.from_proj4(frame["proj4"])
    fwd = Transformer.from_crs(aeqd.geodetic_crs, aeqd, always_xy=True)
    pick_x, pick_y = fwd.transform(lon, lat)
    try:
        Zc, aff_c = di.crop_square(Z_local, affine, (pick_x, pick_y), extent_m)
    except ValueError:
        # the pick sits too near the reprojected patch edge for a full square -> keep the full reprojected
        # tile (still a real, pick-containing crop; just not exactly extent_m). Never fabricate edge fill.
        Zc, aff_c = Z_local, affine
    Zc = np.ascontiguousarray(Zc, dtype=np.float64)
    h, w = Zc.shape

    # Haworth-format world_bounds_m (pixel(0,0) CENTRE = (x0 + cell/2, y1 - cell/2), north-up raster)
    world_bounds = {
        "x0": float(aff_c.x0) - cell / 2.0,
        "y1": float(aff_c.y0) + cell / 2.0,
        "x1": float(aff_c.x0) + (w - 1) * cell + cell / 2.0,
        "y0": float(aff_c.y0) - (h - 1) * cell - cell / 2.0,
    }
    georeference = {
        "crs_kind": "local_aeqd", "proj4": frame["proj4"],
        "lat0": float(frame["lat0"]), "lon0": float(frame["lon0"]),
        "pick_lat": float(lat), "pick_lon": float(lon), "radius_m": MOON_RADIUS_M,
    }

    parent = os.path.dirname(bundle_dir) or "."
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".part_", dir=parent)
    try:
        di.ingest_to_bundle(Zc, cell, tmp, body="moon",
                            source="Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014 (LOLA global, ~118 m/px)",
                            georeference=georeference)
        mp = os.path.join(tmp, "metadata.json")
        meta = json.load(open(mp))
        meta["schema_version"] = "1.0"
        meta["scene_name"] = f"adhoc/{adhoc_site_id(lat, lon)}"
        meta["grid"]["cell_m"] = float(cell)
        meta["world_bounds_m"] = world_bounds
        meta["georeference"] = georeference
        meta["gravity_m_s2"] = 1.62
        meta["region"] = f"off-site ({lat:.3f}, {lon:.3f})"
        meta["height_range_m"] = [float(Zc.min()), float(Zc.max())]
        meta["dem_provenance"] = {
            "source": "PGDA/LOLA Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif (global LOLA shape map)",
            "frame": f"LOCAL azimuthal-equidistant, R={int(MOON_RADIUS_M)} m sphere, centred on the pick",
            "z_semantics": "height above sphere [m]",
            "native_cell_m": float(cell),
            "crop_center_latlon": [float(lat), float(lon)],
            "crop_extent_m": [round(w * cell, 1), round(h * cell, 1)],
            "resolution_note": "native LOLA global ~118 m/px -- NOT upsampled or infilled off-site (honestly coarse "
                               "vs the 5 m/1 m curated sites)",
            "sphere_radius_m": MOON_RADIUS_M,
            "citation": "Barker et al. 2016/2021 (LOLA GDR); Smith et al. 2010 (LOLA)",
        }
        meta["notes"] = ("PLAN-ANYWHERE ad-hoc crop of the global LOLA LDEM, reprojected to a local AEQD "
                         "frame centred on the pick (accuracy: ~0 warp at any latitude).")
        with open(mp, "w") as f:
            json.dump(meta, f, indent=1)
        os.replace(tmp, bundle_dir)                          # atomic publish (never a half-written bundle)
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
