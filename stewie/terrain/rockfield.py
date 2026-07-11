"""Spatial-k Golombek rock-dispersion producer over the REAL lunar DEM (viz2 plan v4, task D1).

WHY this exists. ``procgen.sample_boulders`` inverts the Golombek cumulative-fractional-AREA
size-frequency law F_k(D) = k*exp(-q(k)*D) into a Poisson clast list, but its self-declared gap
(``procgen.py:311-313``) is that clasts are sampled INDEPENDENTLY with a single, spatially-uniform
abundance ``k`` -- no clustering, no crater-rim / ejecta correlation. On a real lunar surface the
total-fractional-area ``k`` is NOT uniform: Bandfield et al. (2011) find Diviner rock abundance is
<1% over most polar terrain and rises only at fresh crater rims and their ejecta. This module fixes
that gap: it derives a per-cell abundance field ``k(x, y)`` from the REAL DEM's morphology (a sparse
polar BACKGROUND rising toward the fresh-EJECTA value where the heightfield shows crater rims / high
curvature / locally-steep ejecta slopes), then samples each k-stratum by REUSING
``procgen.sample_boulders``'s inversion, spatially restricted by the stratum mask.

HONESTY (the load-bearing tag). The spatial abundance field is ``[CALIB]`` -- a sourced-envelope
CALIBRATION model, anchored to Bandfield 2011 background/ejecta abundances, NOT a Haworth-measured
rock count (no NAC ortho of the Haworth work area is on disk; D5 is BLOCKED on that real data). The
per-clast ``buried_frac`` is a genuine ``[UNKNOWN]`` wide envelope U(0.1, 0.7) (Ruesch & Woehler
2021 give only a qualitative direction, no numeric distribution). Both tags are carried verbatim in
the emitted manifest. The size-frequency LAW itself (Golombek 2003) is sourced and correct as-is.

DETERMINISM (contract §3). Generation is a pure function of the GLOBAL coordinate: each k-stratum's
Poisson draw is seeded by ``procgen_seed.coord_seed`` of the window's global origin (plus the
stratum index as the octave field), so the SAME world window yields a byte-identical clast list
regardless of render/visit order.

Pure NumPy. Reuses: ``procgen.sample_boulders`` (the SFD inversion), ``procgen_seed.coord_seed``
(the coordinate-hashed seed), ``site_dem.slope_deg_map`` (the real slope producer), and
``server.gis_layers.curvature_laplacian`` (the real Laplacian-curvature producer, imported lazily so
this terrain-layer module carries no import-time dependency on the server layer).
"""

from __future__ import annotations

import json
import os

import numpy as np

from stewie.specs import constants as K
from stewie.terrain import procgen, procgen_seed
from stewie.terrain.site_dem import slope_deg_map

# Resolution class for coord_seed (procgen_seed.py:88): an INDEPENDENT noise family from the DEM
# residual overlay (class 0) and craters, so the rock draw never collides with those layers.
_ROCK_CELL_CLASS = 101


# ---------------------------------------------------------------------------
# The Golombek size-frequency MODEL (closed form the sampler inverts).
# ---------------------------------------------------------------------------

def golombek_cumulative_area(k: float, diameter_m: float | np.ndarray):
    """Golombek cumulative FRACTIONAL AREA covered by rocks of diameter >= D.

        F_k(D) = k * exp(-q(k) * D),   q(k) = 1.79 + 0.152/k   [1/m]

    (Golombek et al. 2003, LPSC XXXIV; Golombek & Rapp 1997, doi:10.1029/96JE03319.) ``k`` is the
    (scalar) TOTAL fractional area covered by all rocks (D -> 0). This is the UNTRUNCATED model; the
    finite sampler ``procgen.sample_boulders`` covers only [D, d_max], whose expectation is
    ``golombek_cumulative_area(k, D) - golombek_cumulative_area(k, d_max)``. ``D`` may be a scalar
    or an array (returned elementwise).
    """
    q = K.golombek_q(float(k))
    D = np.asarray(diameter_m, dtype=np.float64)
    out = float(k) * np.exp(-q * D)
    return float(out) if out.ndim == 0 else out


# ---------------------------------------------------------------------------
# Real-DEM morphology -> rim/ejecta indicator -> per-cell abundance k(x, y).
# ---------------------------------------------------------------------------

def curvature_field(dem: np.ndarray, cell_m: float) -> np.ndarray:
    """Laplacian curvature grad^2 z [1/m] from the real DEM.

    Reuses the SAME Laplacian producer the LY-05 curvature drape uses
    (``server.gis_layers.curvature_laplacian``), imported lazily so this terrain-layer module
    does not depend on the server layer at import time. Fresh crater rims / ejecta hummocks are
    high-|curvature| features; near-planar background is ~0.
    """
    from stewie.server.gis_layers import curvature_laplacian
    return curvature_laplacian(np.asarray(dem, dtype=np.float64), cell_m)


def ejecta_rim_indicator(dem: np.ndarray, cell_m: float) -> np.ndarray:
    """A [0, 1] fresh-rim / ejecta indicator from the REAL DEM morphology.

    Documented, sourced mapping (the [CALIB] modelling choice):
      * Bandfield et al. (2011): polar rock abundance is <1% over MOST terrain and rises only at
        FRESH crater rims and their EJECTA. Absolute slope alone therefore must NOT drive k up
        (generic Haworth ground is 15-20 deg everywhere yet still rock-sparse); the elevated
        abundance keys on LOCAL morphological ANOMALY, not on absolute slope.
      * Rim/ejecta proxies from the heightfield:
          - ``s_curv``  -- |Laplacian curvature| normalised by its 95th-percentile over the window
            (a robust, self-calibrating saturation): crater rims / ejecta hummocks are the sharp,
            high-|curvature| tail; smooth background is ~0.
          - ``s_slope`` -- slope ANOMALY, (slope - p50)/(p95 - p50) clipped to [0, 1]: locally
            steep crater walls / ejecta faces exceed the window's median slope; the flat background
            (<= median) contributes 0.
      * ``s = max(s_curv, s_slope)`` -- ANY of "fresh rim OR high curvature OR steep ejecta slope".

    The 95th/50th-percentile normalisation is WITHIN-WINDOW and self-calibrating because no absolute
    polar rock-abundance-vs-morphology calibration exists (Bandfield 2011 is Diviner-global,
    equatorial-anchored) -- hence the field is tagged ``[CALIB]``, not a measurement. A perfectly
    flat window yields all-zero indicator (k collapses to the background everywhere).
    """
    dem = np.asarray(dem, dtype=np.float64)
    slope = slope_deg_map(dem, cell_m)
    curv = np.abs(curvature_field(dem, cell_m))

    curv_sat = float(np.percentile(curv, 95.0))
    s_curv = np.clip(curv / curv_sat, 0.0, 1.0) if curv_sat > 0.0 else np.zeros_like(curv)

    sl50 = float(np.percentile(slope, 50.0))
    sl95 = float(np.percentile(slope, 95.0))
    span = sl95 - sl50
    s_slope = np.clip((slope - sl50) / span, 0.0, 1.0) if span > 0.0 else np.zeros_like(slope)

    return np.maximum(s_curv, s_slope)


def spatial_k_field(dem: np.ndarray, cell_m: float, *,
                    k_background: float = K.BOULDER_K_BACKGROUND,
                    k_ejecta: float = K.BOULDER_K_EJECTA) -> np.ndarray:
    """Per-cell Golombek total-fractional-area abundance k(x, y) over the REAL DEM.

    ``k = k_background + s*(k_ejecta - k_background)`` with ``s`` the [0, 1] ejecta/rim indicator
    (``ejecta_rim_indicator``), then CLAMPED to the Bandfield-anchored envelope
    ``[BOULDER_K_BACKGROUND_MIN, BOULDER_K_EJECTA_MAX]`` so no cell ever leaves the sourced band.
    The interior interpolation background(0.005) -> ejecta(0.20) already lies inside that envelope;
    the clamp is a hard guarantee that also holds if a caller overrides the endpoints. [CALIB].
    """
    s = ejecta_rim_indicator(dem, cell_m)
    k = k_background + s * (k_ejecta - k_background)
    return np.clip(k, K.BOULDER_K_BACKGROUND_MIN, K.BOULDER_K_EJECTA_MAX)


# ---------------------------------------------------------------------------
# The producer: stratified Golombek sampling over the real k-field.
# ---------------------------------------------------------------------------

def rock_field(dem: np.ndarray, cell_m: float, *,
               world_x0: float = 0.0, world_y0: float = 0.0, world_seed: int = 0,
               n_strata: int = 6, d_min_m: float = 0.25, d_max_m: float = 0.6,
               k_background: float = K.BOULDER_K_BACKGROUND,
               k_ejecta: float = K.BOULDER_K_EJECTA) -> dict:
    """Spatially-correlated Golombek rock field over a REAL DEM window.

    Steps:
      1. ``spatial_k_field`` -> per-cell abundance k(x, y) from the real morphology (clamped to the
         sourced envelope).
      2. Quantise k into ``n_strata`` linear strata; each stratum's representative k is the MEAN of
         the continuous k over its member cells (its actual mean abundance).
      3. For each non-empty stratum, REUSE ``procgen.sample_boulders`` to sample the WHOLE window at
         that stratum's k (its exact SFD inversion + Poisson draw + buried_frac), seeded by
         ``coord_seed`` of the window's global origin with the stratum index as the octave. THIN the
         result by the stratum mask -- keep only clasts whose cell belongs to this stratum. Poisson
         thinning by a spatial indicator is exact, so the kept clasts are a Poisson field at
         intensity(k_stratum) restricted to the stratum's cells; the union over the partition of
         cells is an inhomogeneous field whose local intensity is the cell's own stratum k.
      4. Renumber clast ids into a single stable 0..n-1 sequence (stratum order is deterministic ->
         the concatenation, hence the whole list, is byte-identical for the same world window).

    Returns a dict with ``clasts`` (each: id, center_m [x, y, z], radius_m, shape, buried_frac,
    stratum), ``k_field`` (the 2-D abundance array), ``stratum_id`` (per-cell stratum index),
    ``strata`` (per-stratum summary), and ``manifest`` (k-field summary + provenance + honesty tags).
    """
    dem = np.asarray(dem, dtype=np.float64)
    height, width = dem.shape
    k_field = spatial_k_field(dem, cell_m, k_background=k_background, k_ejecta=k_ejecta)

    # Quantise into strata. A flat/degenerate field (k.min == k.max) collapses to one stratum.
    kmin, kmax = float(k_field.min()), float(k_field.max())
    if kmax - kmin <= 1e-12:
        stratum_id = np.zeros(k_field.shape, dtype=np.int64)
    else:
        edges = np.linspace(kmin, kmax, n_strata + 1)
        stratum_id = np.clip(np.digitize(k_field, edges[1:-1]), 0, n_strata - 1).astype(np.int64)

    clasts: list[dict] = []
    strata: list[dict] = []
    cid = 0
    cell_area = cell_m * cell_m
    for s in range(n_strata):
        mask = stratum_id == s
        n_cells = int(mask.sum())
        if n_cells == 0:
            continue
        k_rep = float(k_field[mask].mean())
        # Coordinate-hashed seed: pure function of the WORLD origin + stratum (octave). Same window
        # -> same seed -> byte-identical draw (contract §3).
        seed = procgen_seed.coord_seed(world_x0, world_y0, octave=s,
                                       base_cell_class=_ROCK_CELL_CLASS, world_seed=world_seed)
        raw = procgen.sample_boulders(width, height, cell_m, k=k_rep,
                                      d_min_m=d_min_m, d_max_m=d_max_m, seed=seed)
        kept = 0
        for c in raw:
            x, _y, z = c["center_m"]
            col = min(int(x / cell_m), width - 1)
            row = min(int(z / cell_m), height - 1)
            if mask[row, col]:
                rock = dict(c)
                rock["id"] = cid
                rock["stratum"] = s
                clasts.append(rock)
                cid += 1
                kept += 1
        strata.append({
            "stratum": s,
            "k": round(k_rep, 6),
            "n_cells": n_cells,
            "area_m2": round(n_cells * cell_area, 4),
            "n_clasts": kept,
        })

    manifest = _build_manifest(k_field, strata, cell_m, width, height, d_min_m, d_max_m,
                               n_strata, k_background, k_ejecta, len(clasts))
    return {
        "clasts": clasts,
        "k_field": k_field,
        "stratum_id": stratum_id,
        "strata": strata,
        "cell_m": float(cell_m),
        "width": int(width),
        "height": int(height),
        "manifest": manifest,
    }


def rock_field_for_dem_window(bundle_dir: str | None = None, *, r0: int = 0, c0: int = 0,
                              n: int = 256, site: str = "haworth", **kw) -> dict:
    """Convenience: build a ``rock_field`` over a REAL DEM bundle window.

    Reads the [r0:r0+n, c0:c0+n] window from the bundle (streamed via
    ``site_dem.read_dem_window``) and derives the window's TRUE global origin (south-polar-
    stereographic metres, pixel-center convention) from the bundle ``world_bounds_m`` so the
    coordinate-hashed seed is a pure function of the WORLD point (contract §3). ``bundle_dir`` may
    be given explicitly, else it is resolved from the SITES registry for ``site``.
    """
    from stewie.terrain.site_dem import bundle_for_site, read_dem_window

    bundle = bundle_dir or bundle_for_site(site)
    meta = json.load(open(os.path.join(bundle, "metadata.json")))
    grid, bounds = meta["grid"], meta["world_bounds_m"]
    cell = float(grid["cell_m"])
    # Pixel(0,0) CENTER is (x0 + cell/2, y1 - cell/2) on the north-up raster (site_dem convention).
    world_x0 = float(bounds["x0"]) + (c0 + 0.5) * cell
    world_y0 = float(bounds["y1"]) - (r0 + 0.5) * cell
    win, _cell = read_dem_window(r0, c0, n, n, bundle)
    return rock_field(win, cell, world_x0=world_x0, world_y0=world_y0, **kw)


# ---------------------------------------------------------------------------
# Manifest (k-field summary + provenance + verbatim honesty tags).
# ---------------------------------------------------------------------------

def _build_manifest(k_field, strata, cell_m, width, height, d_min_m, d_max_m,
                    n_strata, k_background, k_ejecta, n_clasts) -> dict:
    return {
        "kind": "spatial_k_golombek_rockfield",
        # Verbatim honesty tags (D1 clause 5). The spatial abundance is a sourced-envelope
        # CALIBRATION, NOT a Haworth measurement; buried_frac is a genuine wide-envelope UNKNOWN.
        "honesty_tags": {
            "spatial_abundance_k": "[CALIB]",
            "buried_frac": "[UNKNOWN]",
        },
        "honesty_note": (
            "The spatial rock abundance k(x,y) is a [CALIB] sourced-envelope model: a sparse polar "
            "background (Bandfield 2011, <1% over most terrain) rising toward the fresh-ejecta value "
            "where the REAL DEM shows crater rims / high curvature / locally-steep ejecta slopes. It "
            "is NOT a Haworth-measured rock count (no NAC ortho of the work area is on disk; the "
            "measured calibration D5 is BLOCKED on that real data). The size-frequency LAW itself "
            "(Golombek 2003) is sourced and correct. buried_frac is an [UNKNOWN] wide envelope "
            "U(0.1,0.7) (Ruesch & Woehler 2021 give only a qualitative age-monotonic direction)."
        ),
        "sfd_model": "F_k(D) = k * exp(-q(k) * D); q(k) = 1.79 + 0.152/k  [cumulative fractional AREA]",
        "mapping": (
            "k = clamp(k_background + s*(k_ejecta - k_background), envelope_min, envelope_max); "
            "s = max(|curvature|/p95(|curvature|), (slope - p50(slope))/(p95 - p50)) in [0,1] from "
            "the real heightfield (server.gis_layers.curvature_laplacian + site_dem.slope_deg_map). "
            "Percentile normalisation is within-window/self-calibrating (no absolute polar "
            "rock-vs-morphology calibration exists) -- hence [CALIB]."
        ),
        "k_field": {
            "min": round(float(k_field.min()), 6),
            "max": round(float(k_field.max()), 6),
            "mean": round(float(k_field.mean()), 6),
            "background": float(k_background),
            "ejecta": float(k_ejecta),
            "envelope_min": float(K.BOULDER_K_BACKGROUND_MIN),
            "envelope_max": float(K.BOULDER_K_EJECTA_MAX),
            "n_cells": int(k_field.size),
            "n_strata": int(n_strata),
            "cell_m": float(cell_m),
            "window_m": [round(width * cell_m, 4), round(height * cell_m, 4)],
        },
        "strata": strata,
        "diameter_band_m": [float(d_min_m), float(d_max_m)],
        "n_clasts": int(n_clasts),
        "provenance": {
            "sfd": ("Golombek et al. 2003 (LPSC XXXIV): F_k(D)=k*exp[-q(k)D], q(k)=1.79+0.152/k; "
                    "Golombek & Rapp 1997 (doi:10.1029/96JE03319). [FIXED law]"),
            "spatial_abundance": ("Bandfield et al. 2011 (JGR 116, E00H02, doi:10.1029/2011JE003866): "
                                  "Diviner rock abundance <1% over most polar terrain, elevated at "
                                  "fresh crater rims/ejecta. [CALIB envelope]"),
            "h_over_d": ("Demidov & Basilevsky 2014 (Solar System Research 48(5):324-353, "
                         "doi:10.1134/S0038094614050013): boulder height/diameter 0.60 +/- 0.03."),
            "buried_frac": ("Ruesch & Woehler 2021 (arXiv:2109.00052): only a qualitative "
                            "age-monotonic direction, no numeric distribution -> [UNKNOWN] U(0.1,0.7)."),
        },
        "citations": [
            "Golombek et al. 2003 (LPSC XXXIV); Golombek & Rapp 1997 (doi:10.1029/96JE03319)",
            "Bandfield et al. 2011 (JGR 116, E00H02, doi:10.1029/2011JE003866)",
            "Demidov & Basilevsky 2014 (Solar System Research 48(5):324-353, doi:10.1134/S0038094614050013)",
        ],
    }
