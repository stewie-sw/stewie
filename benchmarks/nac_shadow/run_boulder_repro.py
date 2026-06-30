"""Driver: run the NAC boulder shadow-height reproduction on the FULL real NAC orthos and emit the
deliverable JSON + overlay PNG.  Real data only; the published targets enter only at the compare step.

Usage:
    .venv/bin/python benchmarks/nac_shadow/run_boulder_repro.py \
        --messier <messier_lowsun_60cm.TIF> --station6 <station6_M134991788_60cm.TIF> --outdir <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import nac_boulder_repro as M  # noqa: E402

# main House Rock fragment seed in the FULL Station 6 ortho (located by NCC to the LROC published image)
HOUSE_ROCK_SEED_GLOBAL = (4930, 6585)
HOUSE_ROCK_NCC = 0.80


def run_target_a(messier_path: str) -> dict:
    fr = M.FRAMES["messier_low_sun"]
    res = M.measure_population_hd(messier_path, fr)
    stats = res.stats()
    # diameter-convention sensitivity (NOT a tuning knob; reports robustness of the shadow metric itself)
    gray, gsd, _ = M.load_gray(messier_path)
    sens = {}
    for frac in (0.4, 0.5):
        bs = M.detect_boulders(gray, gsd, fr["sun_elevation_deg"], fr["anti_solar_image_az_deg"],
                               diameter_halfmax_frac=frac)
        v = np.array([b.h_over_d for b in bs])
        sens[f"diameter_halfmax_frac={frac}"] = {"median": round(float(np.median(v)), 3), "n": int(v.size)}
    dark_sens = {}
    for dk in (0.5, 0.6):
        bs = M.detect_boulders(gray, gsd, fr["sun_elevation_deg"], fr["anti_solar_image_az_deg"], dark_frac=dk)
        v = np.array([b.h_over_d for b in bs])
        dark_sens[f"dark_frac={dk}"] = {"median": round(float(np.median(v)), 3), "n": int(v.size)}
    verdict = M.compare_demidov(stats)
    return {"frame": fr, "stats": stats, "verdict": verdict,
            "sensitivity_diameter_convention": sens, "sensitivity_shadow_darkfrac": dark_sens,
            "boulders": [b.__dict__ for b in res.boulders], "result_object": res}


def run_target_b(station6_path: str) -> dict:
    fr = M.FRAMES["station6"]
    gray, gsd, _ = M.load_gray(station6_path)
    sx, sy = HOUSE_ROCK_SEED_GLOBAL
    hw = 60
    crop = gray[sy - hw:sy + hw, sx - hw:sx + hw]
    seed_local = (hw, hw)
    frags = []
    for thr in (230.0, 200.0, 160.0):
        m = M.measure_named_fragment(crop, gsd, fr["sun_elevation_deg"], fr["anti_solar_image_az_deg"],
                                     seed_local, cap_thr=thr)
        if m:
            m["global_seed"] = list(HOUSE_ROCK_SEED_GLOBAL)
            frags.append(m)
    largest_H = frags[1]["height_m"] if len(frags) > 1 else (frags[0]["height_m"] if frags else None)
    verdict = M.compare_station6(largest_H, frags)
    verdict["ncc_match_to_lroc_published_image"] = HOUSE_ROCK_NCC
    return {"frame": fr, "verdict": verdict, "fragments": frags, "crop": crop, "seed_local": seed_local}


def make_overlay(a: dict, b: dict, messier_path: str, png_path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import rasterio

    res = a["result_object"]
    anti = math.radians(res.anti_solar_image_az_deg)
    adx, ady = math.cos(anti), math.sin(anti)
    pdx, pdy = -ady, adx
    bs = res.boulders[:12]

    def st(im):
        m = im > 0
        lo, hi = np.percentile(im[m], (2, 98)) if m.sum() > 5 else (0, 1)
        return np.clip((im - lo) / (hi - lo + 1e-6), 0, 1)

    fig = plt.figure(figsize=(20, 12))
    gs = fig.add_gridspec(3, 6, height_ratios=[1.1, 1.1, 1.0])
    # row 0-1: 12 boulder crops with shadow vectors + d lines + labels
    ds = rasterio.open(messier_path)
    for i, bm in enumerate(bs):
        ax = fig.add_subplot(gs[i // 6, i % 6])
        hw = 30
        cc = ds.read(1, window=((bm.row - hw, bm.row + hw), (bm.col - hw, bm.col + hw))).astype(float)
        ax.imshow(st(cc), cmap="gray")
        cx = cy = hw
        ax.plot(cx, cy, "c+", ms=8)
        ax.arrow(cx, cy, adx * bm.shadow_len_px, ady * bm.shadow_len_px, color="r", width=0.3, head_width=2)
        ax.plot([cx - pdx * bm.diameter_px / 2, cx + pdx * bm.diameter_px / 2],
                [cy - pdy * bm.diameter_px / 2, cy + pdy * bm.diameter_px / 2], "y-", lw=1.5)
        ax.set_title(f"d={bm.diameter_m}m H={bm.height_m}m h/d={bm.h_over_d}", fontsize=8)
        ax.axis("off")
    ds.close()
    # row 2 left: histogram
    axh = fig.add_subplot(gs[2, 0:3])
    v = res.hd_values
    axh.hist(v, bins=20, color="steelblue", edgecolor="k", alpha=0.8)
    med = float(np.median(v))
    axh.axvline(med, color="red", lw=2, label=f"measured median h/d={med:.2f} (n={v.size})")
    axh.axvline(0.60, color="green", lw=2, ls="--", label="Demidov 2014 h/d=0.60")
    axh.axvline(0.50, color="orange", lw=1.5, ls=":", label="Demidov engineering ~0.50")
    axh.set_xlabel("h/d"); axh.set_ylabel("count")
    axh.set_title(f"TARGET A: Messier {a['frame']['nac_frame']} boulder h/d population (e={a['frame']['sun_elevation_deg']:.1f} deg)")
    axh.legend(fontsize=8)
    # row 2 right: House Rock measurement
    axb = fig.add_subplot(gs[2, 3:6])
    crop = b["crop"]
    axb.imshow(st(crop), cmap="gray")
    if b["fragments"]:
        m = b["fragments"][1] if len(b["fragments"]) > 1 else b["fragments"][0]
        aa = math.radians(m["shadow_az_deg"])
        ax2, ay2 = math.cos(aa), math.sin(aa)
        px2, py2 = -ay2, ax2
        cx, cy = b["seed_local"]
        L_px = m["shadow_len_m"] / b["frame"]["gsd_m_per_px"]
        d_px = m["diameter_m"] / b["frame"]["gsd_m_per_px"]
        axb.plot(cx, cy, "c+", ms=10)
        axb.arrow(cx, cy, ax2 * L_px, ay2 * L_px, color="r", width=0.5, head_width=3)
        axb.plot([cx - px2 * d_px / 2, cx + px2 * d_px / 2], [cy - py2 * d_px / 2, cy + py2 * d_px / 2],
                 "y-", lw=2)
        axb.set_title(f"TARGET B: Station 6 House Rock M134991788R\nlargest fragment d={m['diameter_m']}m "
                      f"L={m['shadow_len_m']}m H={m['height_m']}m (doc ~6 m)")
    axb.axis("off")
    fig.suptitle("Shadow-height metric H=L*tan(e) reproduced on REAL LROC NAC boulders", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(png_path, dpi=90)
    plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--messier", required=True)
    ap.add_argument("--station6", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    a = run_target_a(args.messier)
    b = run_target_b(args.station6)
    png = os.path.join(args.outdir, "nac_boulder_repro_2026-06-30.png")
    make_overlay(a, b, args.messier, png)

    out = {
        "experiment": "Shadow-height metric H=L*tan(e): reproduce a PUBLISHED lunar boulder "
                      "height/shape on REAL LROC NAC imagery",
        "date": str(date.today()),
        "data_real": True, "synthetic_data_used": False, "fabricated_height": False,
        "truth_firewall": "measurement reads pixels + metadata Sun elevation only; PUBLISHED targets enter "
                          "only at compare_* (verified by test_nac_boulder_repro truth-isolation tests).",
        "tooling": {"pdr": "1.4.4", "rasterio": "1.4.4",
                    "geometry_source": "ODE CDRNAC4 geometry index (incidence -> elevation=90-incidence)",
                    "dart_reuse": ["dart.shadow_height.measure_shadow_length_px",
                                   "dart.rock_taxonomy.shadow_height_m"]},
        "target_A_population_hd": {
            "site": a["frame"]["site"], "nac_frame": a["frame"]["nac_frame"],
            "ortho_file": a["frame"]["ortho_file"], "ortho_url": a["frame"]["ortho_url"],
            "incidence_deg": a["frame"]["incidence_deg"], "sun_elevation_deg": a["frame"]["sun_elevation_deg"],
            "gsd_m_per_px": a["frame"]["gsd_m_per_px"],
            "anti_solar_image_az_deg": a["frame"]["anti_solar_image_az_deg"],
            "az_validation": a["frame"]["az_validation"],
            "hd_distribution": a["stats"], "comparison": a["verdict"],
            "sensitivity_diameter_convention": a["sensitivity_diameter_convention"],
            "sensitivity_shadow_darkfrac": a["sensitivity_shadow_darkfrac"],
            "n_boulders": len(a["boulders"]),
            "boulders": [{k: vv for k, vv in bd.items()} for bd in a["boulders"]],
        },
        "target_B_station6_house_rock": {
            "site": b["frame"]["site"], "nac_frame": b["frame"]["nac_frame"],
            "ortho_file": b["frame"]["ortho_file"], "ortho_url": b["frame"]["ortho_url"],
            "incidence_deg": b["frame"]["incidence_deg"], "sun_elevation_deg": b["frame"]["sun_elevation_deg"],
            "gsd_m_per_px": b["frame"]["gsd_m_per_px"],
            "anti_solar_image_az_deg": b["frame"]["anti_solar_image_az_deg"],
            "az_validation": b["frame"]["az_validation"],
            "comparison": b["verdict"],
        },
        "published_sources": M.PUBLISHED,
        "overlay_png": os.path.basename(png),
    }
    jpath = os.path.join(args.outdir, "nac_boulder_repro_2026-06-30.json")
    with open(jpath, "w") as f:
        json.dump(out, f, indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else str(o))
    print("TARGET A:", a["verdict"]["verdict"], "| median h/d",
          a["stats"]["median"], "n", a["stats"]["n"])
    print("TARGET B:", b["verdict"]["verdict"])
    print("wrote", jpath)
    print("wrote", png)


if __name__ == "__main__":
    main()
