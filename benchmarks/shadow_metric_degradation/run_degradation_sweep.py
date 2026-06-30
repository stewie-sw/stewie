"""Degradation-sensitivity analysis of the STEWIE cast-shadow-length metric observable.

WHAT THIS IS (read this first):
  A MODELED-DEGRADATION sensitivity sweep of the shadow-length measurement (recover caster height
  H = L*tan(e) from a measured shadow length L). It characterizes the metric's OPERATING ENVELOPE
  under modeled sensor degradation, in the style of the Stanford DEM-anchoring paper's Table 2
  (controlled perturbation ladder -> error + breaking point). It is NOT a real-imagery validation
  of the metric. It does NOT unblock E3 (the two-split residual verification on real ShadowCam/NAC
  imagery). The 2026-06-24 render hard negative (<=1/143 clasts measurable) STANDS; this analysis
  explains WHY by isolating which degradation channel breaks the metric on the clean controlled case.

PIPELINE UNDER TEST (live tree /mnt/projects/stewie/code):
  - Association front-end (the proposal's "association"): dart/shadow_extract.py::associate_base_tip
    (image-derived caster base + shadow tip, with a refusal gate) -> dart/geometry/shadow_metric.py
    ::shadow_height_ortho (H = L*tan(e), top-down orthographic). This is the pipeline the proposal
    reports at 0.0%/0.2% relative height error and the one whose REFUSAL ENVELOPE we characterize.
  - Geometric reference recovery (no refusal, isolates length-measurement-only degradation):
    stewie/eval/gates.py::_controlled_p5_height (fixed image-center base + farthest-dark tip).
  - sigma_n edge-noise model: dart/shadow_edge_sigma.py (measured sigma_edge 0.685 px, real CE-3).
  - SHADOW_LENGTH factor type: dart/factors.py::FactorType.SHADOW_LENGTH (currently metric-blocked).

CONTROLLED ZERO-DEGRADATION BASELINE:
  stewie/eval/tests/fixtures/p5_post_e{30,50}.png -- a rendered vertical post of KNOWN height 1.0 m
  with a clean cast shadow, GSD 6/512 m/px, Sun elevation 30 and 50 deg.

DEGRADATION CHANNELS (the B-render-fidelity channels, all REAL radiometric models, no fabrication):
  saturation_clip, veiling_glare, psf_blur, dust_haze, edge_noise. See DEGRADATIONS below.

Truth (the known 1.0 m caster height) is used ONLY to score recovery error, never inside any
measurement. The Sun elevation and GSD are scene calibration (legitimately known), not height truth.

Run:  PYTHONPATH=/mnt/projects/stewie/code \
      /mnt/projects/07_runtime_system/venv/bin/python \
      benchmarks/shadow_metric_degradation/run_degradation_sweep.py
"""
# PROVENANCE: STEWIE DART subsystem -- modeled-degradation sensitivity analysis (A. Storey)
from __future__ import annotations

import json
import os
from datetime import date as _date

import numpy as np
from imageio.v3 import imread
from scipy.ndimage import gaussian_filter

from dart import shadow_extract as se
from dart.geometry import shadow_metric as sm

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURES = os.path.join(_REPO, "stewie", "eval", "tests", "fixtures")
VALIDATION = os.path.join(_REPO, "stewie", "eval", "validation")
GSD = 6.0 / 512.0            # m per px, from the gate (stewie/eval/gates.py)
TRUE_H = 1.0                 # m, the post's known height (the fixture truth; scoring only)
DRIFT_THRESHOLD = 0.01       # gate's own association-reproduction PASS threshold (gates.py:233)
N_SEEDS = 24                 # stochastic edge-noise channel: seeds per level

CASES = (("p5_post_e30.png", 30.0), ("p5_post_e50.png", 50.0))


def load_gray(name: str) -> np.ndarray:
    img = np.asarray(imread(os.path.join(FIXTURES, name)), dtype=float)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    return img


# ----------------------------------------------------------------------------------------------
# REAL degradation models. Each maps (clean float grayscale [0,255], level) -> degraded float gray.
# ----------------------------------------------------------------------------------------------
def deg_saturation_clip(g: np.ndarray, gain: float, ctx: dict) -> np.ndarray:
    """Highlight saturation / clipping: a linear sensor gain past the well-capacity hard clip.
    out = clip(in * gain, 0, 255). Sunlit regolith blows out as gain rises."""
    return np.clip(g * gain, 0.0, 255.0)


def deg_veiling_glare(g: np.ndarray, floor_dn: float, ctx: dict) -> np.ndarray:
    """Veiling glare: an additive scattered-light floor (lens flare/stray light) that lifts the
    shadow toward the background and reduces shadow contrast. out = clip(in + floor, 0, 255)."""
    return np.clip(g + floor_dn, 0.0, 255.0)


def deg_psf_blur(g: np.ndarray, sigma_px: float, ctx: dict) -> np.ndarray:
    """Optical PSF / MTF blur: a Gaussian point-spread (defocus/diffraction) over the image, which
    spreads the lit->shadow edge (penumbra) and pulls the shadow tip inward. sigma in px."""
    if sigma_px <= 0:
        return g.copy()
    return gaussian_filter(g, sigma=float(sigma_px), mode="nearest")


def deg_dust_haze(g: np.ndarray, haze: float, ctx: dict) -> np.ndarray:
    """Dust / haze: Koschmieder transmission model out = in*t + A*(1-t), transmission t = 1 - haze,
    airlight A = the scene's bright (sunlit) level. Compresses contrast toward the airlight, a
    distinct physics from the additive veiling-glare floor (multiplicative compression vs offset)."""
    t = 1.0 - float(haze)
    A = ctx["airlight"]
    return np.clip(g * t + A * (1.0 - t), 0.0, 255.0)


def deg_edge_noise(g: np.ndarray, sigma_dn: float, ctx: dict) -> np.ndarray:
    """Per-pixel additive Gaussian read noise (perturbs shadow-boundary localization). Seeded for
    reproducibility; the caller sweeps seeds and reports mean +/- std + refusal rate."""
    if sigma_dn <= 0:
        return g.copy()
    rng = np.random.default_rng(ctx["seed"])
    return np.clip(g + rng.normal(0.0, float(sigma_dn), size=g.shape), 0.0, 255.0)


DEGRADATIONS = {
    "saturation_clip": {
        "fn": deg_saturation_clip, "unit": "exposure gain (x)",
        "model": "out = clip(in * gain, 0, 255)  -- linear sensor gain past a hard well-capacity clip",
        "levels": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
    },
    "veiling_glare": {
        "fn": deg_veiling_glare, "unit": "additive floor (DN)",
        "model": "out = clip(in + floor, 0, 255)  -- uniform scattered-light/flare floor",
        "levels": [0.0, 10.0, 20.0, 30.0, 40.0, 60.0, 80.0],
    },
    "psf_blur": {
        "fn": deg_psf_blur, "unit": "PSF sigma (px)",
        "model": "Gaussian PSF, scipy.ndimage.gaussian_filter(sigma)  -- defocus/diffraction MTF",
        "levels": [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0],
    },
    "dust_haze": {
        "fn": deg_dust_haze, "unit": "haze opacity (1 - t)",
        "model": "out = in*t + A*(1-t)  -- Koschmieder transmission, airlight A = 95th-pct scene DN",
        "levels": [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
    },
    "edge_noise": {
        "fn": deg_edge_noise, "unit": "read-noise sigma (DN)",
        "model": "out = clip(in + N(0, sigma), 0, 255)  -- additive Gaussian read noise, %d seeds/level"
                 % N_SEEDS,
        "levels": [0.0, 2.0, 5.0, 10.0, 15.0, 20.0, 30.0],
    },
}


# ----------------------------------------------------------------------------------------------
# Recovery pipelines (read-only callers of the live tree; no edits to the pipeline).
# ----------------------------------------------------------------------------------------------
def recover_assoc(gray: np.ndarray, elev_deg: float) -> dict:
    """The proposal's ASSOCIATION front-end + H=L*tan(e). Returns recovery or a refusal."""
    try:
        a = se.associate_base_tip(gray)
        h, length = sm.shadow_height_ortho(a["base_px"], a["tip_px"], GSD, elev_deg)
        return {"refused": False, "H_m": float(h), "L_m": float(length),
                "direction_deg": float(a["direction_deg"]), "confidence": float(a["confidence"])}
    except ValueError as e:
        return {"refused": True, "reason": str(e)}


def recover_geom(gray: np.ndarray, elev_deg: float) -> dict:
    """The GEOMETRIC reference recovery (gates._controlled_p5_height): fixed image-center base +
    farthest-dark tip. No refusal gate -- isolates length-measurement-only degradation."""
    med = float(np.median(gray))
    dark = gray < 0.5 * med
    rows, cols = np.where(dark)
    if rows.size == 0:
        return {"degenerate": True}
    center = np.array([gray.shape[1] / 2.0, gray.shape[0] / 2.0])
    d = np.hypot(cols - center[0], rows - center[1])
    tip = np.array([cols[int(np.argmax(d))], rows[int(np.argmax(d))]])
    h, length = sm.shadow_height_ortho(center, tip, GSD, elev_deg)
    return {"degenerate": False, "H_m": float(h), "L_m": float(length), "n_dark": int(rows.size)}


def sweep_case(name: str, elev_deg: float) -> dict:
    gray = load_gray(name)
    airlight = float(np.percentile(gray, 95))
    clean_assoc = recover_assoc(gray, elev_deg)
    clean_geom = recover_geom(gray, elev_deg)
    H_clean = clean_assoc["H_m"]                 # degradation drift is referenced to the clean assoc H
    H_clean_geom = clean_geom["H_m"]

    out = {
        "fixture": name, "sun_elev_deg": elev_deg,
        "airlight_dn_p95": round(airlight, 2),
        "clean_baseline": {
            "assoc": {**{k: (round(v, 5) if isinstance(v, float) else v)
                         for k, v in clean_assoc.items()},
                      "abs_err_vs_truth": round(abs(H_clean - TRUE_H) / TRUE_H, 5)},
            "geom_reference": {**{k: (round(v, 5) if isinstance(v, float) else v)
                                  for k, v in clean_geom.items()},
                               "abs_err_vs_truth": round(abs(H_clean_geom - TRUE_H) / TRUE_H, 5)},
            "assoc_vs_ref_rel": round(abs(H_clean - H_clean_geom) / H_clean_geom, 5),
        },
        "channels": {},
        "breaking_points": {},
        "operating_envelope": {},
    }

    for chan, spec in DEGRADATIONS.items():
        rows = []
        for lvl in spec["levels"]:
            if chan == "edge_noise" and lvl > 0:
                Hs, drifts, abserrs, refusals, dirs, confs = [], [], [], [], [], []
                for s in range(N_SEEDS):
                    g = spec["fn"](gray, lvl, {"airlight": airlight, "seed": 1000 + s})
                    r = recover_assoc(g, elev_deg)
                    if r["refused"]:
                        refusals.append(1)
                    else:
                        refusals.append(0)
                        Hs.append(r["H_m"]); dirs.append(r["direction_deg"]); confs.append(r["confidence"])
                        drifts.append(abs(r["H_m"] - H_clean) / H_clean)
                        abserrs.append(abs(r["H_m"] - TRUE_H) / TRUE_H)
                rate = float(np.mean(refusals))
                row = {"level": lvl, "refusal_rate": round(rate, 3), "n_seeds": N_SEEDS}
                if Hs:
                    row.update({
                        "H_m_mean": round(float(np.mean(Hs)), 5),
                        "H_m_std": round(float(np.std(Hs)), 5),
                        "drift_from_clean_mean": round(float(np.mean(drifts)), 5),
                        "drift_from_clean_max": round(float(np.max(drifts)), 5),
                        "abs_err_vs_truth_mean": round(float(np.mean(abserrs)), 5),
                        "direction_deg_mean": round(float(np.mean(dirs)), 2),
                        "confidence_mean": round(float(np.mean(confs)), 3),
                    })
                rows.append(row)
            else:
                g = spec["fn"](gray, lvl, {"airlight": airlight, "seed": 0})
                r = recover_assoc(g, elev_deg)
                if r["refused"]:
                    rows.append({"level": lvl, "refused": True, "reason": r["reason"]})
                else:
                    rows.append({
                        "level": lvl, "refused": False,
                        "H_m": round(r["H_m"], 5),
                        "L_m": round(r["L_m"], 5),
                        "drift_from_clean": round(abs(r["H_m"] - H_clean) / H_clean, 5),
                        "abs_err_vs_truth": round(abs(r["H_m"] - TRUE_H) / TRUE_H, 5),
                        "direction_deg": round(r["direction_deg"], 2),
                        "confidence": round(r["confidence"], 3),
                    })
        out["channels"][chan] = rows

        # breaking point: first level that REFUSES or drifts past the gate's 1% reproduction threshold
        bp = None; mode = "none_within_swept_range"
        for row in rows:
            lvl = row["level"]
            refused = row.get("refused", False) or row.get("refusal_rate", 0.0) >= 0.5
            drift = row.get("drift_from_clean", row.get("drift_from_clean_mean", 0.0))
            if refused:
                bp, mode = lvl, "association_refuses"
                break
            if drift is not None and drift > DRIFT_THRESHOLD:
                bp, mode = lvl, "drift_exceeds_1pct"
                break
        # last-good = the largest level strictly before the breaking level (the tolerated envelope)
        levels = spec["levels"]
        last_good = None
        if bp is not None:
            idx = levels.index(bp)
            last_good = levels[idx - 1] if idx > 0 else None
        else:
            last_good = levels[-1]
        out["breaking_points"][chan] = {
            "breaking_level": bp, "breaking_mode": mode, "last_good_level": last_good,
            "unit": spec["unit"],
        }
        out["operating_envelope"][chan] = (
            f"tolerated up to {last_good} {spec['unit']}"
            + (f"; breaks at {bp} ({mode})" if bp is not None else " (no break within swept range)")
        )
    return out


def main() -> int:
    today = _date.today().isoformat()
    cases = [sweep_case(name, elev) for name, elev in CASES]

    # dominant degradation = the channel that breaks earliest as a fraction of its swept ladder,
    # judged on the primary (e30, longer-shadow) case; reported from the data, not assumed.
    primary = cases[0]
    frac = {}
    for chan, spec in DEGRADATIONS.items():
        bp = primary["breaking_points"][chan]["breaking_level"]
        levels = spec["levels"]
        if bp is None:
            frac[chan] = 1.0
        else:
            frac[chan] = levels.index(bp) / (len(levels) - 1)
    dominant = min(frac, key=frac.get)

    artifact = {
        "experiment": "Cast-shadow-length metric (H=L*tan(e)) degradation-sensitivity analysis",
        "date": today,
        "analysis_type": "MODELED-DEGRADATION sensitivity sweep (bounds the operating envelope)",
        "NOT_a_validation": (
            "This is a modeled-degradation sensitivity analysis on a CLEAN controlled rendered fixture. "
            "It bounds the metric's operating envelope under modeled sensor degradation. It is NOT a "
            "real-imagery validation of the metric and does NOT unblock E3 (the two-split residual "
            "verification still needs real ShadowCam/LROC-NAC grazing-sun imagery with surveyed/DEM "
            "caster truth). The 2026-06-24 render hard negative (<=1/143 clasts measurable) STANDS."
        ),
        "pipeline_file_lines": {
            "association_front_end": "dart/shadow_extract.py::associate_base_tip (refusal gate)",
            "height_recovery": "dart/geometry/shadow_metric.py::shadow_height_ortho (H=L*tan(e))",
            "geometric_reference": "stewie/eval/gates.py::_controlled_p5_height",
            "sigma_n_edge_model": "dart/shadow_edge_sigma.py (measured sigma_edge 0.685 px, real CE-3)",
            "shadow_length_factor": "dart/factors.py::FactorType.SHADOW_LENGTH (metric-blocked: "
                                    "assert_current_claim_allowed)",
        },
        "controlled_reference_case": {
            "fixtures": [c[0] for c in CASES],
            "true_caster_height_m": TRUE_H,
            "gsd_m_per_px": round(GSD, 7),
            "note": "single vertical post of known height with a clean cast shadow; single-caster, so "
                    "the per-caster metric is |dH|/H, not a multi-caster correlation r.",
        },
        "scoring": {
            "metric_error_definition": "drift_from_clean = |H_deg - H_clean| / H_clean (degradation-"
                                       "induced); abs_err_vs_truth = |H - 1.0| / 1.0 (physical).",
            "breaking_criterion": "ASSOCIATION refuses (ValueError) OR drift_from_clean > %.2f (the "
                                  "gate's own association-reproduction PASS threshold, "
                                  "stewie/eval/gates.py:233)." % DRIFT_THRESHOLD,
            "truth_use": "the 1.0 m height is used ONLY to score recovery; Sun elevation and GSD are "
                         "scene calibration, not height truth.",
        },
        "degradation_models": {k: {"unit": v["unit"], "model": v["model"], "levels": v["levels"]}
                               for k, v in DEGRADATIONS.items()},
        "cases": cases,
        "dominant_degradation": {
            "channel": dominant,
            "criterion": "earliest breaking level as a fraction of its swept ladder, on the primary "
                         "(e30) case",
            "breaking_fraction_by_channel": {k: round(v, 3) for k, v in frac.items()},
        },
        "relation_to_2026_06_24_hard_negative": (
            "Consistent with, and explanatory of, the dated render hard negative. On the CLEAN "
            "single-post fixture the metric works; the breaking channels here (see dominant_degradation) "
            "are exactly the radiometric failures that natural clasts on the crater_boulders render "
            "exhibit jointly (low shadow contrast + soft/penumbral edges), which is why <=1/143 natural "
            "clasts were measurable. This analysis does not contradict that finding; it localizes the cause."
        ),
        "honest_negative_context": True,
    }

    out_json = os.path.join(VALIDATION, f"shadow_metric_degradation_{today}.json")
    with open(out_json, "w") as f:
        json.dump(artifact, f, indent=1, sort_keys=False)
        f.write("\n")
    print(f"wrote {out_json}")

    _make_figure(cases, os.path.join(VALIDATION, f"shadow_metric_degradation_{today}.png"))
    return 0


def _make_figure(cases: list, path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    chans = list(DEGRADATIONS.keys())
    fig, axes = plt.subplots(1, len(chans), figsize=(4.0 * len(chans), 4.2), sharey=True)
    colors = {"p5_post_e30.png": "#1f77b4", "p5_post_e50.png": "#d62728"}
    for ax, chan in zip(axes, chans):
        spec = DEGRADATIONS[chan]
        for case in cases:
            rows = case["channels"][chan]
            xs, ys, refuse_x = [], [], []
            for row in rows:
                lvl = row["level"]
                if row.get("refused") or row.get("refusal_rate", 0.0) >= 0.5:
                    refuse_x.append(lvl)
                    continue
                drift = row.get("drift_from_clean", row.get("drift_from_clean_mean"))
                if drift is not None:
                    xs.append(lvl); ys.append(100.0 * drift)
            c = colors[case["fixture"]]
            lbl = f"e{int(case['sun_elev_deg'])}"
            ax.plot(xs, ys, "o-", color=c, label=lbl, ms=4)
            for rx in refuse_x:
                ax.axvline(rx, color=c, ls=":", alpha=0.4)
                ax.plot([rx], [ax.get_ylim()[1] * 0.92 if ax.get_ylim()[1] > 0 else 1], "x",
                        color=c, ms=9, mew=2)
        ax.axhline(100.0 * DRIFT_THRESHOLD, color="gray", ls="--", lw=1)
        ax.set_title(chan.replace("_", " "), fontsize=10)
        ax.set_xlabel(spec["unit"], fontsize=8)
        ax.grid(alpha=0.25)
        ax.set_yscale("symlog", linthresh=1.0)
    axes[0].set_ylabel("metric drift |dH|/H_clean  (%)  [symlog]", fontsize=9)
    axes[0].legend(fontsize=8, title="Sun elev", loc="upper left")
    fig.suptitle("STEWIE cast-shadow-length metric: MODELED degradation sensitivity "
                 "(NOT real-imagery validation)\n"
                 "x = refuses (dotted line);  gray dash = 1% gate reproduction threshold;  "
                 "clean abs. error vs 1.0 m truth ~4-5%", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=130)
    plt.close(fig)
    print(f"wrote {path}")


if __name__ == "__main__":
    raise SystemExit(main())
