#!/usr/bin/env python3
"""VISUAL + MATH check for solnav.perception.mapping: build a 2.5D elevation + return-count map from
the REAL rendered lunar stereo traverse (frames 000..003, crater_boulders scene, Godot sensor model)
and save it beside the prior REAL DEM as a PNG, with the honest built-vs-DEM elevation statistics.

Pipeline (perception path): triangulate each stereo pair (solnav.perception.stereo_vo), place each
cloud in the Godot ground frame with the VO-estimated camera centres (a perception product) anchored
at a single start localization fix and the fixed camera-mount rotation, and accumulate the median
elevation + return count per cell. The map is then compared to the prior crater_boulders DEM.

MATH printed (honest, not a tautology):
  * raw and mean-removed elevation RMSE of the built map vs the prior DEM over the covered overlap;
  * the Pearson correlation of built vs DEM elevations (how much real relief shape was recovered);
  * recovery of a KNOWN injected horizontal offset of the built map (register_within_map), proving
    the map relief is 2-D-distinctive enough to anchor.

Truth firewall (invariant I3): the builder consumes images + the VO trajectory + a single start fix;
the only ground-truth read is the start (x, z) localization fix and, separately in the eval print,
the DEM comparison. No per-frame ground-truth pose is fed to the builder; the clast TRUTH metadata is
never read.

  python3 validation/perception/elevation_map_vs_dem.py [--output <dir>]
"""
import argparse
import json
import os
import sys

import numpy as np
from imageio.v3 import imread

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from dart import mapping, stereo_vo  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                 # .../solnav (package root dir)
CAM = os.path.join(ROOT, "validation", "a6_traverse", "cam")
SEQUENCE = os.path.join(ROOT, "validation", "a6_traverse", "sequence.json")
# EVAL/localization fix: the START (x, z) only -- read once, never per frame (invariant I3).
TRUTH = os.path.join(ROOT, "validation", "a6_traverse", "truth", "truth.json")

DEFAULT_DEM = "/mnt/projects/stewie/code/samples/crater_boulders/heightmap.rf32"
DEM_N = 256
DEM_CELL_M = 0.02
HFOV_DEG = 73.99
WIDTH, HEIGHT = 384, 288


def _load(frame_dir):
    left = np.asarray(imread(os.path.join(frame_dir, "front_left.png")))
    right = np.asarray(imread(os.path.join(frame_dir, "front_right.png")))
    return left, right


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dem", default=DEFAULT_DEM, help="REAL DEM heightmap.rf32 (little-endian f32)")
    ap.add_argument("--output", default=HERE)
    args = ap.parse_args()

    if not os.path.exists(args.dem):
        print(f"BLOCKED: real DEM not found at {args.dem}", file=sys.stderr)
        return 2
    frame_dirs = [os.path.join(CAM, f"frame_{k:03d}") for k in range(4)]
    if not all(os.path.exists(os.path.join(f, "front_left.png")) for f in frame_dirs):
        print(f"BLOCKED: rendered traverse frames not found under {CAM}", file=sys.stderr)
        return 2

    calib = json.load(open(SEQUENCE))["camera_calibration"]      # perception input (not truth)
    baseline = float(calib["baseline_m"])
    cfg = mapping.MappingConfig.from_fov(
        width_px=WIDTH, height_px=HEIGHT, hfov_deg=HFOV_DEG, baseline_m=baseline,
        cell_m=DEM_CELL_M, grid_rows=DEM_N, grid_cols=DEM_N,
        camera_height_m=0.8, look_down_ratio=0.4, max_range_m=4.0,
    )
    print(f"calibration: fx={cfg.fx_px:.2f}px (HFOV {HFOV_DEG} deg @ {WIDTH}px), baseline={baseline} m, "
          f"reference={calib['reference_camera']}")

    pairs = [_load(f) for f in frame_dirs]

    # camera centres from the PERCEPTION VO trajectory + a single start localization fix
    scfg = stereo_vo.StereoVOConfig.from_fov(
        width_px=WIDTH, height_px=HEIGHT, hfov_deg=HFOV_DEG, baseline_m=baseline,
    )
    vo = stereo_vo.estimate_vo(pairs, scfg)
    p0 = json.load(open(TRUTH))["poses"][0]                      # START FIX ONLY (x, z); not per frame
    start_xz = (float(p0["x"]), float(p0["z"]))
    centres = mapping.vo_trajectory_to_world_centres(vo.trajectory_xyz_m, cfg, start_xz=start_xz)
    print(f"VO centres (Godot x): {[round(c[0], 3) for c in centres]}  "
          f"(start fix x,z = {start_xz})")

    emap = mapping.build_elevation_map(pairs, centres, cfg)
    print(f"built map: {int(emap.covered_mask().sum())} covered cells, {emap.n_points} placed points, "
          f"{emap.n_frames} frames")

    # MATH: honest built-vs-DEM elevation statistics over the covered overlap
    dem = np.fromfile(args.dem, dtype="<f4").reshape(DEM_N, DEM_N).astype(np.float64)
    stats = mapping.elevation_rmse_vs_dem(emap.elevation, dem)
    print(f"built-vs-DEM (n={stats.covered_cells} cells): "
          f"raw RMSE={stats.raw_rmse_m:.4f} m  mean-removed RMSE={stats.mean_removed_rmse_m:.4f} m  "
          f"bias={stats.bias_m:+.4f} m  corr={stats.correlation:.4f}")

    # MATH: recover a KNOWN injected offset of the built map (registration mechanism)
    known = (3, -2)
    reg = mapping.register_within_map(emap, known_offset_cells=known, half_cells=12, window_cells=20)
    ok = abs(reg.offset_cells[0] - known[0]) <= 1 and abs(reg.offset_cells[1] - known[1]) <= 1
    print(f"injected offset {known} -> recovered {reg.offset_cells}  "
          f"peak={reg.peak:.3f}  {'MATCH' if ok else 'MISMATCH'}")

    # honest cross-registration to the prior DEM (texture-starvation limit)
    cross = mapping.correlate_to_dem(emap, dem, known_offset_cells=(0, 0), half_cells=24)
    print(f"built-vs-prior-DEM NCC cross-registration: peak={cross.peak:.4f}  "
          f"confidence={cross.confidence:.4f}  offset={cross.offset_cells} "
          f"(weak: low-texture sparse 4-frame map)")

    os.makedirs(args.output, exist_ok=True)
    out_png = os.path.join(args.output, "built_elevation_vs_dem.png")
    mapping.save_map_vs_dem_png(emap, dem, out_png, cfg=cfg)
    print(f"wrote {out_png}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
