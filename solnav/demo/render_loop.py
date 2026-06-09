#!/usr/bin/env python3
"""Per-rover-position Godot render loop (closes the P0 perception gate).

Renders the real dustgym lunar scene from a sequence of rover STATIONS (and two camera
heights = TRANSIT vs MEERKAT posture) on the RTX 3090 via the Godot sidecar, then runs the
solnav shadow mask on each rendered-sensor frame. Demonstrates that cast shadows respond to
rover positioning and posture height, and that the masking front-end runs on rendered
imagery. This is rendered-sensor simulation; it needs the declared Godot runtime.
"""
import json
import os
import subprocess

import matplotlib
import numpy as np

matplotlib.use("Agg")
import imageio.v2 as imageiov2
import matplotlib.pyplot as plt
from imageio.v3 import imread

from solnav.perception import masking, stereo_depth
from solnav.posture import kinematics as kin

SIDE = "/mnt/projects/foss_ipex/dustgym/godot_sidecar"
SCENE = "../samples/crater_boulders"
OUTd = SIDE + "/out"
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
CX, CZ = 2.56, 2.56                      # scene center (5.12 m patch)


def render(pose, out_name):
    cmd = ["./render_layers.sh", "--", "--scene", SCENE, "--layers", "terrain,clasts",
           "--pose", ",".join(f"{v:.3f}" for v in pose), "--size", "768x576", "--out", out_name]
    result = subprocess.run(cmd, cwd=SIDE, capture_output=True, text=True, timeout=200)
    if result.returncode != 0:
        return None
    p = os.path.join(OUTd, out_name)
    return p if os.path.exists(p) else None


def main():
    # six stations across the scene; camera heights = TRANSIT (low) and MEERKAT (raised)
    h_low = 1.6 + kin.posture("TRANSIT").chassis_lift_m
    h_high = 1.6 + kin.posture("MEERKAT").chassis_lift_m
    stations = np.linspace(-1.6, 1.6, 6)
    rows = []
    frames_for_gif = []
    for i, dx in enumerate(stations):
        cam = (CX + dx, h_low, CZ + 3.2, CX, -0.1, CZ)        # station i, low posture
        p = render(cam, f"rl_{i:02d}.png")
        if p is None:
            print(f"station {i}: render FAILED"); continue
        img = np.asarray(imread(p))
        sh = masking.detect_shadow_mask(img)
        rows.append({"station": i, "dx_m": round(float(dx), 2), "posture": "TRANSIT",
                     "shadow_frac": round(float(sh.mean()), 3)})
        frames_for_gif.append(masking.overlay(stereo_depth.to_gray(img), sh))
    # multi-height: re-render station 2 at MEERKAT height (posture shadow parallax)
    cam_hi = (CX + stations[2], h_high, CZ + 3.2, CX, -0.1, CZ)
    p_hi = render(cam_hi, "rl_meerkat.png")
    meerkat = None
    if p_hi:
        img = np.asarray(imread(p_hi)); sh = masking.detect_shadow_mask(img)
        meerkat = {"station": 2, "posture": "MEERKAT", "cam_height_m": round(h_high, 2),
                   "shadow_frac": round(float(sh.mean()), 3)}

    res = {"n_stations": len(rows), "renderer": "Godot 4.6.3 / Vulkan / RTX 3090",
           "shadow_frac_by_station": [r["shadow_frac"] for r in rows],
           "shadow_frac_varies_with_position": round(float(np.ptp([r["shadow_frac"] for r in rows])), 3),
           "meerkat_vs_transit_shadow_frac": (meerkat["shadow_frac"] if meerkat else None,
                                              rows[2]["shadow_frac"] if len(rows) > 2 else None)}
    json.dump(res, open(os.path.join(OUT, "render_loop_metrics.json"), "w"), indent=2)
    for k, v in res.items():
        print(f"  {k}: {v}")

    # montage of the per-station renders + shadow overlay
    n = len(rows)
    fig, ax = plt.subplots(2, max(3, (n + 1) // 2), figsize=(15, 7))
    ax = ax.ravel()
    for i, r in enumerate(rows):
        img = np.asarray(imread(os.path.join(OUTd, f"rl_{r['station']:02d}.png")))
        sh = masking.detect_shadow_mask(img)
        ax[i].imshow(masking.overlay(stereo_depth.to_gray(img), sh))
        ax[i].set_title(f"station {r['station']} (dx={r['dx_m']} m)\nshadow {r['shadow_frac']*100:.0f}%", fontsize=9)
        ax[i].axis("off")
    for j in range(n, len(ax)):
        ax[j].axis("off")
    fig.suptitle("Per-rover-position Godot renders (real, RTX 3090) + shadow mask: shadows track position", fontsize=12)
    fig.tight_layout(rect=[0, 0, 1, 0.95]); fig.savefig(os.path.join(OUT, "render_loop_montage.png"), dpi=140); plt.close(fig)
    if frames_for_gif:
        imageiov2.mimsave(os.path.join(OUT, "render_loop.gif"), frames_for_gif, duration=0.4, loop=0)
    print("wrote render_loop_montage.png + render_loop.gif + render_loop_metrics.json")


if __name__ == "__main__":
    main()
