#!/usr/bin/env python3
"""P5 image-derived cast-shadow HEIGHT on REAL renders (spec sec 16).

Reads solnav's own self-contained Godot renders (render/p5proj/, a known 1.0 m post, top-down
orthographic, directional shadows on) at two Sun elevations, measures the cast-shadow length from
PIXELS, and recovers the post height H = L*tan(e). No truth pose is used (the post height is the
ground-truth being recovered, the Sun elevation is the render parameter). Validates both the absolute
height and the elevation-scaling L(e1)/L(e2) = tan(e2)/tan(e1).
"""
import json
import os

import numpy as np
from imageio.v3 import imread

from solnav.geometry import shadow_metric as sm

PROJ = os.path.join(os.path.dirname(__file__), "..", "render", "p5proj")
OUT = os.path.join(os.path.dirname(__file__), "out"); os.makedirs(OUT, exist_ok=True)
ORTHO_SIZE, PX = 6.0, 512
M_PER_PX = ORTHO_SIZE / PX
TRUE_H = 1.0


def measure(path, elev):
    g = np.asarray(imread(path)).astype(float)
    if g.ndim == 3:
        g = g[..., :3].mean(2)
    dark = g < 0.5 * np.median(g)                      # cast shadow << lit ground
    ys, xs = np.where(dark)
    center = np.array([g.shape[1] / 2.0, g.shape[0] / 2.0])   # post at world origin -> image center
    d = np.hypot(xs - center[0], ys - center[1])
    tip = np.array([xs[int(np.argmax(d))], ys[int(np.argmax(d))]])
    H, L = sm.shadow_height_ortho(center, tip, M_PER_PX, elev)
    return {"elev_deg": elev, "L_m": round(L, 3), "H_m": round(H, 3),
            "err_pct": round(abs(H - TRUE_H) * 100, 1), "n_dark_px": int(dark.sum())}


def main():
    r30 = measure(os.path.join(PROJ, "p5_e30.png"), 30.0)
    r50 = measure(os.path.join(PROJ, "p5_e50.png"), 50.0)
    res = {"true_height_m": TRUE_H, "m_per_px": round(M_PER_PX, 5),
           "elev30": r30, "elev50": r50,
           "length_ratio_L30_L50": round(r30["L_m"] / r50["L_m"], 2),
           "predicted_ratio_tan50_tan30": round(np.tan(np.radians(50)) / np.tan(np.radians(30)), 2),
           "provenance": "IMAGE_DERIVED",
           "note": "recovered from REAL rendered cast shadows (solnav self-contained scene, not John's sidecar)"}
    json.dump(res, open(os.path.join(OUT, "image_p5_metrics.json"), "w"), indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
