#!/usr/bin/env python3
"""#147 tier-3 (bounded Chrono brick): settle a deterministic boulder scatter with a REAL Chrono
rigid-body solve and export the rest scene as JSON for the cockpit 3D view to render.

This uses the working core PyChrono (rigid-body SMC contact, validated vs analytic g in
scripts/test_chrono_clast_producer.py) -- it does NOT need pychrono.vehicle (the blocked SCM module)
or a GPU. It is a real Chrono producer feeding the console, not the force-accurate drum-excavation
tier (that stays blocked on the Chrono toolchain + GPU DEM; see task #147).

The exported clast (x, y, r) are in the order frame (metres from the site origin); the cockpit places
each boulder ON the loaded DEM surface (heightAt(x,y) + r), so a real Chrono-settled scatter appears as
terrain features in the same spatial view used for planning + live execution.

Run (in the dedicated Chrono env, NOT the project .venv):
    /mnt/projects/stewie/.toolchain/chrono-env/bin/python scripts/chrono_clast_scene.py \
        --out <data>/clasts_scene.json --n 16 --window 300 --seed 7
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chrono_clast_producer import G_MOON, settle_clasts  # noqa: E402  (real Chrono producer)


GROUND_HALF_M = 18.0   # settle within the settle_clasts ground box (50x50 m, +/-25 m) with margin


def _scatter(n: int, seed: int) -> list:
    """A deterministic boulder scatter CENTERED ON THE ORIGIN (the settle_clasts ground box is 50x50 m at
    the origin), a seeded golden-angle spiral within +/-GROUND_HALF_M so every clast lands ON the ground
    (no RNG; reproducible + diffable). radii 0.4..1.6 m. The caller offsets to the DEM centre afterward."""
    out = []
    golden = math.pi * (3.0 - math.sqrt(5.0))            # golden-angle spiral -> even, RNG-free spread
    for i in range(n):
        k = (i + 0.5) / n
        rad = GROUND_HALF_M * math.sqrt(k)               # spread to +/-GROUND_HALF_M (inside the ground)
        ang = (seed * 0.7) + i * golden
        x = rad * math.cos(ang)
        y = rad * math.sin(ang)
        r = 0.4 + 1.2 * (((i * 7 + seed) % 5) / 4.0)     # 0.4 .. 1.6 m, deterministic
        out.append((x, y, r))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--window", type=float, default=300.0)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    clasts = _scatter(a.n, a.seed)                        # centred on the origin (the ground box)
    res = settle_clasts(clasts, gravity_z=-G_MOON)        # REAL Chrono solve at lunar gravity
    # settle_clasts -> {"rest": [{x,y,z,radius_m,mass_kg}], "settled_time_s", "final_ke_J", "drop_pe_J", ...}
    # offset the settled (x,y) from the ground-centred Chrono frame to the DEM centre (order frame)
    off = a.window * 0.5
    scene = [{"x": round(p["x"] + off, 3), "y": round(p["y"] + off, 3), "z": round(p["z"], 3),
              "r": round(p["radius_m"], 3)} for p in res["rest"]]

    doc = {"frame": "order", "gravity": "moon", "g_ms2": G_MOON, "window_m": a.window,
           "settled_time_s": res.get("settled_time_s"),
           "final_ke_J": round(res.get("final_ke_J", 0.0), 6), "drop_pe_J": round(res.get("drop_pe_J", 0.0), 3),
           "engine": "pychrono.ChSystemSMC", "n": len(scene), "clasts": scene}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(doc, f, indent=2)
    print(f"wrote {len(scene)} settled clasts -> {a.out} (settled_t={res.get('settled_t')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
