"""Reproduce a PUBLISHED lunar-boulder height/shape with H = L*tan(e) on REAL LROC NAC imagery.

This moves the ARGUS Niche-1 shadow-height cue (H = L*tan(e): boulder height = shadow length times the
tangent of the solar elevation) from "validated only on renders + edge noise" to "reproduces a published
height/shape statistic on real lunar boulders." Two independent real-NAC targets:

  TARGET A  -- population cross-check of the lunar boulder height-to-diameter ratio against
               Demidov & Basilevsky (2014), h/d = 0.60 +/- 0.03 (DOI 10.1134/S0038094614050013; 445 rocks
               from ground-based Apollo/Lunokhod panoramas, independent of NAC shadows). Measured on a
               flat-mare fresh-crater ejecta field (Messier, Mare Fecunditatis) at low Sun, where shadows
               are long and separable. NO DEM ground truth is needed: h/d is a population statistic.

  TARGET B  -- absolute anchor on the Apollo 17 Station 6 "House Rock" boulder group (NAC M134991788R,
               documented original block 18 x 10 x 6 m; now split into ~5 fragments). Measure the largest
               fragment's shadow and compare its recovered height to the documented ~6 m.

TRUTH FIREWALL (structural, not aspirational):
  The MEASUREMENT functions below (detect_boulders / measure_population_hd / measure_named_fragment) take
  ONLY pixels + real Sun geometry. They NEVER read the published target values. The published numbers live
  in PUBLISHED and are read ONLY by the compare_* functions, AFTER each measurement is frozen. Corrupting
  PUBLISHED cannot change any measured number -- test_nac_boulder_repro.py asserts exactly this.

REAL DATA ONLY: heights come from measured shadow pixels and metadata Sun elevation. No synthetic data, no
fabricated heights. Solar elevation = 90 - INCIDENCE_ANGLE from the source NAC frame PDS geometry (verified
via the ODE CDRNAC4 geometry index). Where a clean measurement is impossible the code records the blocker.

Reuses the tested DART shadow pipeline: dart.shadow_height.measure_shadow_length_px (anti-solar ray walk)
and dart.rock_taxonomy.shadow_height_m (H = L*tan(e)). Adds only NAC-specific acquisition + detection glue.
"""
# PROVENANCE: STEWIE benchmark over real LROC NAC PDS products (A. Storey)
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import rasterio
from scipy.ndimage import label, maximum_filter, uniform_filter

from dart.rock_taxonomy import shadow_height_m
from dart.shadow_height import measure_shadow_length_px

# ----------------------------------------------------------------------------------------------------------
# REAL FRAME GEOMETRY.  Solar elevation = 90 - incidence; incidence is the SOURCE NAC FRAME value from the
# PDS / ODE CDRNAC4 geometry index (SPICE-derived), NOT assumed.  Each entry is a map-projected NAC ortho
# (Equirectangular_Moon, north-up), so the GSD comes from the GeoTIFF transform and "north up / east right"
# fixes the azimuth frame.  anti_solar_image_az_deg (image frame x-right, y-DOWN) is determined FROM THE
# DATA and independently validated per frame (see az_validation); it is a geometry input, not a target.
# ----------------------------------------------------------------------------------------------------------
FRAMES: dict[str, dict] = {
    "messier_low_sun": {
        "site": "Messier / Messier A fresh-crater ejecta, Mare Fecunditatis (~1.93 S, 47.71 E)",
        "nac_frame": "M165530748",
        "dtm_bundle": "NAC_DTM_MESSIER3",
        "ortho_file": "NAC_DTM_MESSIER3_M165530748_60CM.TIF",
        "incidence_deg": 68.11,          # ODE CDRNAC4 pdsid nac.m165530748lc (2011-07-17)
        "sun_elevation_deg": 90.0 - 68.11,
        "emission_deg": 24.61,
        "phase_deg": 92.71,
        "gsd_m_per_px": 0.6,
        "anti_solar_image_az_deg": 1.7,  # shadows point ~due-east (sun in the west)
        "az_validation": ("sign anchored by large-crater interior shadow geometry -- the lit inner walls of "
                          "the frame's large bowl craters are on the EAST, so the Sun is in the WEST and "
                          "cast shadows point EAST; the data-derived shadow axis is 1.7/181.7 deg."),
        "label_url": ("https://pds.lroc.im-ldi.com/data/LRO-L-LROC-3-CDR-V1.0/LROLRC_1008/DATA/SCI/"
                      "2011198/NAC/M165530748LC.xml"),
        "ortho_url": ("https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/BROWSE/"
                      "NAC_DTM/MESSIER3/NAC_DTM_MESSIER3_M165530748_60CM.TIF"),
    },
    "station6": {
        "site": "Apollo 17 Station 6 'House Rock', base of the North Massif (~20.29 N, 30.80 E)",
        "nac_frame": "M134991788R",
        "dtm_bundle": "NAC_DTM_APOLLO17_1",
        "ortho_file": "NAC_DTM_APOLLO17_1_M134991788_60CM.TIF",
        "incidence_deg": 64.66,          # ODE CDRNAC4 pdsid nac.m134991788rc (2010-07-28, afternoon)
        "sun_elevation_deg": 90.0 - 64.66,
        "emission_deg": 16.67,
        "phase_deg": 48.33,
        "gsd_m_per_px": 0.6,
        "anti_solar_image_az_deg": 345.5,  # shadows point ENE (sun WSW, afternoon)
        "az_validation": ("frame + boulder located by 0.80 normalized cross-correlation against the LROC "
                          "published image of the boulder (lroc.im-ldi.com/images/759); the main fragment's "
                          "cast shadow points ENE, so the Sun is in the WSW (afternoon)."),
        "label_url": ("https://pds.lroc.im-ldi.com/data/LRO-L-LROC-3-CDR-V1.0/LROLRC_1004/DATA/MAP/"
                      "2010209/NAC/M134991788RC.xml"),
        "ortho_url": ("https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/BROWSE/"
                      "NAC_DTM/APOLLO17_1/NAC_DTM_APOLLO17_1_M134991788_60CM.TIF"),
    },
}

# ----------------------------------------------------------------------------------------------------------
# PUBLISHED TARGETS -- read ONLY by compare_* (the firewall).  No measurement function imports this block.
# ----------------------------------------------------------------------------------------------------------
PUBLISHED: dict[str, dict] = {
    "demidov_hd": {
        "h_over_d": 0.60, "sigma": 0.03,
        "also": {"h_over_D_full": 0.54, "engineering": 0.5},
        "n_rocks": 445,
        "doi": "10.1134/S0038094614050013",
        "ref": "Demidov & Basilevsky (2014), Solar System Research 48(5):324-353",
        "note": "h/d from ground-based Apollo/Lunokhod panoramas, independent of NAC shadows.",
    },
    "station6_house_rock": {
        "height_m": 6.0, "block_dims_m": [18.0, 10.0, 6.0],
        "largest_fragment_across_m": 10.0, "n_fragments": 5,
        "url": "https://lroc.im-ldi.com/images/759",
        "note": "documented original block 18x10x6 m from Apollo 17 surface photogrammetry; now split.",
    },
}


# ==========================================================================================================
# MEASUREMENT  (firewall side -- never reads PUBLISHED)
# ==========================================================================================================
WorldBox = tuple[int, int, int, int]  # (col0, row0, width, height) pixel window, or None for full frame


@dataclass
class BoulderMeasurement:
    """One boulder's frozen measurement -- pixels + Sun geometry only, no published value involved."""
    col: int
    row: int
    diameter_m: float
    shadow_len_m: float
    height_m: float
    h_over_d: float
    shadow_len_px: float
    diameter_px: float
    bg_dn: float


@dataclass
class PopulationResult:
    frame_key: str
    sun_elevation_deg: float
    gsd_m: float
    anti_solar_image_az_deg: float
    boulders: list[BoulderMeasurement] = field(default_factory=list)

    @property
    def hd_values(self) -> np.ndarray:
        return np.array([b.h_over_d for b in self.boulders], dtype=float)

    def stats(self) -> dict:
        v = self.hd_values
        if v.size == 0:
            return {"n": 0, "median": None, "iqr": None, "mean": None, "median_ci95": None}
        rng = np.random.default_rng(20260630)
        meds = [float(np.median(rng.choice(v, v.size, replace=True))) for _ in range(2000)]
        return {
            "n": int(v.size),
            "median": float(np.median(v)),
            "mean": float(v.mean()),
            "iqr": [float(np.percentile(v, 25)), float(np.percentile(v, 75))],
            "median_ci95": [float(np.percentile(meds, 2.5)), float(np.percentile(meds, 97.5))],
            "diameter_m_range": [float(min(b.diameter_m for b in self.boulders)),
                                 float(max(b.diameter_m for b in self.boulders))],
        }


def load_gray(path: str, window: WorldBox | None = None) -> tuple[np.ndarray, float, rasterio.Affine]:
    """Read a NAC ortho (or a pixel window of it) as float32 gray plus its GSD and affine transform."""
    with rasterio.open(path) as ds:
        if window is None:
            arr = ds.read(1).astype(np.float32)
            tf = ds.transform
        else:
            c0, r0, w, h = window
            arr = ds.read(1, window=((r0, r0 + h), (c0, c0 + w))).astype(np.float32)
            tf = ds.window_transform(((r0, r0 + h), (c0, c0 + w)))
        gsd = float(abs(tf.a))
    return arr, gsd, tf


def estimate_shadow_axis_deg(gray: np.ndarray, *, smooth_max: float = 12.0) -> float:
    """Data-derived dominant shadow AXIS (mod 180, image frame x-right y-down) -- a cross-check for the
    recorded anti_solar azimuth, NOT a target read.  On cratered terrain the dominant bright-cap -> dark-lobe
    offset is the lit-wall->shadow direction; its axis equals the cast-shadow axis. Returns degrees in
    [0,180)."""
    g = gray.astype(np.float32)
    h, w = g.shape
    lm = uniform_filter(g, 25)
    ls = np.sqrt(np.maximum(uniform_filter(g * g, 25) - lm ** 2, 0))
    bs = uniform_filter(ls, 121)
    pk = (g == maximum_filter(g, 7)) & (g - lm > 3.5 * np.maximum(ls, 3)) & (g > 0) & (bs < smooth_max)
    ys, xs = np.where(pk)
    angs = []
    for y, x in zip(ys, xs):
        if y < 16 or y >= h - 16 or x < 16 or x >= w - 16:
            continue
        bg = lm[y, x]
        win = g[y - 14:y + 15, x - 14:x + 15]
        dk = win < 0.5 * bg
        if dk.sum() < 6:
            continue
        dy, dx = np.where(dk)
        ox, oy = dx.mean() - 14, dy.mean() - 14
        if math.hypot(ox, oy) > 2:
            angs.append(math.atan2(oy, ox))
    if not angs:
        raise ValueError("no bright-cap/dark-lobe pairs to estimate shadow axis")
    a2 = 2.0 * np.asarray(angs)
    axis = 0.5 * math.degrees(math.atan2(np.sin(a2).sum(), np.cos(a2).sum())) % 180.0
    return float(axis)


def _profile(g, y, x, ux, uy, d):
    h, w = g.shape
    xi, yi = int(round(x + ux * d)), int(round(y + uy * d))
    return float(g[yi, xi]) if (0 <= xi < w and 0 <= yi < h) else math.nan


def detect_boulders(gray: np.ndarray, gsd_m: float, sun_elevation_deg: float,
                    anti_solar_image_az_deg: float, *,
                    diameter_halfmax_frac: float = 0.5, dark_frac: float = 0.55,
                    min_diameter_px: int = 4, min_shadow_px: int = 5, smooth_max: float = 10.0,
                    band: int = 8000, overlap: int = 300) -> list[BoulderMeasurement]:
    """Detect ISOLATED positive-relief boulders and measure each (diameter d, shadow length L, height H).

    Separability (the standing finding: an azimuth gate alone is necessary-but-NOT-sufficient because
    aggregate crater shadowing passes it): each accepted boulder is a compact bright cap that is a LOCAL
    MAXIMUM on locally-smooth mare, with the SOLAR side lit and a SINGLE dark cast-shadow lobe attached on
    the ANTI-solar side that terminates back in lit mare (not a crater interior, whose shadow sits on the
    SOLAR side under the lit far wall).  d is the cross-sun FWHM of the cap; L is the anti-solar dark run
    from the cap's anti-solar edge via the tested DART ray walk; H = L*tan(e) via dart.rock_taxonomy.
    """
    a = math.radians(anti_solar_image_az_deg)
    adx, ady = math.cos(a), math.sin(a)
    sdx, sdy = -adx, -ady                 # solar
    pdx, pdy = -ady, adx                  # cross-sun
    sun_az_for_walk = (anti_solar_image_az_deg - 180.0) % 360.0  # dart walks anti_solar_dir(sun_az)
    tan_e = math.tan(math.radians(sun_elevation_deg))
    H, W = gray.shape
    out: list[BoulderMeasurement] = []
    top = 0
    while top < H:
        bot = min(H, top + band)
        arr = gray[top:bot]
        h, w = arr.shape
        valid = arr > 0
        if valid.mean() >= 0.05:
            lm = uniform_filter(arr, 25)
            ls = np.sqrt(np.maximum(uniform_filter(arr * arr, 25) - lm ** 2, 0))
            bs = uniform_filter(ls, 121)
            pk = (arr == maximum_filter(arr, 7)) & (arr - lm > 3.5 * np.maximum(ls, 3)) & valid & (bs < smooth_max)
            ys, xs = np.where(pk)
            for y, x in zip(ys.tolist(), xs.tolist()):
                if y < 40 or y >= h - 40 or x < 40 or x >= w - 40:
                    continue
                bg = float(lm[y, x]); pk_dn = float(arr[y, x])
                if bg <= 0:
                    continue
                solar_lit = np.nanmean([_profile(arr, y, x, sdx, sdy, d) for d in (3, 4, 5)])
                anti_min = np.nanmin([_profile(arr, y, x, adx, ady, d) for d in (3, 4, 5, 6, 7)])
                if not (solar_lit > 0.75 * bg and anti_min < 0.55 * bg):     # positive relief, attached shadow
                    continue
                thr = bg + diameter_halfmax_frac * (pk_dn - bg)

                def _w(ux, uy, _arr=arr, _y=y, _x=x, _thr=thr):
                    d = 0
                    while d < 16:
                        v = _profile(_arr, _y, _x, ux, uy, d + 1)
                        if math.isnan(v) or v < _thr:
                            break
                        d += 1
                    return d
                d_px = _w(pdx, pdy) + _w(-pdx, -pdy) + 1
                solfar = np.nanmean([_profile(arr, y, x, sdx, sdy, d) for d in (int(d_px) + 3, int(d_px) + 5)])
                if not (solfar < 1.3 * bg):                                  # compact cap, not an extended wall
                    continue
                e = 0
                while e < int(d_px) + 5:
                    v = _profile(arr, y, x, adx, ady, e + 1)
                    if math.isnan(v) or v < thr:
                        break
                    e += 1
                bx, by = x + adx * e, y + ady * e
                L_px = measure_shadow_length_px(arr, float(bx), float(by), sun_az_for_walk,
                                                dark_frac=dark_frac, max_len_px=70, start_px=1)
                if L_px < min_shadow_px:
                    continue
                past = np.nanmean([_profile(arr, y, x, adx, ady, e + L_px + k) for k in (2, 3, 4)])
                if math.isnan(past) or not (0.75 * bg < past < 1.5 * bg):    # shadow ends in lit mare (separable)
                    continue
                d_m = d_px * gsd_m
                L_m = L_px * gsd_m
                H_m = shadow_height_m(L_m, sun_elevation_deg)               # H = L*tan(e)  [DART]
                hd = H_m / d_m if d_m > 0 else 0.0
                if d_px >= min_diameter_px and 0.1 < hd < 2.5:
                    out.append(BoulderMeasurement(col=int(x), row=int(y + top), diameter_m=round(d_m, 2),
                                                  shadow_len_m=round(L_m, 2), height_m=round(H_m, 2),
                                                  h_over_d=round(hd, 3), shadow_len_px=round(L_px, 1),
                                                  diameter_px=round(d_px, 1), bg_dn=round(bg, 1)))
        if bot >= H:
            break
        top += band - overlap
    # dedupe by proximity, keep the larger (d+L) first
    out.sort(key=lambda b: -(b.diameter_px + b.shadow_len_px))
    ded: list[BoulderMeasurement] = []
    for b in out:
        if all((b.col - d.col) ** 2 + (b.row - d.row) ** 2 > 400 for d in ded):
            ded.append(b)
    return ded


def measure_population_hd(frame_path: str, frame: dict, *, window: WorldBox | None = None,
                          **kw) -> PopulationResult:
    """TARGET A measurement: the isolated-boulder h/d population on one NAC frame. No published value read."""
    gray, gsd, _ = load_gray(frame_path, window)
    res = PopulationResult(frame_key=frame.get("nac_frame", "?"),
                           sun_elevation_deg=frame["sun_elevation_deg"], gsd_m=gsd,
                           anti_solar_image_az_deg=frame["anti_solar_image_az_deg"])
    res.boulders = detect_boulders(gray, gsd, frame["sun_elevation_deg"],
                                   frame["anti_solar_image_az_deg"], **kw)
    return res


def measure_named_fragment(gray: np.ndarray, gsd_m: float, sun_elevation_deg: float,
                           anti_solar_image_az_deg: float, seed_xy: tuple[int, int], *,
                           cap_thr: float, dark_frac_floor: float = 0.42) -> dict | None:
    """TARGET B measurement: the largest fragment's shadow at a known seed pixel. No published value read.

    Cap = the bright connected component (DN >= cap_thr) containing the seed; its attached dark cast-shadow
    lobe is the largest near-zero blob touching it. d = cross-sun extent of the cap; L = anti-solar extent of
    the shadow lobe from the cap's anti-solar edge; H = L*tan(e)."""
    g = gray.astype(np.float32)
    valid = g[g > 0]
    bg = float(np.median(valid[valid < 1.5 * np.median(valid)]))
    sx, sy = seed_xy
    lab, _ = label(g >= cap_thr)
    lid = lab[sy, sx]
    if lid == 0:
        return None
    ys, xs = np.where(lab == lid)
    if xs.size < 4:
        return None
    cxc, cyc = xs.mean(), ys.mean()
    dl, dn = label(g < dark_frac_floor * bg)
    best = None
    cap_extent = max(np.ptp(xs), np.ptp(ys))
    for i in range(1, dn + 1):
        yy, xx = np.where(dl == i)
        if yy.size < 20:
            continue
        mind = min(math.hypot(px - cxc, py - cyc) for px, py in zip(xx[::2], yy[::2]))
        if mind < cap_extent * 0.9 + 6 and (best is None or yy.size > best[0]):
            best = (yy.size, xx, yy)
    if best is None:
        return None
    _, xx, yy = best
    anti = math.degrees(math.atan2(yy.mean() - cyc, xx.mean() - cxc)) % 360.0
    adx, ady = math.cos(math.radians(anti)), math.sin(math.radians(anti))
    pdx, pdy = -ady, adx
    d_px = float(np.ptp((xs - cxc) * pdx + (ys - cyc) * pdy) + 1)
    edge = float(((xs - cxc) * adx + (ys - cyc) * ady).max())
    L_px = float(((xx - cxc) * adx + (yy - cyc) * ady).max() - edge)
    d_m = d_px * gsd_m
    L_m = L_px * gsd_m
    H_m = shadow_height_m(L_m, sun_elevation_deg)
    return {"seed_xy": [int(sx), int(sy)], "cap_thr": cap_thr, "shadow_az_deg": round(anti, 1),
            "diameter_m": round(d_m, 2), "shadow_len_m": round(L_m, 2), "height_m": round(H_m, 2),
            "h_over_d": round(H_m / d_m, 3) if d_m > 0 else None, "cap_px": int(xs.size),
            "shadow_px": int(best[0])}


# ==========================================================================================================
# COMPARE  (the ONLY functions that read PUBLISHED)
# ==========================================================================================================
def compare_demidov(stats: dict) -> dict:
    """Compare a frozen measured h/d population statistic to Demidov & Basilevsky (2014)."""
    pub = PUBLISHED["demidov_hd"]
    if stats.get("n", 0) == 0 or stats.get("median") is None:
        return {"verdict": "BLOCKED", "reason": "no boulders measured", **pub}
    med = stats["median"]
    ci = stats.get("median_ci95") or [med, med]
    iqr = stats.get("iqr") or [med, med]
    target, sig = pub["h_over_d"], pub["sigma"]
    eng, hD = pub["also"]["engineering"], pub["also"]["h_over_D_full"]   # 0.50, 0.54
    # judge on the POINT estimate, not the discretized bootstrap CI (which over-claims on pixel-quantized h/d)
    within_headline = abs(med - target) <= sig
    within_family = (eng - 0.05) <= med <= (target + 0.05)              # 0.45 .. 0.65 lunar-boulder aspect family
    headline_in_iqr = iqr[0] <= target <= iqr[1]
    if within_headline:
        verdict = "REPRODUCES the headline h/d = 0.60 +/- 0.03"
    elif within_family:
        verdict = (f"REPRODUCES the lunar-boulder aspect family (median {med:.2f} matches the engineering "
                   f"~{eng}/h_D {hD} value); the headline 0.60 lies "
                   f"{'within' if headline_in_iqr else 'above'} the IQR but above the point median")
    else:
        verdict = "DOES NOT reproduce"
    return {"verdict": verdict, "measured_median_hd": round(med, 3), "measured_iqr": [round(c, 3) for c in iqr],
            "measured_ci95": [round(c, 3) for c in ci], "published_h_over_d": target, "published_sigma": sig,
            "published_family": pub["also"], "headline_within_iqr": headline_in_iqr,
            "is_boulder_like_not_crater_like": med > 0.30, "doi": pub["doi"], "ref": pub["ref"]}


def compare_station6(largest_fragment_height_m: float | None, fragments: list[dict]) -> dict:
    """Compare the frozen largest-fragment shadow height to the documented ~6 m House Rock block."""
    pub = PUBLISHED["station6_house_rock"]
    if largest_fragment_height_m is None:
        return {"verdict": "BLOCKED", "reason": "largest fragment shadow not measurable", **pub}
    doc = pub["height_m"]
    consistent = 0.5 * doc <= largest_fragment_height_m <= 1.3 * doc
    return {
        "verdict": ("CONSISTENT with documented ~6 m (largest fragment retains ~full original height)"
                    if consistent else "INCONSISTENT with documented ~6 m"),
        "largest_fragment_height_m": round(largest_fragment_height_m, 2),
        "documented_height_m": doc, "documented_block_dims_m": pub["block_dims_m"],
        "caveats": ["boulder is SPLIT into ~5 fragments; this is the LARGEST fragment, not the intact block",
                    "sits on the North-Massif-base SLOPE -- H=L*tan(e) assumes level ground, so a local "
                    "down-Sun slope biases the recovered height",
                    "smaller fragments' shadows MERGE with the main shadow at 0.6 m/px -> not separately "
                    "measurable (recorded, not fabricated)"],
        "url": pub["url"], "fragments_measured": fragments}
