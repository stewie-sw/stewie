"""Cross-site DEM comparison (viz2 PRD Phase G / G2, G2a, G4) — the backend producer.

The counterpart to :mod:`dart.dem_cross` (imagery-vs-DEM): where ``dem_cross`` cross-validates ONE
site's imagery against its own DEM, this module compares the REAL on-disk lunar DEM bundles under
``samples/lunar_dem/`` AGAINST EACH OTHER — a per-site statistics table (slope, roughness, relief,
cell size) and, where two sites' footprints TRULY overlap in the shared frame, a residual map.

Discipline (no synthetic terrain, no fabricated stats):
  * Every statistic comes from the REAL producers already in the tree — :func:`site_dem.slope_deg_map`
    for slope, :func:`dem_cross.dem_layers` for roughness — run over the bundle's real ``heightmap.rf32``.
  * Provenance (source + citation) is read VERBATIM from each bundle's ``metadata.json``
    ``dem_provenance`` block: the LOLA Product-78 tiles carry Barker/Mazarico; the LRO NAC
    Shape-from-Shading tile carries Alexandrov & Beyer 2018 (a DIFFERENT instrument + method). The
    table never re-types a citation; it echoes what the bundle claims.
  * A residual is produced ONLY where two footprints genuinely overlap in the shared south-polar
    stereographic metric frame (``world_bounds_m``). The bundled sites are disjoint craters around the
    pole, so every real pair takes the EXPLICIT REFUSAL path — the module refuses to difference tiles
    that do not cover the same ground rather than invent an alignment.
  * G2a (the one honest overlap that DOES exist): the 1 m LRO NAC SfS Haworth drive-site tile and the
    5 m LOLA Product-78 backbone cover the SAME ground at two resolutions/instruments. Re-cropping the
    raw 5 m Haworth ``*_surf.tif`` over the 1 m tile's footprint yields a REAL resolution-difference
    residual (SfS 1 m − LOLA 5 m). If the raw 5 m source is not on host, G2a is BLOCKED (reported,
    never faked).

Frame note (DEM_CROSSREF_2026-06-11 §a): all Product-78 tiles AND the SfS strip are published in the
one south-polar stereographic frame (IAU_2015:30135, R = 1737400 m sphere), so ``world_bounds_m`` are
directly comparable metres — an overlap test is a rectangle intersection, no reprojection.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass

import numpy as np

from dart.dem_cross import dem_layers
from dart.dem_import import crop_square, load_lola_geotiff
from stewie.terrain.site_dem import load_haworth_dem, slope_deg_map

# repo root from dart/dem_site_compare.py -> dart -> <repo>
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SITE_ROOT = os.path.join(_REPO_ROOT, "samples", "lunar_dem")

# G2a: the raw 5 m PGDA LOLA Haworth source (host asset, not repo-committed). Overridable via
# $STEWIE_LOLA_5MPP_DIR for portability; absence => G2a BLOCKED (never fabricated).
_LOLA_5MPP_DIR = os.environ.get("STEWIE_LOLA_5MPP_DIR", "/mnt/projects/datasets/lola_5mpp")
DEFAULT_HAWORTH_5M_SRC = os.path.join(_LOLA_5MPP_DIR, "Haworth_final_adj_5mpp_surf.tif")


# ---------------------------------------------------------------------------
# Bundle enumeration + metadata.
# ---------------------------------------------------------------------------

def list_site_bundles(root: str = DEFAULT_SITE_ROOT) -> list[str]:
    """Absolute paths of the on-disk DEM bundle DIRECTORIES under ``root`` (a bundle == a directory
    that carries a ``metadata.json``), sorted by name. This is the ONE enumeration the cross-site
    comparator and the viz2 site switcher share, so the compare table's rows are exactly the bundles
    on disk — no hard-coded site list to drift out of sync."""
    out = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "metadata.json")):
            out.append(os.path.abspath(d))
    return out


def _load_meta(bundle: str) -> dict:
    with open(os.path.join(bundle, "metadata.json")) as fh:
        return json.load(fh)


def _has_heightmap(bundle: str) -> bool:
    return os.path.exists(os.path.join(bundle, "heightmap.rf32"))


# ---------------------------------------------------------------------------
# Per-site statistics row (G2).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SiteStat:
    """One real DEM bundle's comparison row. ``citation``/``source`` are echoed VERBATIM from the
    bundle's ``metadata.json`` ``dem_provenance`` — the SfS tile carries Alexandrov & Beyer, the LOLA
    tiles carry Barker/Mazarico. Slope/roughness are ``None`` for a metadata-only bundle (no
    ``heightmap.rf32`` to run the real producers over) — reported honestly, not zero-filled."""
    name: str
    region: str
    cell_m: float
    width: int
    height: int
    extent_km: float                       # tile side (width * cell / 1000), rounded
    height_min_m: float
    height_max_m: float
    relief_m: float                        # height_max - height_min
    slope_median_deg: float | None
    slope_rms_deg: float | None
    roughness_median_m: float | None
    has_heightmap: bool
    source: str                            # dem_provenance.source, verbatim
    citation: str                          # dem_provenance.citation, verbatim
    footprint_m: tuple[float, float, float, float]  # (xmin, ymin, xmax, ymax) in the shared frame


def site_stat(bundle: str) -> SiteStat:
    """Build one :class:`SiteStat` from a real bundle. Slope (median + RMS) via the real
    :func:`site_dem.slope_deg_map`; roughness (median windowed height-std) via
    :func:`dem_cross.dem_layers`; both run over the on-disk ``heightmap.rf32``. Height range is read
    off the real grid when a heightmap is present, else off ``metadata.json height_range_m``."""
    meta = _load_meta(bundle)
    name = os.path.basename(os.path.normpath(bundle))
    g = meta["grid"]
    cell = float(g["cell_m"])
    w, h = int(g["width"]), int(g["height"])
    prov = meta.get("dem_provenance", {}) or {}
    fp = bundle_footprint(meta)

    slope_med: float | None = None
    slope_rms: float | None = None
    rough_med: float | None = None
    if _has_heightmap(bundle):
        Z, cell_l = load_haworth_dem(bundle_dir=bundle)     # (Z [m], cell_m); the real loader
        slope = slope_deg_map(Z, cell_l)
        rough = dem_layers((Z, cell_l))["roughness_m"]
        slope_med = float(np.median(slope))
        slope_rms = float(np.sqrt(np.mean(slope * slope)))
        rough_med = float(np.median(rough))
        hmin, hmax = float(Z.min()), float(Z.max())
    else:
        hr = meta.get("height_range_m") or [float("nan"), float("nan")]
        hmin, hmax = float(hr[0]), float(hr[1])

    return SiteStat(
        name=name, region=str(meta.get("region", "")), cell_m=cell, width=w, height=h,
        extent_km=round(w * cell / 1000.0, 3),
        height_min_m=hmin, height_max_m=hmax, relief_m=hmax - hmin,
        slope_median_deg=slope_med, slope_rms_deg=slope_rms, roughness_median_m=rough_med,
        has_heightmap=_has_heightmap(bundle),
        source=str(prov.get("source", "")), citation=str(prov.get("citation", "")),
        footprint_m=fp,
    )


def compare_table(root: str = DEFAULT_SITE_ROOT) -> list[SiteStat]:
    """The cross-site comparison table: one :class:`SiteStat` per on-disk bundle under ``root``,
    in the same order as :func:`list_site_bundles`. Rows == the bundles actually on disk."""
    return [site_stat(b) for b in list_site_bundles(root)]


# ---------------------------------------------------------------------------
# Footprint overlap + residual (G2).
# ---------------------------------------------------------------------------

def bundle_footprint(bundle_or_meta) -> tuple[float, float, float, float]:
    """Normalised footprint ``(xmin, ymin, xmax, ymax)`` [m] from ``world_bounds_m`` — the tile's
    extent in the shared south-polar stereographic frame. Accepts a bundle dir or a parsed metadata
    dict."""
    meta = bundle_or_meta if isinstance(bundle_or_meta, dict) else _load_meta(bundle_or_meta)
    b = meta["world_bounds_m"]
    return (min(b["x0"], b["x1"]), min(b["y0"], b["y1"]),
            max(b["x0"], b["x1"]), max(b["y0"], b["y1"]))


def footprint_overlap(fa, fb) -> tuple[float, float, float, float] | None:
    """The overlap rectangle of two footprints, or ``None`` if they are disjoint (or merely touch
    with zero area). Rectangle intersection in the shared metric frame — no reprojection."""
    x0 = max(fa[0], fb[0]); y0 = max(fa[1], fb[1])
    x1 = min(fa[2], fb[2]); y1 = min(fa[3], fb[3])
    return (x0, y0, x1, y1) if (x1 > x0 and y1 > y0) else None


def site_residual(bundle_a: str, bundle_b: str, *, keep_array: bool = False) -> dict:
    """Difference two site DEMs where their footprints TRULY overlap; else the explicit refusal path.

    Returns a dict with ``overlap`` (bool) and ``reason`` (empty on success, else the refusal). On a
    real overlap where BOTH bundles carry a heightmap, the residual (A − B) is sampled on the overlap
    at ``bundle_b``'s cell grid (``a`` bilinear-nearest resampled onto it) and the stats
    (n / mean / median / rms / max_abs, all metres) are returned; ``keep_array`` also returns the 2-D
    residual. Refuses when the footprints are disjoint OR when either side is metadata-only (no
    heightmap to difference) — it never fabricates an alignment or a surface."""
    ma, mb = _load_meta(bundle_a), _load_meta(bundle_b)
    na = os.path.basename(os.path.normpath(bundle_a))
    nb = os.path.basename(os.path.normpath(bundle_b))
    ov = footprint_overlap(bundle_footprint(ma), bundle_footprint(mb))
    if ov is None:
        return {"overlap": False, "a": na, "b": nb,
                "reason": f"footprints disjoint in the shared frame ({na} and {nb} cover "
                          "different ground) — refusing to difference non-overlapping tiles"}
    if not _has_heightmap(bundle_a) or not _has_heightmap(bundle_b):
        missing = na if not _has_heightmap(bundle_a) else nb
        return {"overlap": True, "a": na, "b": nb, "overlap_rect_m": ov,
                "reason": f"{missing} is metadata-only (no heightmap.rf32) — cannot difference"}

    Za, ca = load_haworth_dem(bundle_dir=bundle_a)
    Zb, cb = load_haworth_dem(bundle_dir=bundle_b)
    res = _resample_and_diff(Za, bundle_footprint(ma), ca, Zb, bundle_footprint(mb), cb, ov)
    out = {"overlap": True, "a": na, "b": nb, "overlap_rect_m": ov, "reason": "",
           "grid_cell_m": float(cb), **_residual_stats(res)}
    if keep_array:
        out["residual_m"] = res
    return out


def _north_up_affine(footprint, cell):
    """First-pixel (row0,col0) CENTER for a north-up raster over ``footprint`` at ``cell`` (row 0 =
    max Y). Matches the ``site_dem`` pixel-center convention (ax0 = x0 + cell/2, ay0 = y1 - cell/2)."""
    xmin, _ymin, _xmax, ymax = footprint
    return xmin + cell / 2.0, ymax - cell / 2.0


def _resample_and_diff(Za, fa, ca, Zb, fb, cb, overlap_rect) -> np.ndarray:
    """A − B over the overlap, sampled at B's cell centers. Each B node's world (X, Y) is mapped to
    the nearest A cell (clamped in-bounds); nodes whose A sample falls off A's grid are dropped
    (NaN). Nearest-cell sampling only — no interpolated (invented) heights."""
    ax0, ay0 = _north_up_affine(fa, ca)
    bx0, by0 = _north_up_affine(fb, cb)
    x0, y0, x1, y1 = overlap_rect
    # B nodes inside the overlap
    bc0 = int(np.ceil((x0 - bx0) / cb)); bc1 = int(np.floor((x1 - bx0) / cb))
    br0 = int(np.ceil((by0 - y1) / cb)); br1 = int(np.floor((by0 - y0) / cb))
    br0 = max(br0, 0); bc0 = max(bc0, 0)
    br1 = min(br1, Zb.shape[0] - 1); bc1 = min(bc1, Zb.shape[1] - 1)
    rows = np.arange(br0, br1 + 1); cols = np.arange(bc0, bc1 + 1)
    if rows.size == 0 or cols.size == 0:
        return np.empty((0, 0), dtype=float)
    Xc = bx0 + cols * cb                     # world X per B column
    Yr = by0 - rows * cb                     # world Y per B row
    acol = np.round((Xc - ax0) / ca).astype(int)
    arow = np.round((ay0 - Yr) / ca).astype(int)
    okc = (acol >= 0) & (acol < Za.shape[1])
    okr = (arow >= 0) & (arow < Za.shape[0])
    sub_b = Zb[br0:br1 + 1, bc0:bc1 + 1].astype(float)
    A = np.full(sub_b.shape, np.nan)
    ar = arow[okr]; ac = acol[okc]
    A[np.ix_(okr, okc)] = Za[np.ix_(ar, ac)].astype(float)
    return A - sub_b


def _residual_stats(res: np.ndarray) -> dict:
    finite = res[np.isfinite(res)] if res.size else res.reshape(-1)
    if finite.size == 0:
        return {"n": 0, "mean_m": None, "median_m": None, "rms_m": None, "max_abs_m": None}
    return {"n": int(finite.size), "mean_m": float(finite.mean()),
            "median_m": float(np.median(finite)),
            "rms_m": float(np.sqrt(np.mean(finite * finite))),
            "max_abs_m": float(np.abs(finite).max())}


def pairwise_residual_report(root: str = DEFAULT_SITE_ROOT) -> list[dict]:
    """The residual verdict for every unordered pair of on-disk bundles: ``overlap`` + ``reason``.
    For the bundled sites (disjoint craters) every pair refuses — the honest cross-site result."""
    bundles = list_site_bundles(root)
    out = []
    for i in range(len(bundles)):
        for j in range(i + 1, len(bundles)):
            r = site_residual(bundles[i], bundles[j])
            out.append({k: r[k] for k in ("a", "b", "overlap", "reason")})
    return out


# ---------------------------------------------------------------------------
# G2a — the 1 m SfS vs 5 m LOLA resolution-difference residual (the one real overlap).
# ---------------------------------------------------------------------------

def haworth_1m_vs_5m_residual(sfs_bundle: str | None = None,
                              raw_5m_src: str = DEFAULT_HAWORTH_5M_SRC,
                              *, keep_array: bool = False) -> dict:
    """The honest resolution-difference exhibit: SfS 1 m − LOLA 5 m over the SAME Haworth footprint.

    The committed 1 m LRO NAC Shape-from-Shading drive-site tile and the 5 m LOLA Product-78 backbone
    cover the same ground with DIFFERENT instruments + resolutions, so their difference is a real
    cross-product residual (Alexandrov & Beyer 2018 §5.4 puts SfS-to-LOLA absolute error at the ~1 m
    scale). The raw 5 m ``*_surf.tif`` is re-cropped over the 1 m tile's footprint (``dem_import``),
    then SfS is sampled at the 5 m cell centers and differenced.

    If the raw 5 m source is not on host, returns ``{"blocked": True, "reason": ...}`` — the residual
    is NEVER fabricated from a missing source."""
    sfs_bundle = sfs_bundle or os.path.join(DEFAULT_SITE_ROOT, "haworth_sfs_2km_1m")
    if not os.path.exists(os.path.join(sfs_bundle, "heightmap.rf32")):
        return {"blocked": True, "reason": f"SfS 1 m bundle missing heightmap at {sfs_bundle}"}
    if not os.path.exists(raw_5m_src):
        return {"blocked": True,
                "reason": f"raw 5 m Haworth source not on host at {raw_5m_src} — need the PGDA "
                          "LOLA_5mpp Haworth_final_adj_5mpp_surf.tif (Product 78) to build the residual"}

    meta = _load_meta(sfs_bundle)
    fp = bundle_footprint(meta)                       # 1 m tile footprint
    Z1, c1 = load_haworth_dem(bundle_dir=sfs_bundle)  # 2000x2000 @ 1 m
    xmin, ymin, xmax, ymax = fp
    cx, cy = 0.5 * (xmin + xmax), 0.5 * (ymin + ymax)
    ext = xmax - xmin
    Zraw, aff, _rmeta = load_lola_geotiff(raw_5m_src)
    try:
        Z5, aff5 = crop_square(Zraw, aff, (cx, cy), ext)   # 5 m crop over the 1 m footprint
    except ValueError as e:
        return {"blocked": True,
                "reason": f"raw 5 m Haworth tile does not cover the SfS footprint: {e}"}

    # residual on the 5 m grid: sample SfS 1 m at each 5 m node center (nearest cell), A=SfS, B=LOLA
    ax0, ay0 = _north_up_affine(fp, c1)               # SfS pixel-center affine
    H5, W5 = Z5.shape
    cols = np.arange(W5); rows = np.arange(H5)
    Xc = aff5.x0 + cols * aff5.px
    Yr = aff5.y0 - rows * aff5.px
    scol = np.round((Xc - ax0) / c1).astype(int)
    srow = np.round((ay0 - Yr) / c1).astype(int)
    okc = (scol >= 0) & (scol < Z1.shape[1])
    okr = (srow >= 0) & (srow < Z1.shape[0])
    sfs = np.full((H5, W5), np.nan)
    sfs[np.ix_(okr, okc)] = Z1[np.ix_(srow[okr], scol[okc])].astype(float)
    res = sfs - Z5.astype(float)

    out = {"blocked": False, "a": "haworth_sfs_2km_1m (SfS, 1 m)",
           "b": "Haworth LOLA 5 m re-crop (Product 78)",
           "a_citation": (meta.get("dem_provenance", {}) or {}).get("citation", ""),
           "footprint_m": fp, "cell_a_m": float(c1), "cell_b_m": float(aff5.px),
           **_residual_stats(res)}
    if keep_array:
        out["residual_m"] = res
    return out


# ---------------------------------------------------------------------------
# G4 — provenance pane data (verbatim citation per bundle).
# ---------------------------------------------------------------------------

def provenance_pane(bundle: str) -> dict:
    """The "About this DEM" pane's data for one bundle: the region, instrument, and the VERBATIM
    ``dem_provenance`` source/citation/frame/license. Read straight off ``metadata.json`` — the pane
    echoes what the bundle claims (Barker/Mazarico for a LOLA tile, Alexandrov & Beyer for the SfS
    tile), it does not compose or paraphrase a citation."""
    meta = _load_meta(bundle)
    prov = meta.get("dem_provenance", {}) or {}
    return {
        "name": os.path.basename(os.path.normpath(bundle)),
        "region": str(meta.get("region", "")),
        "source": str(prov.get("source", "")),
        "citation": str(prov.get("citation", "")),
        "frame": str(prov.get("frame", "")),
        "license_basis": str(prov.get("license_basis", "")),
        "cell_m": float(meta.get("grid", {}).get("cell_m", float("nan"))),
    }


# ---------------------------------------------------------------------------
# Pretty-print (CLI / exhibit caption).
# ---------------------------------------------------------------------------

def format_table(rows: list[SiteStat]) -> str:
    """A fixed-width text rendering of the compare table (for the CLI / the plotted-exhibit caption)."""
    hdr = (f"{'site':26s} {'cell':>5s} {'extent':>7s} {'relief':>8s} "
           f"{'slope_med':>9s} {'slope_rms':>9s} {'rough_med':>9s}  provenance")
    lines = [hdr, "-" * len(hdr)]
    for r in rows:
        sm = f"{r.slope_median_deg:7.2f}" if r.slope_median_deg is not None else "    n/a"
        sr = f"{r.slope_rms_deg:7.2f}" if r.slope_rms_deg is not None else "    n/a"
        rm = f"{r.roughness_median_m:7.3f}" if r.roughness_median_m is not None else "    n/a"
        cite = (r.citation[:44] + "…") if len(r.citation) > 45 else r.citation
        lines.append(f"{r.name:26s} {r.cell_m:4.0f}m {r.extent_km:5.1f}km {r.relief_m:7.0f}m "
                     f"{sm:>9s} {sr:>9s} {rm:>9s}  {cite}")
    return "\n".join(lines)


if __name__ == "__main__":  # a quick real-data dump
    tbl = compare_table()
    print(format_table(tbl))
    print("\npairwise residual verdicts:")
    for p in pairwise_residual_report():
        print(f"  {p['a']:24s} x {p['b']:24s} -> "
              f"{'RESIDUAL' if p['overlap'] and not p['reason'] else 'REFUSE: ' + p['reason']}")
    print("\nG2a 1 m-vs-5 m Haworth residual:")
    g2a = haworth_1m_vs_5m_residual()
    if g2a.get("blocked"):
        print(f"  BLOCKED: {g2a['reason']}")
    else:
        print(f"  n={g2a['n']} mean={g2a['mean_m']:.3f} rms={g2a['rms_m']:.3f} "
              f"max_abs={g2a['max_abs_m']:.3f} m  (SfS 1 m − LOLA 5 m)")
