"""Independent DEM anchoring prior for the S3LI ``s3li_crater`` traverse (Mt Etna / Cisternazza).

This module turns a PUBLIC orbital/airborne Digital Elevation Model of Mt Etna into a height + surface
-normal sampler over a local ENU frame, for the DEM-anchoring SLAM experiment that reproduces
arXiv:2603.17229. The DEM used is **Copernicus GLO-30** (the Copernicus DEM 2021 release, 30 m / 1
arc-second, EGM2008-orthometric heights), tile ``N37/E015`` fetched from the AWS open-data bucket
``copernicus-dem-30m.s3.amazonaws.com`` (no auth). Higher-resolution Italian DEMs (Tinitaly 10 m,
OpenTopography Etna LiDAR) were tried first but are registration/API-key gated and unreachable without
interactive sign-up, so GLO-30 is the honest fallback that GUARANTEES a real-data result.

WHY THIS PRIOR IS INDEPENDENT (the experiment's whole validity). The DEM is a public survey produced
years before the 2021 rover run; it is NOT built from the rover's own ground-truth trajectory. The
S3LI data share ships no DEM (see ``CALIBRATION_NOTES.md``); the original paper sourced a Pleiades DSM
separately for the same reason. So a downstream estimator may legitimately consume (DEM + a declared
coarse start fix) as a map prior.

TRUTH FIREWALL (invariant I3). The ENU origin is a DECLARED DATUM -- a single known coarse start fix
(the first D-GNSS fix of the ``s3li_crater`` run, baked in below as a constant), NOT the trajectory.
This module reads ONLY the independent DEM and that one declared origin; it never opens the GT
``global_lle.pos`` track. A SLAM front end can therefore anchor to (this DEM, this declared origin)
without ever touching the GT trajectory. (Registration is *validated* against GT in the test, because
the test is the scoring layer, not an estimator -- exactly as ``dart.lusnar_reader`` reads GT for
scoring while the firewall is enforced at the estimator input.)

DATUM CAVEAT (do NOT mistake a height-datum offset for misregistration). The S3LI GT heights are WGS84
ELLIPSOIDAL; Copernicus heights are EGM2008 ORTHOMETRIC. At Mt Etna the EGM2008 geoid undulation is
``EGM2008_GEOID_UNDULATION_M`` (+43.46 m, independently computed via pyproj), so a near-CONSTANT tens-
of-metres offset between GT and DEM is EXPECTED and is the datum, not an error. Registration is judged
on RELIEF SHAPE (de-meaned RMSE + along-track correlation), not the absolute offset -- see the test.

Heights returned by this sampler are the DEM's native EGM2008-orthometric elevation in metres (ABSOLUTE,
not relative to the ENU origin). Add ``EGM2008_GEOID_UNDULATION_M`` to convert to WGS84-ellipsoidal.

rasterio is imported lazily (only to read the GeoTIFF at construction); the rest is numpy + pyproj. The
DEM tile is not bundled -- the sampler is real-data-gated and raises if the tile is absent.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). DEM: Copernicus GLO-30 (ESA/Copernicus, public).
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np
from pyproj import Transformer

# --- the independent public DEM (real-data-gated; not bundled) ------------------------------------
_DEM_DIR = "/mnt/projects/datasets/argus_dem_nav/s3li/dem"
DEFAULT_DEM_PATH = os.path.join(_DEM_DIR, "Copernicus_DSM_COG_10_N37_00_E015_00_DEM.tif")
DEM_SOURCE = "Copernicus GLO-30 (Copernicus DEM, EGM2008-orthometric, ~30 m), tile N37/E015"
DEM_RESOLUTION_M = 30.0

# --- declared datum: the coarse start fix (NOT the GT trajectory; invariant I3) -------------------
# First D-GNSS fix of the s3li_crater run (global_lle.pos first data row): a single known start pose.
ORIGIN_LAT_DEG = 37.726382053
ORIGIN_LON_DEG = 15.005966866
# height of the declared start fix in WGS84-ELLIPSOIDAL metres (as the RTKLIB GT reports it)
ORIGIN_HEIGHT_ELLIPSOIDAL_M = 2678.6869
# EGM2008 geoid undulation at the traverse (h_ellipsoidal - H_orthometric), computed with pyproj
# (EPSG:4979 -> EPSG:9518); the datum offset between GT (ellipsoidal) and the DEM (orthometric).
EGM2008_GEOID_UNDULATION_M = 43.46
# the declared origin's ORTHOMETRIC height (same vertical datum as the DEM the sampler returns)
ORIGIN_HEIGHT_ORTHOMETRIC_M = ORIGIN_HEIGHT_ELLIPSOIDAL_M - EGM2008_GEOID_UNDULATION_M

_WGS84_LLA = "EPSG:4979"      # geographic 3D, ellipsoidal height
_WGS84_ECEF = "EPSG:4978"     # geocentric (Earth-Centred, Earth-Fixed)


@dataclass(frozen=True)
class DemSample:
    """One DEM query result: ``height_m`` is the EGM2008-orthometric elevation (absolute metres) and
    ``normal_enu`` is the unit outward surface normal expressed in the local ENU frame (East, North,
    Up). The normal's Up component is positive (a terrain normal points out of the ground)."""

    height_m: float
    normal_enu: np.ndarray


class S3liDem:
    """Height + surface-normal sampler over the independent Copernicus Etna DEM, in a local ENU frame
    anchored at the declared coarse start fix (``ORIGIN_*`` constants).

    Reads a window of the DEM around the declared origin once at construction (the ~250 m traverse plus
    a halo), then samples purely in numpy. Queries are accepted as local ENU ``(x_east, y_north)`` in
    metres relative to the origin, or as ``(lat, lon)`` in degrees. The surface normal is built from the
    DEM's local gradient by central differences taken in the ENU frame at the DEM's ground resolution.

    Independent prior + declared datum (invariant I3): construction touches ONLY ``dem_path`` and the
    declared origin constants -- never the GT trajectory. A downstream estimator may anchor to
    (this DEM, this origin) as a map prior without reading GT.
    """

    def __init__(
        self,
        dem_path: str = DEFAULT_DEM_PATH,
        *,
        origin_lat_deg: float = ORIGIN_LAT_DEG,
        origin_lon_deg: float = ORIGIN_LON_DEG,
        origin_height_ellipsoidal_m: float = ORIGIN_HEIGHT_ELLIPSOIDAL_M,
        window_radius_m: float = 1000.0,
    ) -> None:
        if not os.path.isfile(dem_path):
            raise FileNotFoundError(
                f"independent DEM tile not found: {dem_path} (fetch the Copernicus GLO-30 N37/E015 tile "
                f"from copernicus-dem-30m.s3.amazonaws.com)"
            )
        self.dem_path = dem_path
        self.origin_lat_deg = float(origin_lat_deg)
        self.origin_lon_deg = float(origin_lon_deg)
        self.origin_height_ellipsoidal_m = float(origin_height_ellipsoidal_m)
        self.cell_m = DEM_RESOLUTION_M

        # ENU machinery: geodetic ENU about the origin via ECEF (proper, round-trips exactly).
        self._fwd = Transformer.from_crs(_WGS84_LLA, _WGS84_ECEF, always_xy=True)
        self._inv = Transformer.from_crs(_WGS84_ECEF, _WGS84_LLA, always_xy=True)
        x0, y0, z0 = self._fwd.transform(
            self.origin_lon_deg, self.origin_lat_deg, self.origin_height_ellipsoidal_m
        )
        self._p0 = np.array([x0, y0, z0], dtype=float)
        lam = np.radians(self.origin_lon_deg)
        phi = np.radians(self.origin_lat_deg)
        sl, cl, sp, cp = np.sin(lam), np.cos(lam), np.sin(phi), np.cos(phi)
        # rows = East, North, Up unit vectors in ECEF; ENU = R @ (P - P0)
        self._rot = np.array(
            [[-sl, cl, 0.0], [-sp * cl, -sp * sl, cp], [cp * cl, cp * sl, sp]], dtype=float
        )

        self._load_window(dem_path, window_radius_m)

    # ---- DEM window ingest (the only rasterio use; lazy import) -----------------------------------
    def _load_window(self, dem_path: str, window_radius_m: float) -> None:
        import rasterio
        from rasterio.windows import from_bounds

        # bbox around the declared origin, padded by window_radius_m
        dlat = window_radius_m / 110540.0
        dlon = window_radius_m / (111320.0 * float(np.cos(np.radians(self.origin_lat_deg))))
        west, east = self.origin_lon_deg - dlon, self.origin_lon_deg + dlon
        south, north = self.origin_lat_deg - dlat, self.origin_lat_deg + dlat
        with rasterio.open(dem_path) as ds:
            if ds.crs is None or ds.crs.to_epsg() != 4326:
                raise ValueError(f"expected a geographic EPSG:4326 DEM, got {ds.crs}")
            b = ds.bounds
            # Clamp the requested window to the tile (the origin can sit near a tile edge -- the
            # N37/E015 tile starts at lon ~15.0 and the origin is ~0.006 deg east of it). The S3LI
            # traverse runs EAST of the origin and is fully inside this tile, so a tile-clamped
            # window still covers the whole traverse. Raise only if the origin itself is off-tile.
            if not (b.left <= self.origin_lon_deg <= b.right
                    and b.bottom <= self.origin_lat_deg <= b.top):
                raise ValueError(
                    f"declared origin ({self.origin_lat_deg:.5f},{self.origin_lon_deg:.5f}) is not "
                    f"inside DEM tile {os.path.basename(dem_path)} bounds={tuple(b)}"
                )
            west = max(west, b.left)
            east = min(east, b.right)
            south = max(south, b.bottom)
            north = min(north, b.top)
            win = from_bounds(west, south, east, north, transform=ds.transform).round_offsets()
            win = win.round_lengths()
            z = ds.read(1, window=win).astype(np.float64)
            wt = ds.window_transform(win)
            nodata = ds.nodata
        if nodata is not None:
            z = np.where(z == nodata, np.nan, z)
        if not np.isfinite(z).all():
            raise ValueError("DEM window contains nodata/NaN over the traverse area")
        self._z = z
        self._resx = float(wt.a)            # +degrees per column (lon east)
        self._resy = float(-wt.e)           # +degrees per row (lat south); wt.e is negative (north-up)
        self._left = float(wt.c)            # lon of the window's left edge (col 0 left edge)
        self._top = float(wt.f)             # lat of the window's top edge (row 0 top edge)
        nrow, ncol = z.shape
        # covered lon/lat extent (pixel-centre to pixel-centre, the bilinear-valid interior)
        self._lon_lo = self._left + 0.5 * self._resx
        self._lon_hi = self._left + (ncol - 0.5) * self._resx
        self._lat_hi = self._top - 0.5 * self._resy
        self._lat_lo = self._top - (nrow - 0.5) * self._resy

    # ---- local ENU <-> geographic -----------------------------------------------------------------
    def lle_to_enu(self, lat_deg: Any, lon_deg: Any, height_m: Any | None = None) -> Any:
        """Geographic (deg, deg[, ellipsoidal m]) -> local ENU ``(east, north, up)`` metres. Accepts
        scalars or matching-shape arrays. ``height_m`` defaults to the origin height (horizontal east/
        north are insensitive to it at the sub-mm level over this extent)."""
        lat = np.asarray(lat_deg, dtype=float)
        lon = np.asarray(lon_deg, dtype=float)
        h = (np.full(lat.shape, self.origin_height_ellipsoidal_m)
             if height_m is None else np.asarray(height_m, dtype=float))
        x, y, z = self._fwd.transform(lon, lat, h)
        d = np.stack([np.asarray(x), np.asarray(y), np.asarray(z)], axis=0) - self._p0[:, None] \
            if lat.ndim else np.array([x, y, z]) - self._p0
        enu = self._rot @ d
        return enu

    def enu_to_lle(self, east_m: Any, north_m: Any, up_m: Any = 0.0) -> Any:
        """Local ENU metres -> geographic ``(lat_deg, lon_deg, ellipsoidal_height_m)``. Inverse of
        :meth:`lle_to_enu`; scalars or matching-shape arrays."""
        e = np.asarray(east_m, dtype=float)
        n = np.asarray(north_m, dtype=float)
        u = np.broadcast_to(np.asarray(up_m, dtype=float), e.shape) if e.ndim else np.asarray(up_m)
        enu = np.stack([e, n, u], axis=0) if e.ndim else np.array([e, n, u])
        p = self._rot.T @ enu + (self._p0[:, None] if e.ndim else self._p0)
        lon, lat, h = self._inv.transform(p[0], p[1], p[2])
        return np.asarray(lat), np.asarray(lon), np.asarray(h)

    # ---- DEM height (bilinear) --------------------------------------------------------------------
    def _bilinear(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Bilinear DEM height at geographic lat/lon (arrays). Pixel-CENTRE referenced. Raises if any
        query falls outside the loaded window's bilinear-valid interior (honest failure, no
        edge-extrapolation)."""
        lat = np.asarray(lat, dtype=float)
        lon = np.asarray(lon, dtype=float)
        if np.any(lon < self._lon_lo) or np.any(lon > self._lon_hi) \
                or np.any(lat < self._lat_lo) or np.any(lat > self._lat_hi):
            raise ValueError("query outside the loaded DEM window; widen window_radius_m")
        c = (lon - self._left) / self._resx - 0.5
        r = (self._top - lat) / self._resy - 0.5
        r0 = np.floor(r).astype(int)
        c0 = np.floor(c).astype(int)
        fr = r - r0
        fc = c - c0
        nrow, ncol = self._z.shape
        r0 = np.clip(r0, 0, nrow - 2)
        c0 = np.clip(c0, 0, ncol - 2)
        z = self._z
        v00 = z[r0, c0]
        v01 = z[r0, c0 + 1]
        v10 = z[r0 + 1, c0]
        v11 = z[r0 + 1, c0 + 1]
        return (v00 * (1 - fr) * (1 - fc) + v01 * (1 - fr) * fc
                + v10 * fr * (1 - fc) + v11 * fr * fc)

    def heights_lle(self, lat_deg: Any, lon_deg: Any) -> np.ndarray:
        """Vectorised DEM orthometric height (m) at geographic lat/lon (arrays or scalars)."""
        return self._bilinear(np.asarray(lat_deg, dtype=float), np.asarray(lon_deg, dtype=float))

    def height_lle(self, lat_deg: float, lon_deg: float) -> float:
        """DEM orthometric height (m) at a single geographic lat/lon."""
        return float(self._bilinear(np.asarray([lat_deg]), np.asarray([lon_deg]))[0])

    def height_enu(self, east_m: float, north_m: float) -> float:
        """DEM orthometric height (m) at a single local ENU ``(east, north)``."""
        lat, lon, _ = self.enu_to_lle(east_m, north_m)
        return float(self._bilinear(np.asarray([float(lat)]), np.asarray([float(lon)]))[0])

    # ---- surface normal (local gradient, in the ENU frame) ----------------------------------------
    def normal_enu(self, east_m: float, north_m: float, step_m: float | None = None) -> np.ndarray:
        """Unit outward surface normal (East, North, Up) at a local ENU point, from DEM central
        differences taken in the ENU frame. ``step_m`` defaults to the DEM ground resolution so the
        slope reflects the DEM's true posting (no sub-pixel amplification)."""
        s = self.cell_m if step_m is None else float(step_m)
        hxp = self.height_enu(east_m + s, north_m)
        hxm = self.height_enu(east_m - s, north_m)
        hyp = self.height_enu(east_m, north_m + s)
        hym = self.height_enu(east_m, north_m - s)
        dz_de = (hxp - hxm) / (2.0 * s)
        dz_dn = (hyp - hym) / (2.0 * s)
        nrm = np.array([-dz_de, -dz_dn, 1.0], dtype=float)
        return nrm / np.linalg.norm(nrm)

    def normal_lle(self, lat_deg: float, lon_deg: float, step_m: float | None = None) -> np.ndarray:
        """Unit outward surface normal (ENU) at a geographic lat/lon."""
        enu = self.lle_to_enu(lat_deg, lon_deg)
        return self.normal_enu(float(enu[0]), float(enu[1]), step_m=step_m)

    # ---- combined samplers ------------------------------------------------------------------------
    def sample_enu(self, east_m: float, north_m: float, step_m: float | None = None) -> DemSample:
        """DEM height + unit ENU surface normal at a local ENU ``(east, north)`` point."""
        return DemSample(self.height_enu(east_m, north_m), self.normal_enu(east_m, north_m, step_m))

    def sample_lle(self, lat_deg: float, lon_deg: float, step_m: float | None = None) -> DemSample:
        """DEM height + unit ENU surface normal at a geographic lat/lon point."""
        return DemSample(self.height_lle(lat_deg, lon_deg), self.normal_lle(lat_deg, lon_deg, step_m))

    # ---- coverage helper --------------------------------------------------------------------------
    def covers_lle(self, lat_deg: float, lon_deg: float) -> bool:
        """True iff the geographic point lies inside the loaded window's bilinear-valid interior."""
        return bool(self._lon_lo <= lon_deg <= self._lon_hi and self._lat_lo <= lat_deg <= self._lat_hi)
