#!/usr/bin/env python3
"""Produce a viz2 rock-field clast JSON over a REAL DEM window (viz2 plan v4, Phase D display).

This is the file-mediated seam between the Python D1 spatial-k Golombek producer
(``stewie.terrain.rockfield``) and the GDScript viz2 scene (``viz2_root._build_clasts_display``):
Godot cannot import Python, so this script writes the clasts (in the SCENE WORLD frame) as JSON that
``viz2_root.gd --clasts <path>`` renders verbatim through the frozen clast render path.

Real data only. The clasts are STATISTICAL — drawn (Poisson) from the sourced Golombek size-frequency
law over the REAL heightfield's morphology (a sparse polar background rising toward the fresh crater
rims / high-curvature / steep-ejecta cells the DEM actually shows), never invented; the honest
``[CALIB]``/``[UNKNOWN]`` tags from ``rockfield`` ride along in the emitted manifest.

Frames (the ONE subtlety):
  * ``rockfield`` seeds its Poisson draw by the window's TRUE polar-stereographic global origin (so the
    draw is a pure function of the WORLD point — determinism), but returns each clast center_m in
    WINDOW-LOCAL metres with the height relative to a surface≈0 reference.
  * the viz2 SCENE places geometry at ``world_pos(row,col) = (x0 + col*cell, height, y0 + row*cell)``
    (state_fields.gd:456, from ``world_bounds_m``). So each clast is re-expressed into that scene frame:
      scene_x = x0 + (c0 + col_local)*cell,  scene_z = y0 + (r0 + row_local)*cell,
      scene_y = DEM_height[r0+row_local, c0+col_local] + (radius - buried*diameter)
    i.e. the partially-buried sphere is seated on the REAL surface at its own cell. The DEM window is
    read from the SAME ``heightmap.rf32`` the scene renders (site_dem.read_dem_window), same row-major
    orientation, so the placement is pixel-consistent with the terrain mesh.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from stewie.terrain import rockfield                       # noqa: E402
from stewie.terrain.site_dem import read_dem_window        # noqa: E402


def build_clasts(bundle_dir: str, r0: int, c0: int, n: int, *,
                 d_min_m: float = 0.25, d_max_m: float = 0.6,
                 world_seed: int = 0) -> dict:
    """Generate the spatial-k rock field over the ``[r0:r0+n, c0:c0+n]`` window of ``bundle_dir`` and
    return a dict ``{clasts, manifest, window, source_bundle}`` with clasts in the SCENE WORLD frame."""
    meta = json.load(open(os.path.join(bundle_dir, "metadata.json")))
    grid = meta["grid"]
    bounds = meta["world_bounds_m"]
    cell = float(grid["cell_m"])
    x0 = float(bounds["x0"])                                # scene world min corner (state_fields world_min)
    y0 = float(bounds["y0"])
    y1 = float(bounds["y1"])

    dem, _cell = read_dem_window(r0, c0, n, n, bundle_dir)
    dem = np.asarray(dem, dtype=np.float64)
    h, w = dem.shape

    # Polar-stereographic origin of the window (pixel-center) for the DETERMINISTIC seed only
    # (matches rockfield.rock_field_for_dem_window; north-up raster: y1 is the top row).
    seed_x0 = x0 + (c0 + 0.5) * cell
    seed_y0 = y1 - (r0 + 0.5) * cell

    rf = rockfield.rock_field(dem, cell, world_x0=seed_x0, world_y0=seed_y0,
                              world_seed=world_seed, d_min_m=d_min_m, d_max_m=d_max_m)

    scene_clasts: list[dict] = []
    for c in rf["clasts"]:
        x_local, y_rel, z_local = (float(v) for v in c["center_m"])
        col_local = min(max(int(x_local / cell), 0), w - 1)
        row_local = min(max(int(z_local / cell), 0), h - 1)
        abs_h = float(dem[row_local, col_local])
        scene_clasts.append({
            "id": int(c["id"]),
            "center_m": [round(x0 + c0 * cell + x_local, 4),
                         round(abs_h + y_rel, 4),
                         round(y0 + r0 * cell + z_local, 4)],
            "radius_m": float(c["radius_m"]),
            "shape": c.get("shape", "sphere"),
            "buried_frac": float(c["buried_frac"]),
            "stratum": int(c.get("stratum", 0)),
        })

    return {
        "source_bundle": os.path.basename(bundle_dir.rstrip("/")),
        "scene_name": meta.get("scene_name", ""),
        "window": {"r0": int(r0), "c0": int(c0), "n": int(n), "cell_m": cell,
                   "world_bounds_m": bounds},
        "n_clasts": len(scene_clasts),
        "manifest": rf["manifest"],                         # verbatim [CALIB]/[UNKNOWN] tags + provenance
        "clasts": scene_clasts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default=os.path.join(_REPO, "samples", "lunar_dem", "haworth_sfs_2km_1m"))
    ap.add_argument("--r0", type=int, default=800)
    ap.add_argument("--c0", type=int, default=800)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--d-min", type=float, default=0.25)
    ap.add_argument("--d-max", type=float, default=0.6)
    ap.add_argument("--world-seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not os.path.isdir(a.bundle):
        print(f"viz2_rockfield_clasts: bundle not found: {a.bundle}", file=sys.stderr)
        return 2
    out = build_clasts(a.bundle, a.r0, a.c0, a.n, d_min_m=a.d_min, d_max_m=a.d_max,
                       world_seed=a.world_seed)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(out, fh)
    strata = out["manifest"].get("strata", [])
    dens = [(s["stratum"], s["k"], s["n_clasts"], round(s["n_clasts"] / s["area_m2"] * 1e4, 2))
            for s in strata if s.get("area_m2")]
    print(f"viz2_rockfield_clasts: {out['n_clasts']} clasts over {a.n}x{a.n} @ {out['window']['cell_m']} m "
          f"({out['source_bundle']}); spatial_abundance_k="
          f"{out['manifest']['honesty_tags']['spatial_abundance_k']}")
    print(f"  density/(100m)^2 by stratum (k rises toward rims): {dens}")
    print(f"  -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
