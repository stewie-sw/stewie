#!/usr/bin/env python3
"""Produce a viz2 PLANNED-ROUTE polyline (+ its rock cluster) over a REAL DEM window (viz2 plan v4, F2).

This is the file-mediated seam between the Python mission planner (``lode.mission_planner``) and the
GDScript viz2 scene (``viz2_root._build_path_display`` / ``viz2_path.gd``): Godot cannot import Python,
so this script runs ``mission_planner.plan()`` over the REAL 1 m Haworth DEM and writes the returned
route (and the rock cluster it detours around) as JSON the scene renders verbatim.

Real data + real physics only:
  * the DEM window is streamed from the REAL LRO NAC Shape-from-Shading Haworth bundle;
  * the rock cluster is a clump of REAL Golombek-scale boulders (radii 0.45..0.9 m) whose EXPOSED
    height ``2 r (1 - buried_frac)`` exceeds the IPEx traversable-rock limit OBSTACLE_HEIGHT_M (0.075 m
    [SCHULER24]), so every boulder is genuinely impassable. The clump is a CONTROLLED placement (a real
    boulder field positioned across the corridor) so the detour reads cleanly in a capture -- the same
    controlled-fixture method the routes-around pytest uses; nothing about the terrain or the boulder
    physics is synthetic;
  * the route is the REAL ``mission_planner.plan()`` least-cost haul over the slope + rock-hazard
    keep-out costmap (``lode.costmap_layers.rock_keepouts`` -> the planner's keep-out routing).

Two outputs, both in the SCENE WORLD frame [x, height, z] (the SAME order-frame + GW-12 world mapping
``scripts/viz2_rockfield_clasts.py`` uses, so ``--clasts`` renders the cluster and ``--path`` the route):
  * ``--clasts-out``: the boulder clump (viz2_rockfield_clasts JSON schema).
  * ``--path-out``:   the planned route polyline (``waypoints`` = [x, height, z] on the real surface).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "packages", "stewie-bodies"),
           os.path.join(_REPO, "packages", "stewie-forge")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lode import costmap_layers as cl                       # noqa: E402
from lode import mission_planner as MP                      # noqa: E402
from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M       # noqa: E402
from stewie.terrain.site_dem import read_dem_window         # noqa: E402


def _rock_clump(cx, cz, radius_m, n, *, seed, r_min=0.45, r_max=0.9, buried=0.1):
    """A disk clump of REAL Golombek-scale impassable boulders (window-local metres). Uniform over the
    disk; each boulder's exposed height 2 r (1 - buried) > OBSTACLE_HEIGHT_M so all are impassable."""
    rng = np.random.default_rng(seed)
    clasts = []
    for cid in range(n):
        ang = rng.uniform(0.0, 2.0 * math.pi)
        rr = radius_m * math.sqrt(rng.uniform(0.0, 1.0))    # uniform-area disk sampling
        x = cx + rr * math.cos(ang)
        z = cz + rr * math.sin(ang)
        r = float(rng.uniform(r_min, r_max))
        clasts.append({"id": cid, "center_m": [x, 0.0, z], "radius_m": r,
                       "buried_frac": float(buried), "stratum": 0})
    return clasts


def build(bundle_dir, r0, c0, n, a_xy, b_xy, *, clump_center=None, clump_radius=12.0,
          n_boulders=240, seed=7):
    meta = json.load(open(os.path.join(bundle_dir, "metadata.json")))
    grid, bounds = meta["grid"], meta["world_bounds_m"]
    cell = float(grid["cell_m"])
    x0, y0 = float(bounds["x0"]), float(bounds["y0"])       # scene world min corner (state_fields world_min)

    dem, _cell = read_dem_window(r0, c0, n, n, bundle_dir)
    dem = np.asarray(dem, dtype=np.float64)
    h, w = dem.shape

    ccx, ccz = clump_center if clump_center else (0.5 * (a_xy[0] + b_xy[0]), 0.5 * (a_xy[1] + b_xy[1]))
    clump = _rock_clump(ccx, ccz, clump_radius, n_boulders, seed=seed)
    keepouts = cl.rock_keepouts(clump)

    # the REAL planner: one balanced cut->fill haul, routed around the rock keep-outs on the real DEM.
    mission = MP.Mission(
        name="viz2 F2 rock-detour", body="moon", charger=(float(a_xy[0]), float(a_xy[1])),
        orders=[
            MP.BuildOrder("Excavate borrow", "cut", a_xy[0], a_xy[1], 16.0, 0.3, "4x4 m"),
            MP.BuildOrder("Build fill pad", "fill", b_xy[0], b_xy[1], 16.0, 0.3, "4x4 m"),
        ],
        keepouts=tuple(keepouts))
    res = MP.plan(mission, dem=(dem, cell), dem_origin=(0.0, 0.0), max_traverse_slope_deg=25.0)
    leg = _cutfill_leg(res.totals["routes"], tuple(a_xy), tuple(b_xy))
    routed_m = _polyline_len(leg["waypoints"])

    # baseline (no rocks) for the honest detour figure printed to the log.
    import dataclasses
    base = MP.plan(dataclasses.replace(mission, keepouts=()), dem=(dem, cell), dem_origin=(0.0, 0.0))
    base_leg = _cutfill_leg(base.totals["routes"], tuple(a_xy), tuple(b_xy))
    straight_m = _polyline_len(base_leg["waypoints"])

    # scene-frame mapping (mirror viz2_rockfield_clasts): local (x, z) -> [x0+c0*cell+x, h, y0+r0*cell+z]
    def scene_xz(lx, lz):
        return x0 + c0 * cell + lx, y0 + r0 * cell + lz

    def dem_h(lx, lz):
        col = min(max(int(lx / cell), 0), w - 1)
        row = min(max(int(lz / cell), 0), h - 1)
        return float(dem[row, col])

    scene_clasts = []
    for b in clump:
        lx, _ly, lz = (float(v) for v in b["center_m"])
        sx, sz = scene_xz(lx, lz)
        r = float(b["radius_m"]); bf = float(b["buried_frac"])
        seat = dem_h(lx, lz) + (r - bf * 2.0 * r)           # partially-buried sphere seated on the surface
        scene_clasts.append({"id": int(b["id"]), "center_m": [round(sx, 4), round(seat, 4), round(sz, 4)],
                             "radius_m": r, "shape": "sphere", "buried_frac": bf, "stratum": 0})

    waypoints = []
    for (lx, lz) in leg["waypoints"]:
        sx, sz = scene_xz(float(lx), float(lz))
        waypoints.append([round(sx, 4), round(dem_h(float(lx), float(lz)), 4), round(sz, 4)])

    window = {"r0": int(r0), "c0": int(c0), "n": int(n), "cell_m": cell, "world_bounds_m": bounds}
    clasts_doc = {
        "source_bundle": os.path.basename(bundle_dir.rstrip("/")),
        "scene_name": meta.get("scene_name", ""),
        "window": window, "n_clasts": len(scene_clasts),
        "manifest": {
            "kind": "controlled_impassable_boulder_clump",
            "honesty_tags": {"spatial_abundance_k": "[DEMO-CLUSTER]", "boulder_physics": "[REAL]"},
            "honesty_note": (
                "A CONTROLLED clump of REAL Golombek-scale boulders (radii 0.45-0.9 m, exposed height "
                "> OBSTACLE_HEIGHT_M=0.075 m [SCHULER24], so all impassable) placed across the cut->fill "
                "corridor on the REAL LRO NAC SfS Haworth DEM, so the mission_planner.plan() detour reads "
                "in the capture. The DEM + boulder physics are real; the clump PLACEMENT is the controlled "
                "demo geometry (the routes-around pytest also exercises the stochastic rockfield producer)."),
            "obstacle_height_m": OBSTACLE_HEIGHT_M, "n_boulders": len(scene_clasts),
            "clump_center_local_m": [round(ccx, 3), round(ccz, 3)], "clump_radius_m": clump_radius,
        },
        "clasts": scene_clasts,
    }
    path_doc = {
        "source_bundle": os.path.basename(bundle_dir.rstrip("/")),
        "scene_name": meta.get("scene_name", ""),
        "window": window,
        "sites_local_m": {"cut": list(a_xy), "fill": list(b_xy)},
        "n_waypoints": len(waypoints),
        "routed_m": round(routed_m, 3), "straight_m": round(straight_m, 3),
        "detour_frac": round(routed_m / straight_m - 1.0, 4) if straight_m > 1e-9 else 0.0,
        "n_keepouts": len(keepouts), "obstacle_height_m": OBSTACLE_HEIGHT_M,
        "reached": bool(leg["reached"]),
        "note": ("waypoints are [x, height, z] in the SCENE WORLD frame (order-frame + GW-12 mapping); "
                 "the route is mission_planner.plan()'s least-cost haul bending around the rock keep-outs "
                 "on the real DEM."),
        "waypoints": waypoints,
    }
    return clasts_doc, path_doc


def _cutfill_leg(routes, a_xy, b_xy):
    for leg in routes:
        if {tuple(leg["from_xy"]), tuple(leg["to_xy"])} == {a_xy, b_xy}:
            return leg
    raise SystemExit(f"viz2_path: no cut->fill leg between {a_xy} and {b_xy} in the plan")


def _polyline_len(wp):
    return sum(math.hypot(wp[i + 1][0] - wp[i][0], wp[i + 1][1] - wp[i][1]) for i in range(len(wp) - 1))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bundle", default=os.path.join(_REPO, "samples", "lunar_dem", "haworth_sfs_2km_1m"))
    ap.add_argument("--r0", type=int, default=1520)         # the flattest 120x120 real window (no drop-offs)
    ap.add_argument("--c0", type=int, default=0)
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--a", default="20,60", help="cut site, window-local metres 'x,y'")
    ap.add_argument("--b", default="100,60", help="fill site, window-local metres 'x,y'")
    ap.add_argument("--clump", default="60,60", help="rock-clump centre, window-local metres 'x,y'")
    ap.add_argument("--clump-radius", type=float, default=12.0)
    ap.add_argument("--n-boulders", type=int, default=240)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--clasts-out", required=True)
    ap.add_argument("--path-out", required=True)
    a = ap.parse_args()
    if not os.path.isdir(a.bundle):
        print(f"viz2_path: bundle not found: {a.bundle}", file=sys.stderr)
        return 2
    a_xy = tuple(float(v) for v in a.a.split(","))
    b_xy = tuple(float(v) for v in a.b.split(","))
    clump = tuple(float(v) for v in a.clump.split(","))
    clasts_doc, path_doc = build(a.bundle, a.r0, a.c0, a.n, a_xy, b_xy,
                                 clump_center=clump, clump_radius=a.clump_radius,
                                 n_boulders=a.n_boulders, seed=a.seed)
    for out, doc in ((a.clasts_out, clasts_doc), (a.path_out, path_doc)):
        os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
        with open(out, "w") as fh:
            json.dump(doc, fh)
    print(f"viz2_path: {path_doc['n_waypoints']}-wp route over {a.n}x{a.n} @ {path_doc['window']['cell_m']} m "
          f"({clasts_doc['source_bundle']}); {clasts_doc['n_clasts']} boulders "
          f"({path_doc['n_keepouts']} impassable keep-outs)")
    print(f"  routed {path_doc['routed_m']} m vs straight {path_doc['straight_m']} m "
          f"-> detour +{100 * path_doc['detour_frac']:.1f}%")
    print(f"  -> clasts {a.clasts_out}")
    print(f"  -> path   {a.path_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
