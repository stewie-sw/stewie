"""Cast-shadow-length metric (H = L*tan(e)) on REAL LROC NAC imagery -- acquisition + measurement.

This module validates the shadow-height cue on real Lunar Reconnaissance Orbiter
Narrow Angle Camera (LROC NAC) products, NOT on renders. It reuses the tested DART shadow code
(`dart.shadow_extract`, `dart.shadow_height`, `dart.rock_taxonomy`) and adds only the NAC-specific
acquisition + co-registration + measurement glue.

DATA (all real, freely public via the LROC PDS node / Orbital Data Explorer -- see PRODUCTS):
 - Two map-projected NAC orthoimages of Giordano Bruno crater (the freshest, most boulder-rich large
   lunar crater) from two NAC stereo-DTM bundles, imaged at two metadata-known Sun elevations
   (32.16 deg and 53.61 deg). Both are georeferenced Equirectangular_Moon GeoTIFFs, so the SAME
   ground point is the SAME world coordinate in both -- co-registration is automatic (no manual
   tie-pointing). This is the "two-split" two-Sun-angle self-consistency design of the proposal.
 - The co-registered 3 m NAC stereo DTM (independent height reference, path 1).

The Sun elevation per frame is read from the source NAC frame geometry (incidence angle, via the
LROC PDS label / the ODE geometry index): elevation = 90 - incidence. The map/pixel scale (GSD)
comes from the GeoTIFF transform.

No synthetic data, no fabricated heights. Heights are recovered only from measured shadow pixels and
metadata Sun elevation; where a clean, independent ground-truth height is not obtainable the code
records the specific blocker rather than inventing a number.
"""
# PROVENANCE: STEWIE benchmark over real LROC NAC PDS products (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import uniform_filter

from dart.rock_taxonomy import shadow_height_m
from dart.shadow_height import measure_shadow_length_px

# Real, freely-public LROC products used (LRO-L-LROC-5-RDR NAC DTM bundles; source NAC frames are
# LRO-L-LROC-3-CDR). Geometry: incidence/emission/GSD from the ODE geometry index (SPICE-derived).
PRODUCTS: dict[str, dict] = {
    "ortho_low_sun": {
        "nac_frame": "M1190012618",
        "dtm_bundle": "NAC_DTM_GIORDNBRN13",
        "ortho_file": "NAC_DTM_GIORDNBRN13_M1190012618_100CM.TIF",
        "incidence_deg": 57.84,
        "sun_elevation_deg": 32.16,
        "emission_deg": 13.87,
        "gsd_m_per_px": 1.0,
        "url": "https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/"
               "EXTRAS/BROWSE/NAC_DTM/GIORDNBRN13/NAC_DTM_GIORDNBRN13_M1190012618_100CM.TIF",
    },
    "ortho_high_sun": {
        "nac_frame": "M156924032",
        "dtm_bundle": "NAC_DTM_GIORDNBRNO4",
        "ortho_file": "NAC_DTM_GIORDNBRNO4_M156924032_60CM.TIF",
        "incidence_deg": 36.39,
        "sun_elevation_deg": 53.61,
        "emission_deg": 3.65,
        "gsd_m_per_px": 0.6,            # the 60CM ortho GeoTIFF grid (source-frame native scale 0.566 m)
        "url": "https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/"
               "EXTRAS/BROWSE/NAC_DTM/GIORDNBRNO4/NAC_DTM_GIORDNBRNO4_M156924032_60CM.TIF",
    },
    "dem": {
        "dtm_bundle": "NAC_DTM_GIORDNBRN13",
        "dem_file": "NAC_DTM_GIORDNBRN13.TIF",
        "post_spacing_m": 3.0,
        "url": "https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/"
               "DATA/SDP/NAC_DTM/GIORDNBRN13/NAC_DTM_GIORDNBRN13.TIF",
    },
}

WorldBox = tuple[float, float, float, float]  # (west, south, east, north) in the GeoTIFF CRS metres


@dataclass(frozen=True)
class Window:
    """A georeferenced image window: pixels plus the affine transform and ground sample distance."""

    pixels: np.ndarray
    transform: rasterio.Affine
    gsd_m: float

    def world_to_rc(self, wx: float, wy: float) -> tuple[float, float]:
        col, row = ~self.transform * (wx, wy)
        return float(row), float(col)


def load_window(path: str, box: WorldBox, *, out_shape: tuple[int, int] | None = None) -> Window:
    """Read a georeferenced window (world box, CRS metres) from a GeoTIFF as a Window."""
    with rasterio.open(path) as ds:
        win = from_bounds(*box, ds.transform)
        pix = ds.read(1, window=win, out_shape=out_shape).astype(np.float32)
        tf = ds.window_transform(win) if out_shape is None else _scaled_transform(ds, win, out_shape)
        gsd = float(abs(tf.a))
    return Window(pixels=pix, transform=tf, gsd_m=gsd)


def _scaled_transform(ds: rasterio.DatasetReader, win, out_shape: tuple[int, int]) -> rasterio.Affine:
    base = ds.window_transform(win)
    sx = win.width / out_shape[1]
    sy = win.height / out_shape[0]
    return base * rasterio.Affine.scale(sx, sy)


def coregistration_highpass_corr(path_a: str, path_b: str, box: WorldBox,
                                 *, shape: tuple[int, int] = (750, 750), hp: int = 15) -> float:
    """Pearson correlation of the high-pass structure of two orthoimages sampled over the SAME world
    box. Albedo/illumination differ between Sun angles (DC term), so we high-pass first; a positive
    correlation confirms the two map-projected frames register to the same ground (geometry), which
    is what makes the two-Sun self-consistency test valid without manual tie-pointing."""
    a = load_window(path_a, box, out_shape=shape).pixels
    b = load_window(path_b, box, out_shape=shape).pixels
    m = (a > 0) & (b > 0)
    if m.sum() < 100:
        raise ValueError("too little valid overlap to assess co-registration")
    ah = a - uniform_filter(a, hp)
    bh = b - uniform_filter(b, hp)
    return float(np.corrcoef(ah[m].ravel(), bh[m].ravel())[0, 1])


def dem_relief(dem_path: str, box: WorldBox) -> dict:
    """Min/max/relief of the DEM over a world box. At NAC-DTM post spacing (2-3 m) the resolvable
    feature scale is several posts (>~15-20 m), so this relief reflects MOUND/hummock topography,
    not individual 10-30 m boulders -- the path-1 limitation this benchmark documents."""
    with rasterio.open(dem_path) as ds:
        win = from_bounds(*box, ds.transform)
        d = ds.read(1, window=win).astype(np.float32)
        post = float(abs(ds.transform.a))
    d = d[np.isfinite(d) & (d > -1e30)]
    if d.size == 0:
        raise ValueError("no valid DEM samples in window")
    return {"min_m": float(d.min()), "max_m": float(d.max()),
            "relief_m": float(d.max() - d.min()), "post_spacing_m": round(post, 3),
            "min_resolvable_feature_m": round(3.0 * post, 2)}


def recover_height_m(shadow_length_m: float, sun_elevation_deg: float) -> float:
    """H = L*tan(e) -- the tested DART recovery (dart.rock_taxonomy.shadow_height_m)."""
    return shadow_height_m(shadow_length_m, sun_elevation_deg)


def directed_shadow_length_m(gray: np.ndarray, base_rc: tuple[float, float],
                             shadow_image_azimuth_deg: float, gsd_m: float, **kw) -> float:
    """Shadow length [m] measured ONLY along the supplied (true) anti-solar image azimuth, by walking
    the contiguous dark run from the caster base. This is the correct measurement: it reads the
    boulder's actual cast shadow, not whatever dark feature happens to be longest. Reuses the DART
    ray-walk (dart.shadow_height.measure_shadow_length_px), which walks anti_solar_dir(sun_azimuth);
    so sun_azimuth = shadow_azimuth - 180."""
    r, c = base_rc
    sun_az = (shadow_image_azimuth_deg - 180.0) % 360.0
    length_px = measure_shadow_length_px(gray, float(c), float(r), sun_az, **kw)
    return float(length_px) * gsd_m


def longest_dark_run_any_direction(gray: np.ndarray, base_rc: tuple[float, float], gsd_m: float,
                                   *, dark_frac: float = 0.5, lit_frac: float = 0.85,
                                   max_len_px: int = 60, n_dirs: int = 36) -> tuple[float, float | None]:
    """Longest contiguous dark run that TERMINATES in lit ground, searched over ALL directions.

    This is the WRONG way to measure a shadow and is included to demonstrate the artifact it creates:
    because any dark feature's extent scales ~1/tan(e), recovering H = L*tan(e) from the undirected
    longest run yields spurious two-Sun "agreement" even when the chosen directions are inconsistent
    (i.e. not the real anti-solar azimuth). Returns (length_m, image_azimuth_deg|None)."""
    g = np.asarray(gray, float)
    h, w = g.shape
    r, c = int(round(base_rc[0])), int(round(base_rc[1]))
    y0, y1 = max(0, r - 6), min(h, r + 7)
    x0, x1 = max(0, c - 6), min(w, c + 7)
    bg = float(np.median(g[y0:y1, x0:x1])) if (y1 > y0 and x1 > x0) else float(g.mean())
    thr, lit = dark_frac * bg, lit_frac * bg
    best_len, best_az = 0.0, None
    for k in range(n_dirs):
        a = math.radians(k * 360.0 / n_dirs)
        dx, dy = math.cos(a), math.sin(a)
        run, ended = 0, False
        for s in range(2, max_len_px):
            x, y = int(round(c + dx * s)), int(round(r + dy * s))
            if not (0 <= x < w and 0 <= y < h):
                break
            if g[y, x] < thr:
                run = s
            elif g[y, x] > lit and run > 0:
                ended = True
                break
            elif run > 0:
                break
        if ended and run > best_len:
            best_len, best_az = float(run), (k * 360.0 / n_dirs) % 360.0
    return best_len * gsd_m, best_az


def circular_concentration(azimuths_deg: list[float] | np.ndarray) -> float:
    """Mean resultant length R in [0,1] of a set of directions. R~1 = one consistent direction (a real
    single Sun); R~0 = scattered (no real common shadow direction -- the artifact tell)."""
    a = np.radians(np.asarray(azimuths_deg, float))
    if a.size == 0:
        return 0.0
    return float(np.hypot(np.cos(a).sum(), np.sin(a).sum()) / a.size)
