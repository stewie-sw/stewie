#!/usr/bin/env python3
"""Pack a COLMAP dense fused.ply into a single-tile Cesium 3D Tiles point cloud, georeferenced + gravity-
aligned + metric-scaled onto a lunar site -- the data source for the cockpit's "reconstruction twin" globe
layer (Cesium3DTileset).

Faithful placement (real data only -- the dense cloud + the real Godot ground-truth poses):
  1. Recompute the Umeyama Sim3 that aligned the COLMAP camera centres (sparse/0/images.txt) to the Godot
     ground-truth centres (sensors.json pose_in_world) -- the SAME alignment colmap_recon reports. Applying
     it maps the dense cloud into the METRIC Godot world frame (real scale, gravity-correct: Godot is Y-up).
  2. Godot (Y-up, -Z forward, +X right) -> ENU (X east, Y north, Z up): enu = (x, -z, y), so "up" is up.
  3. Centre the cloud at the ENU origin so it sits exactly at the site.
  4. Emit ONE .pnts tile (POSITION f32 + RGB u8; ~150k pts fits a single tile) + a tileset.json whose root
     transform is the WGS84 ENU->ECEF frame at the site lat/lon -- WGS84 because the cockpit's Cesium globe
     uses Ellipsoid.WGS84 (the radius is cosmetic there), so the twin lands where the work-area footprint is.

No py3dtiles dependency (the .pnts byte layout is written directly). Reuses colmap_recon's exact pose +
alignment conventions by import.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from colmap_recon import parse_images_txt, umeyama_sim3  # noqa: E402  (reuse exact conventions)

_PLY_NP = {"float": "<f4", "float32": "<f4", "double": "<f8", "uchar": "u1", "uint8": "u1",
           "int": "<i4", "char": "i1", "short": "<i2", "ushort": "<u2"}


def load_ply_xyz_rgb(path: str):
    """Read a binary_little_endian PLY -> (xyz float64 (N,3), rgb uint8 (N,3))."""
    with open(path, "rb") as f:
        hdr = b""
        while b"end_header" not in hdr:
            line = f.readline()
            if not line:
                raise ValueError("PLY: no end_header")
            hdr += line
        lines = hdr.decode("ascii", "replace").splitlines()
        fmt = next(line for line in lines if line.startswith("format"))
        if "binary_little_endian" not in fmt:
            raise ValueError(f"PLY: expected binary_little_endian, got {fmt!r}")
        n = int(next(line for line in lines if line.startswith("element vertex")).split()[-1])
        props = [line.split()[1:] for line in lines if line.startswith("property")]
        dt = np.dtype([(p[1], _PLY_NP[p[0]]) for p in props])
        data = np.frombuffer(f.read(n * dt.itemsize), dtype=dt, count=n)
    xyz = np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float64)
    rgb = np.stack([data["red"], data["green"], data["blue"]], axis=1).astype(np.uint8)
    return xyz, rgb


def enu_to_ecef_transform(lat_deg: float, lon_deg: float, h: float = 0.0) -> list[float]:
    """Column-major 4x4 (Cesium tileset `transform`) mapping local ENU metres -> WGS84 ECEF at the site."""
    a, f = 6378137.0, 1.0 / 298.257223563
    e2 = f * (2.0 - f)
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sl, cl, so, co = math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon)
    nrad = a / math.sqrt(1.0 - e2 * sl * sl)
    x, y, z = (nrad + h) * cl * co, (nrad + h) * cl * so, (nrad * (1.0 - e2) + h) * sl
    east, north, up = (-so, co, 0.0), (-sl * co, -sl * so, cl), (cl * co, cl * so, sl)
    return [east[0], east[1], east[2], 0.0, north[0], north[1], north[2], 0.0,
            up[0], up[1], up[2], 0.0, x, y, z, 1.0]


def write_pnts(path: str, pos_f32: np.ndarray, rgb_u8: np.ndarray) -> int:
    """Write a Cesium .pnts (POSITION + RGB, RTC_CENTER at origin). Returns the byte length."""
    n = int(pos_f32.shape[0])
    pos_bytes = np.ascontiguousarray(pos_f32, dtype="<f4").tobytes()
    rgb_bytes = np.ascontiguousarray(rgb_u8, dtype="u1").tobytes()
    ft_bin = pos_bytes + rgb_bytes
    ft_bin += b"\x00" * ((8 - (len(ft_bin) % 8)) % 8)               # FT binary padded to 8 bytes
    ft_json = json.dumps({"POINTS_LENGTH": n, "RTC_CENTER": [0.0, 0.0, 0.0],
                          "POSITION": {"byteOffset": 0}, "RGB": {"byteOffset": len(pos_bytes)}},
                         separators=(",", ":")).encode("utf-8")
    ft_json += b" " * ((8 - ((28 + len(ft_json)) % 8)) % 8)         # FT binary must start 8-byte aligned
    total = 28 + len(ft_json) + len(ft_bin)
    header = struct.pack("<4sIIIIII", b"pnts", 1, total, len(ft_json), len(ft_bin), 0, 0)
    with open(path, "wb") as f:
        f.write(header + ft_json + ft_bin)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="COLMAP dense fused.ply -> georeferenced Cesium 3D Tiles tile")
    ap.add_argument("--ply", required=True, help="dense fused.ply (COLMAP frame)")
    ap.add_argument("--sparse", required=True, help="sparse model dir holding images.txt (e.g. .../sparse/0)")
    ap.add_argument("--sensors", required=True, help="sensors.json with ground-truth pose_in_world")
    ap.add_argument("--lat", type=float, required=True, help="site centre latitude (deg)")
    ap.add_argument("--lon", type=float, required=True, help="site centre longitude (deg)")
    ap.add_argument("--out-dir", required=True, dest="out_dir", help="tileset output dir")
    args = ap.parse_args()

    # (1) recompute the Sim3 COLMAP-centres -> Godot GT-centres (metric, gravity-correct).
    imgs = parse_images_txt(os.path.join(args.sparse, "images.txt"))
    sensors = json.load(open(args.sensors))
    gt = {c["image"]: np.array(c["pose_in_world"]["position_m"], float) for c in sensors["cameras"]}
    matched = sorted((n for n in imgs if n in gt))
    if len(matched) < 3:
        print(f"ply_to_3dtiles: only {len(matched)} matched cams (<3) -- cannot align", file=sys.stderr)
        return 2
    src = np.array([imgs[n].center() for n in matched])
    dst = np.array([gt[n] for n in matched])
    s, R, t = umeyama_sim3(src, dst)

    # (2-3) cloud -> metric Godot frame -> ENU -> centred at the site.
    xyz, rgb = load_ply_xyz_rgb(args.ply)
    godot = (s * (R @ xyz.T)).T + t                                 # COLMAP -> metric Godot world
    enu = np.stack([godot[:, 0], -godot[:, 2], godot[:, 1]], axis=1)  # Godot Y-up -> ENU Z-up
    centroid = enu.mean(axis=0)
    pos = (enu - centroid).astype(np.float32)

    # (4) write the tile + tileset.
    os.makedirs(args.out_dir, exist_ok=True)
    pnts_bytes = write_pnts(os.path.join(args.out_dir, "points.pnts"), pos, rgb)
    mn, mx = pos.min(axis=0), pos.max(axis=0)
    c, half = (mn + mx) / 2.0, (mx - mn) / 2.0
    diag = float(np.linalg.norm(mx - mn))
    tileset = {
        "asset": {"version": "1.0"},
        "geometricError": diag,
        "root": {
            "transform": enu_to_ecef_transform(args.lat, args.lon),
            "boundingVolume": {"box": [float(c[0]), float(c[1]), float(c[2]),
                                       float(half[0]), 0.0, 0.0, 0.0, float(half[1]), 0.0,
                                       0.0, 0.0, float(half[2])]},
            "geometricError": 0.0,
            "refine": "ADD",
            "content": {"uri": "points.pnts"},
        },
    }
    json.dump(tileset, open(os.path.join(args.out_dir, "tileset.json"), "w"), indent=2)
    print(f"ply_to_3dtiles: {pos.shape[0]} pts | Sim3 scale={s:.4f} | metric extent "
          f"{(mx - mn).round(2).tolist()} m | site ({args.lat:.4f},{args.lon:.4f}) | "
          f"pnts {pnts_bytes} B -> {args.out_dir}/tileset.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
