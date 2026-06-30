"""Validate H = L*tan(e) by TWO-SUN self-consistency on REAL LROC NAC over SPARSE MARE -- runner.

Outcome (see the emitted JSON): BLOCKED, but it sharpens and extends the prior Giordano-Bruno blocker.
We test the one untested promising regime -- sparse mare two-Sun NAC -- on three real sites and find:

  * MESSIER (Mare Fecunditatis fresh-crater ejecta; two-Sun e45/e21, shadow-length ratio 2.5x,
    co-registration high-pass corr ~0.77): isolated-boulder tight crops max R ~0.26 (low Sun) / ~0.31
    (high Sun) -- only ONE high-Sun crop reaches 0.30 and its shadow is NOT separately measurable in
    both frames. The DTM footprint is cluttered ejecta, so per-boulder shadow-edge azimuths do not
    concentrate -- the Giordano-Bruno failure mode, now on mare.

  * REINER GAMMA (smooth-mare swirl; two-Sun e15/e47, shadow-length ratio 3.5x): the high-Sun frame's
    tight crops DO clear the gate (boulder-crop max R ~0.75, 37 >= 0.30; window-scan max R ~0.98) -- but
    this is AGGREGATE directional shadowing of a densely small-cratered surface, NOT an isolated boulder.
    All gate-passing candidates measured yield directed shadow L ~ 0 in >= 1 frame (sub-resolution bright
    spots); the low-Sun member is shadow-saturated (boulder-crop max R ~0.20, 0 >= 0.30). So R >= 0.30 is
    NECESSARY but NOT SUFFICIENT -- it does not guarantee a separable, two-Sun-consistent boulder shadow.

  * A12 (Apollo 12 ascent-impact site, sparse mare; POSITIVE CONTROL, single epoch -> no usable second
    Sun): isolated-boulder tight crops clear the gate (max R ~0.40, 17 >= 0.30; window-scan max ~0.95).
    This proves the metric's gate CAN admit sparse-mare features -- but the only two-Sun coverage
    (overlapping NAC stereo DTMs) is sited over rough features, where the resolvable shadows are crater
    interiors (which do not obey H = L*tan(e)) or sub-resolution. No fabricated height is ever written.

Run:  NAC_TWOSUN_DATA=/path/to/orthos  .venv/bin/python benchmarks/nac_shadow/run_twosun_validation.py
Orthos auto-download from the LROC PDS node if absent (~2 GB; URLs in nac_twosun.PRODUCTS_TWOSUN).
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date

import numpy as np
import rasterio

import nac_twosun as nt

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.environ.get("NAC_TWOSUN_DATA", os.path.expanduser("~/.cache/stewie_nac_twosun"))
ARTIFACT = os.path.join(REPO, "stewie", "eval", "validation", "nac_shadow_twosun_2026-06-30.json")
FIGURE = os.path.join(REPO, "stewie", "eval", "validation", "nac_shadow_twosun_2026-06-30.png")

# Per-site overlap box (world metres, each site's Equirectangular_Moon CRS) for the co-registration check.
COREG_BOX = {
    "messier": (-4011000.0, -60000.0, -4007000.0, -56000.0),
    "reiner": (3636000.0, 210000.0, 3644000.0, 235000.0),
}


def _path(spec: dict) -> str:
    return os.path.join(DATA_DIR, spec["file"])


def ensure_products() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    for site in nt.PRODUCTS_TWOSUN.values():
        for key in ("low_sun", "high_sun"):
            spec = site.get(key)
            if not spec:
                continue
            p = _path(spec)
            if not os.path.exists(p):
                print(f"downloading {spec['file']} ...", flush=True)
                urllib.request.urlretrieve(spec["url"], p)


def _summ(rs: list[float]) -> dict:
    a = np.asarray(rs, float)
    if a.size == 0:
        return {"n": 0}
    return {"n": int(a.size), "R_max": round(float(a.max()), 3),
            "R_p99": round(float(np.percentile(a, 99)), 3),
            "R_median": round(float(np.median(a)), 3),
            "n_pass_gate_0p30": int((a >= nt.GATE_R).sum())}


def assess_site(name: str, site: dict) -> dict:
    low, high = site.get("low_sun"), site["high_sun"]
    rec: dict[str, object] = {"site": site["site"], "terrain": site["terrain"],
                              "frames": {k: site[k]["frame"] for k in ("low_sun", "high_sun") if k in site},
                              "sun_elevations_deg": {k: site[k]["sun_elevation_deg"]
                                                     for k in ("low_sun", "high_sun") if k in site}}
    if low is not None:
        rec["shadow_length_ratio_lo_over_hi"] = round(
            np.tan(np.radians(high["sun_elevation_deg"])) / np.tan(np.radians(low["sun_elevation_deg"])), 2)
        rec["co_registration_highpass_corr"] = round(nt.coreg_corr(_path(low), _path(high), COREG_BOX[name]), 3)
    # gate assessment on each available frame
    frames = {"high_sun": high} if low is None else {"low_sun": low, "high_sun": high}
    gate: dict[str, dict] = {}
    boulder_hits: dict[str, list[nt.GateHit]] = {}
    for tag, spec in frames.items():
        with rasterio.open(_path(spec)) as ds:
            arr = ds.read(1)
            tf = ds.transform
        win = nt.scan_gate_windows(arr, tf, win=256, step=240)
        bld = nt.detect_isolated_boulders(arr, tf, crop=80, smooth_max=9.0, max_eval=600)
        boulder_hits[tag] = bld
        gate[tag] = {
            "window_scan": _summ([h.confidence_R for h in win]),
            "isolated_boulder_crops": _summ([h.confidence_R for h in bld]),
        }
    rec["gate"] = gate
    # two-Sun measurement on the gate-passing isolated-boulder candidates (high-Sun frame admits)
    if low is not None:
        passers = [h for h in boulder_hits["high_sun"] if h.confidence_R >= nt.GATE_R]
        gate["high_sun"]["n_isolated_boulders_pass_gate"] = len(passers)
        measured = []
        with rasterio.open(_path(low)) as dlo, rasterio.open(_path(high)) as dhi:
            seen: list[tuple[float, float]] = []
            for h in passers:
                if any(abs(h.world_x - s[0]) < 60 and abs(h.world_y - s[1]) < 60 for s in seen):
                    continue
                seen.append((h.world_x, h.world_y))
                m = nt.measure_two_sun(dlo, low["sun_elevation_deg"], dhi, high["sun_elevation_deg"],
                                       (h.world_x, h.world_y))
                m["admit_gate_R_high_sun"] = round(h.confidence_R, 3)
                measured.append(m)
                if len(measured) >= 8:
                    break
        rec["two_sun_measurements"] = measured
        rec["n_two_sun_validated"] = sum(
            1 for m in measured if isinstance(m["two_sun"], dict) and m["two_sun"].get("both_measurable"))
    return rec


def make_figure(sites: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def stretch(a: np.ndarray) -> np.ndarray:
        m = a > 0
        if m.sum() < 5:
            return np.zeros_like(a, float)
        lo, hi = np.percentile(a[m], (2, 98))
        return np.clip((a - lo) / (hi - lo + 1e-6), 0, 1)

    def crop_world(path: str, wx: float, wy: float, half_m: float = 90.0) -> tuple[np.ndarray, float]:
        with rasterio.open(path) as ds:
            gsd = ds.transform.a
            hp = int(half_m / gsd)
            col, row = ~ds.transform * (wx, wy)
            win = rasterio.windows.Window(int(col) - hp, int(row) - hp, 2 * hp, 2 * hp)
            return ds.read(1, window=win).astype(np.float32), gsd

    fig, ax = plt.subplots(2, 3, figsize=(13.5, 9))
    # Row 0: Reiner two-Sun candidate that CLEARS the gate (high Sun) but is unmeasurable
    rs = sites["reiner"]
    cand = None
    for m in rs.get("two_sun_measurements", []):
        cand = m
        break
    rl, rh = nt.PRODUCTS_TWOSUN["reiner"]["low_sun"], nt.PRODUCTS_TWOSUN["reiner"]["high_sun"]
    if cand is not None:
        wx, wy = cand["world_xy"]
        for j, (spec, lab) in enumerate(((rh, "high"), (rl, "low"))):
            a, gsd = crop_world(_path(spec), wx, wy)
            mm = cand[("high_sun" if lab == "high" else "low_sun")]
            ax[0, j].imshow(stretch(a), cmap="gray")
            ax[0, j].plot(a.shape[1] // 2, a.shape[0] // 2, "c+", ms=12)
            ax[0, j].set_title(f"Reiner Gamma {lab} Sun e{spec['sun_elevation_deg']:.0f}\n"
                               f"gate R={mm['gate_R']}  L={mm['shadow_len_m']}m", fontsize=9)
            ax[0, j].axis("off")
    ax[0, 2].axis("off")
    ax[0, 2].text(0.0, 0.5, "Reiner: high-Sun crops CLEAR the gate\n(boulder-crop R up to ~0.75) but on\n"
                            "AGGREGATE small-crater shadowing --\nno isolated boulder; directed L ~ 0;\n"
                            "low-Sun frame is shadow-saturated.\nR>=0.30 is necessary, not sufficient.",
                  fontsize=10, va="center")
    # Row 1: A12 positive control isolated boulder that clears the gate, + Messier clutter
    a12 = nt.PRODUCTS_TWOSUN["a12_control"]["high_sun"]
    with rasterio.open(_path(a12)) as ds:
        arr = ds.read(1)
        tf = ds.transform
    bld = nt.detect_isolated_boulders(arr, tf, crop=80, smooth_max=9.0, max_eval=400)
    top = next((h for h in bld if h.confidence_R >= nt.GATE_R), bld[0] if bld else None)
    if top is not None:
        ca, gsd = crop_world(_path(a12), top.world_x, top.world_y)
        ax[1, 0].imshow(stretch(ca), cmap="gray")
        ax[1, 0].plot(ca.shape[1] // 2, ca.shape[0] // 2, "c+", ms=12)
        if np.isfinite(top.shadow_az_deg):
            dx, dy = np.cos(np.radians(top.shadow_az_deg)), np.sin(np.radians(top.shadow_az_deg))
            n = ca.shape[0] // 2
            ax[1, 0].plot([ca.shape[1] // 2, ca.shape[1] // 2 + dx * n * 0.6],
                          [ca.shape[0] // 2, ca.shape[0] // 2 + dy * n * 0.6], "r-", lw=1.5)
    ax[1, 0].set_title(f"A12 sparse-mare CONTROL e{a12['sun_elevation_deg']:.0f}\n"
                       f"isolated boulder gate R={top.confidence_R:.2f} (PASSES)" if top else "A12", fontsize=9)
    ax[1, 0].axis("off")
    ml = nt.PRODUCTS_TWOSUN["messier"]["low_sun"]
    mbld = sites["messier"]["gate"]["low_sun"]["isolated_boulder_crops"]
    with rasterio.open(_path(ml)) as ds:
        cy, cx = ds.height // 2, ds.width // 2
        cm = ds.read(1, window=rasterio.windows.Window(cx - 150, cy - 150, 300, 300)).astype(np.float32)
    ax[1, 1].imshow(stretch(cm), cmap="gray")
    ax[1, 1].set_title(f"Messier ejecta low Sun e{ml['sun_elevation_deg']:.0f}\n"
                       f"isolated-boulder R_max={mbld['R_max']} (< 0.30)", fontsize=9)
    ax[1, 1].axis("off")
    ax[1, 2].axis("off")
    ax[1, 2].text(0.0, 0.5, "A12 (sparse mare, single epoch):\nthe gate PASSES on isolated features\n"
                            "(boulder-crop R up to ~0.40) -- but no\nsecond Sun.\n\nMessier (two-Sun mare ejecta):\n"
                            "cluttered; isolated-boulder crops do\nnot clear (R_max ~0.31). Two-Sun cover\n"
                            "and clean isolated boulders do not\nco-occur on free NAC -> BLOCKED.",
                  fontsize=10, va="center")
    fig.suptitle("Two-Sun cast-shadow validation on REAL LROC NAC over SPARSE MARE -- BLOCKED "
                 "(gate vs isolated-boulder separability)", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIGURE, dpi=120)
    plt.close(fig)
    print("wrote", FIGURE)


def main() -> None:
    ensure_products()
    sites = {name: assess_site(name, spec) for name, spec in nt.PRODUCTS_TWOSUN.items()}
    n_validated = sum(int(s.get("n_two_sun_validated", 0)) for s in sites.values())
    artifact = {
        "experiment": "Two-Sun self-consistency of H = L*tan(e) on REAL LROC NAC over SPARSE MARE",
        "date": date.today().isoformat(),
        "outcome": "BLOCKED" if n_validated == 0 else "VALIDATED",
        "data_real": True,
        "synthetic_data_used": False,
        "fabricated_height": False,
        "n_two_sun_boulders_validated": n_validated,
        "tooling": {"pdr": "1.4.4", "rasterio": "1.4.4",
                    "ode": "oderest.rsl.wustl.edu CDRNAC4 geometry index (incidence -> sun elevation)",
                    "isis": "NOT required -- map-projected NAC stereo-DTM orthos give top-down geometry + GSD"},
        "gate_threshold_R": nt.GATE_R,
        "products": nt.PRODUCTS_TWOSUN,
        "sites": sites,
        "specific_blocker": (
            "No freely-available SPARSE-MARE two-Sun NAC pair yields a gate-admitted, separable, two-Sun-"
            "consistent ISOLATED-BOULDER shadow (n_two_sun_boulders_validated = 0; see per-site gate numbers). "
            "Two-Sun map-projected coverage exists only as overlapping NAC stereo-DTM ortho bundles, which are "
            "sited over ROUGH features. There the resolvable shadows are (a) buried in clutter so isolated-"
            "boulder crops do not clear the gate per boulder (Messier ejecta: boulder-crop R_max ~0.26 low / "
            "~0.31 high Sun; the lone high-Sun passer is NOT two-Sun-measurable), or (b) at the ~0.6-1.3 m "
            "ortho GSD the gate passes only on AGGREGATE small-crater directional shadowing (Reiner high Sun "
            "boulder-crop R_max ~0.75, 37 crops >= 0.30; window-scan R_max ~0.98) with NO single isolated "
            "boulder whose shadow is separately measurable -- all gate-passing candidates give directed L ~ 0 "
            "in >= 1 frame -- and the low-Sun member is shadow-saturated (boulder-crop R_max ~0.20, 0 >= 0.30). "
            "Where the gate cleanly admits isolated sparse-mare features (A12: boulder-crop R_max ~0.40, "
            "window-scan ~0.95) there is no usable second Sun (single-epoch DTM). The forward geometry "
            "(shadow -> H), the gate, and georeferenced two-Sun co-registration (Messier corr ~0.77) all work; "
            "what is missing is a LARGE ISOLATED boulder with a separable cast shadow CO-LOCATED with two-Sun "
            "coverage at sub-metre GSD."
        ),
        "key_finding_beyond_prior_run": (
            "Extends the Giordano-Bruno blocker (cluttered fresh crater, R~0.02) to genuinely sparse/smooth "
            "mare with strong two-Sun spread (Messier shadow ratio 2.5x, Reiner 3.5x), and adds the "
            "methodological point that clearing the azimuth gate R>=0.30 is NECESSARY BUT NOT SUFFICIENT: it "
            "can be satisfied by aggregate small-crater directional shadowing rather than an isolated boulder "
            "(Reiner high Sun), so a separability / positive-relief criterion must be added to the two-Sun test."
        ),
        "what_would_unblock": [
            "A sub-meter (<=0.5 m) two-Sun map-projected NAC pair over a site with a VERIFIED LARGE (>~8 m) "
            "ISOLATED boulder on smooth mare (e.g. a single block on flat mare with two-epoch NAC coverage): "
            "the georeferenced-ortho co-registration validated here applies directly.",
            "A ShadowCam / very-low-Sun (e <~ 5-10 deg) NAC pair over an isolated mare block -> long, cleanly "
            "separable shadow that dominates its crop's shadow-edge azimuth.",
            "Relax to a single-Sun absolute check: a sub-meter NAC stereo DTM co-located with a low-Sun NAC "
            "frame over a large isolated block -> recovered-vs-DTM height (path 1), no second Sun needed.",
        ],
        "most_uncertain_claim": (
            "That NO large isolated boulder with a separable shadow exists anywhere in the Messier/Reiner "
            "two-Sun overlaps -- detectors sampled bright peaks on smooth surroundings and resolved dark "
            "shadow blobs; the resolved blobs were dominated by small CRATER interiors (negative relief, not "
            "valid for H = L*tan(e)). A targeted survey of a known mare boulder with two-epoch coverage could "
            "still succeed."
        ),
    }
    os.makedirs(os.path.dirname(ARTIFACT), exist_ok=True)
    with open(ARTIFACT, "w") as f:
        json.dump(artifact, f, indent=2)
    print("wrote", ARTIFACT)
    make_figure(sites)


if __name__ == "__main__":
    main()
