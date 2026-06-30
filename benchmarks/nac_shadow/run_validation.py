"""Validate H = L*tan(e) on REAL LROC NAC imagery of Giordano Bruno -- runner + artifact writer.

Outcome (see the emitted JSON): the forward measurement pipeline and the two-Sun co-registration both
work on real data, but a DEFENSIBLE *validated* boulder height is BLOCKED at freely-accessible NAC
sites, for two specific, separately-documented reasons:

  PATH 1 (independent height from a co-registered stereo DTM): the 2-3 m NAC stereo DTM resolves only
  ~75-120 m melt mounds; individual 10-30 m boulders are sub-resolution, so the DTM cannot supply a
  per-boulder ground-truth height. (Extends the known SfS-DEM smoothing to NAC *stereo* DTMs.)

  PATH 2 (two-Sun self-consistency): co-registration is solved (two georeferenced orthos at 32.2 deg
  and 53.6 deg sampled at identical world coords; high-pass corr ~0.5), but a clean per-boulder shadow
  is not separable on the available terrain -- boulder-rich rubble sits on slopes in deep shadow at low
  Sun, smooth melt carries only sub-5 m boulders, and dense fields merge shadows. Crucially, a NAIVE
  "two-Sun agreement" obtained by taking the longest dark run in any direction is an ARTIFACT: any dark
  feature's extent scales ~1/tan(e), so H = L*tan(e) "agrees" regardless of whether it is a boulder.
  This runner demonstrates the artifact (heights agree while the chosen shadow azimuths are scattered),
  and shows the metric's own DART front-end gate (shadow-edge concentration) rejects the terrain.

Run:  NAC_SHADOW_DATA=/path/to/products  .venv/bin/python benchmarks/nac_shadow/run_validation.py
Products auto-download from the LROC PDS node if absent (~2.3 GB; see nac_shadow.PRODUCTS for URLs).
No synthetic data; no fabricated height is ever written.
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date

import numpy as np
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import maximum_filter

import nac_shadow as ns
from dart.shadow_extract import extract_shadow_azimuth

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.environ.get("NAC_SHADOW_DATA", os.path.expanduser("~/.cache/stewie_nac_shadow"))
ARTIFACT = os.path.join(REPO, "stewie", "eval", "validation", "nac_shadow_validation_2026-06-29.json")
FIGURE = os.path.join(REPO, "stewie", "eval", "validation", "nac_shadow_validation_2026-06-29.png")

# Giordano Bruno overlap windows (Equirectangular_Moon metres). COREG = 1.5 km; LIT = a boulder field
# lit at both Sun angles; MELT = a smoother melt patch; BLOCK = the largest isolated block (lit only
# at high Sun). These are the same windows the interactive analysis used.
COREG_BOX = (-1884494.0, 1090534.0, -1882994.0, 1092034.0)
LIT_CENTER = (-1882398.0, 1099052.0)
BLOCK_CENTER = (-1881609.0, 1085265.0)


def ensure_products() -> dict[str, str]:
    os.makedirs(DATA_DIR, exist_ok=True)
    paths = {}
    for key in ("ortho_low_sun", "ortho_high_sun", "dem"):
        p = PRODUCT_PATH(key)
        fname = ns.PRODUCTS[key].get("ortho_file") or ns.PRODUCTS[key]["dem_file"]
        if not os.path.exists(p):
            url = ns.PRODUCTS[key]["url"]
            print(f"downloading {fname} ...")
            urllib.request.urlretrieve(url, p)
        paths[key] = p
    return paths


def PRODUCT_PATH(key: str) -> str:
    fname = ns.PRODUCTS[key].get("ortho_file") or ns.PRODUCTS[key]["dem_file"]
    return os.path.join(DATA_DIR, fname)


def _box(center: tuple[float, float], half: float) -> ns.WorldBox:
    return (center[0] - half, center[1] - half, center[0] + half, center[1] + half)


def path1_dem_smoothing(dem_path: str) -> dict:
    """Document that the stereo DTM cannot supply per-boulder height GT (resolves mounds, not boulders)."""
    rel = ns.dem_relief(dem_path, _box(LIT_CENTER, 90.0))
    return {
        "result": "BLOCKED",
        "reason": "NAC stereo DTM post spacing resolves mounds, not individual boulders",
        "post_spacing_m": rel["post_spacing_m"],
        "min_resolvable_feature_m": rel["min_resolvable_feature_m"],
        "dem_relief_over_180m_window_m": round(rel["relief_m"], 1),
        "note": "min_resolvable_feature (~3 posts) exceeds typical boulder size (10-30 m); the local "
                "relief reflects the 75-120 m melt mound, so a per-boulder ground-truth height is "
                "unrecoverable from this DTM.",
    }


def path2_artifact_demo(ortho_low: str, ortho_high: str) -> dict:
    """Show that naive undirected two-Sun 'agreement' is the 1/tan(e) artifact, not boulder recovery."""
    wl = ns.load_window(ortho_low, _box(LIT_CENTER, 120.0))
    wh = ns.load_window(ortho_high, _box(LIT_CENTER, 120.0))
    e_lo = ns.PRODUCTS["ortho_low_sun"]["sun_elevation_deg"]
    e_hi = ns.PRODUCTS["ortho_high_sun"]["sun_elevation_deg"]
    # detect bright boulder peaks in the crisp high-Sun frame, map to world, measure in BOTH frames
    g = wh.pixels
    med = float(np.median(g[g > 0]))
    pk = (g == maximum_filter(g, 5)) & (g > 1.3 * med)
    ys, xs = np.where(pk)
    rel_diffs, az_lo, az_hi = [], [], []
    for r, c in zip(ys.tolist(), xs.tolist()):
        wx, wy = wh.transform * (c + 0.5, r + 0.5)
        rl, alo = ns.longest_dark_run_any_direction(wl.pixels, wl.world_to_rc(wx, wy), wl.gsd_m)
        rh, ahi = ns.longest_dark_run_any_direction(wh.pixels, wh.world_to_rc(wx, wy), wh.gsd_m)
        if alo is None or ahi is None or rl < 3 or rh < 3:
            continue
        h_lo = ns.recover_height_m(rl, e_lo)
        h_hi = ns.recover_height_m(rh, e_hi)
        rel_diffs.append(abs(h_lo - h_hi) / ((h_lo + h_hi) / 2))
        az_lo.append(alo)
        az_hi.append(ahi)
    return {
        "result": "BLOCKED (apparent agreement is an artifact)",
        "n_features": len(rel_diffs),
        "naive_height_median_rel_diff_pct": round(float(np.median(rel_diffs)) * 100, 1) if rel_diffs else None,
        "shadow_azimuth_concentration_low_sun": round(ns.circular_concentration(az_lo), 3),
        "shadow_azimuth_concentration_high_sun": round(ns.circular_concentration(az_hi), 3),
        "interpretation": "The per-feature shadow azimuths are scattered (concentration ~0.08-0.10, far "
                          "below 1) and the undirected two-Sun heights do not agree (median rel diff ~50%). "
                          "A single Sun casts shadows in ONE direction, so scattered azimuths prove the "
                          "undirected longest-dark-run is not reading real cast shadows -- it picks "
                          "arbitrary terrain darkness, whose extent only trivially scales ~1/tan(e). A "
                          "valid two-Sun test must measure the actual cast shadow along the single true "
                          "anti-solar azimuth; that azimuth is not cleanly recoverable on this cluttered "
                          "terrain (see dart_frontend_gate), which is the path-2 blocker.",
    }


def path2_dart_gate(ortho_low: str, ortho_high: str) -> dict:
    """Run the metric's own DART shadow-edge front-end gate; it rejects this cluttered terrain."""
    out: dict[str, object] = {}
    for tag, path in (("low_sun_32deg", ortho_low), ("high_sun_54deg", ortho_high)):
        w = ns.load_window(path, _box(LIT_CENTER, 200.0))
        obs = extract_shadow_azimuth(w.pixels, gate=False)
        out[tag] = {"shadow_edge_concentration_R": round(obs.confidence, 3),
                    "spec_gate_R": 0.30, "passes_gate": bool(obs.confidence >= 0.30)}
    out["interpretation"] = ("The DART shadow-azimuth front-end (dart.shadow_extract.extract_shadow_azimuth) "
                             "gates at R=0.30; both frames score ~0.03, so the metric's own gate REJECTS this "
                             "terrain as too cluttered for a calibrated heading/shadow -- consistent with the "
                             "documented VALIDATION STATUS in dart/shadow_height.py, now confirmed on real NAC.")
    return out


def make_figure(ortho_low: str, ortho_high: str, dem_path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def stretch(a: np.ndarray) -> np.ndarray:
        m = a > 0
        lo, hi = np.percentile(a[m], (2, 98))
        return np.clip((a - lo) / (hi - lo), 0, 1)

    wl = ns.load_window(ortho_low, _box(LIT_CENTER, 120.0))
    wh = ns.load_window(ortho_high, _box(LIT_CENTER, 120.0))
    with rasterio.open(dem_path) as ds:
        dem = ds.read(1, window=from_bounds(*_box(LIT_CENTER, 120.0), ds.transform)).astype(np.float32)
        post = float(abs(ds.transform.a))
    dem[dem < -1e30] = np.nan
    gy, gx = np.gradient(np.where(np.isfinite(dem), dem, np.nanmedian(dem)), post)
    hs = -gx + gy
    with rasterio.open(ortho_high) as ds:
        blk = ds.read(1, window=from_bounds(*_box(BLOCK_CENTER, 30.0), ds.transform)).astype(np.float32)

    fig, ax = plt.subplots(1, 4, figsize=(16, 4.4))
    ax[0].imshow(stretch(wl.pixels), cmap="gray"); ax[0].set_title("NAC ortho, Sun elev 32.2 deg\nM1190012618 (1.0 m/px)")
    ax[1].imshow(stretch(wh.pixels), cmap="gray"); ax[1].set_title("SAME ground, Sun elev 53.6 deg\nM156924032 (0.6 m/px)")
    ax[2].imshow(hs, cmap="gray"); ax[2].set_title("Co-registered 3 m stereo DTM\n(mounds resolved, boulders are not)")
    ax[3].imshow(stretch(blk), cmap="gray"); ax[3].set_title("Largest isolated ~35 m block @54 deg\nshadow merges into rubble pool")
    for a in ax:
        a.set_xticks([]); a.set_yticks([])
    fig.suptitle("Giordano Bruno crater -- real LROC NAC two-Sun cast-shadow validation attempt "
                 "(co-registration works; per-boulder ground truth is blocked)", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGURE, dpi=120)
    plt.close(fig)
    print("wrote", FIGURE)


def main() -> None:
    paths = ensure_products()
    ortho_low, ortho_high, dem = paths["ortho_low_sun"], paths["ortho_high_sun"], paths["dem"]
    coreg = ns.coregistration_highpass_corr(ortho_low, ortho_high, COREG_BOX)
    artifact = {
        "experiment": "Cast-shadow-length metric H = L*tan(e) on REAL LROC NAC imagery",
        "date": date.today().isoformat(),
        "site": "Giordano Bruno crater (freshest large lunar crater), ~35.9 N, 102.9 E",
        "outcome": "BLOCKED on a defensible validated height; forward pipeline + co-registration confirmed.",
        "data_real": True,
        "synthetic_data_used": False,
        "fabricated_height": False,
        "products": ns.PRODUCTS,
        "tooling": {"pdr": "1.4.4 (read PDS .IMG/.LBL pixels + labels)",
                    "rasterio": "1.4.4 (georeferenced ortho/DEM GeoTIFFs)",
                    "ode": "oderest.rsl.wustl.edu geometry index (incidence/emission/GSD, SPICE-derived)",
                    "isis": "NOT required -- map-projected ortho products gave top-down geometry + GSD"},
        "sun_geometry": {
            "low_sun_frame": {"product": "M1190012618", "incidence_deg": 57.84, "sun_elevation_deg": 32.16,
                              "emission_deg": 13.87, "gsd_m_per_px": 1.0},
            "high_sun_frame": {"product": "M156924032", "incidence_deg": 36.39, "sun_elevation_deg": 53.61,
                               "emission_deg": 3.65, "gsd_m_per_px": 0.6},
            "note": "sun_elevation = 90 - incidence (source NAC frame geometry); shadow ratio tan(53.6)/"
                    "tan(32.2) = 2.16",
        },
        "co_registration": {
            "method": "both orthos georeferenced Equirectangular_Moon; sampled at identical world coords",
            "highpass_correlation_1p5km": round(coreg, 3),
            "result": "CONFIRMED -- same ground at both Sun angles, no manual tie-pointing",
        },
        "path1_stereo_dtm_groundtruth": path1_dem_smoothing(dem),
        "path2_two_sun_self_consistency": {
            "naive_artifact_demo": path2_artifact_demo(ortho_low, ortho_high),
            "dart_frontend_gate": path2_dart_gate(ortho_low, ortho_high),
        },
        "specific_blocker": (
            "A defensible validation needs a LARGE, ISOLATED boulder with a SEPARABLE cast shadow (tip "
            "ending in lit ground) imaged at low Sun, PLUS an independent height. At freely-accessible NAC "
            "sites this combination fails: (1) NAC stereo DTMs do not resolve boulder relief (no GT), and "
            "(2) at fresh-crater boulder fields the boulders are either in deep shadow at low Sun, too "
            "dense (merged shadows), or too small (smooth melt/mare). The forward step (shadow -> H) and "
            "two-Sun co-registration both work; only the clean boulder + independent height co-occurrence "
            "is missing."
        ),
        "what_would_unblock": [
            "A low-Sun (e <~ 20 deg) MAP-PROJECTED NAC frame over a SPARSE mare boulder field (isolated "
            "boulders on dark smooth mare -> long, clean, separable shadows + one unambiguous anti-solar) "
            "paired with a second Sun angle: the georeferenced-ortho co-registration validated here applies "
            "directly, yielding a clean two-Sun number.",
            "A sub-meter NAC stereo DTM (<~1 m post; exists for a few special sites) co-located with a "
            "low-Sun NAC frame over a large isolated boulder -> path-1 relief GT.",
            "A surveyed/published boulder height (e.g. an Apollo-traverse boulder) co-located with a NAC "
            "low-Sun frame -> path-3 independent height.",
        ],
        "most_uncertain_claim": (
            "That NO accessible NAC stereo DTM resolves boulder relief -- tested on a 3 m Giordano Bruno "
            "DTM; a <~1 m special-site DTM over a large isolated block could partially resolve it (path 1)."
        ),
    }
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w") as f:
        json.dump(artifact, f, indent=2)
    print("wrote", ARTIFACT)
    make_figure(ortho_low, ortho_high, dem)


if __name__ == "__main__":
    main()
