"""Build a STEWIE Godot terrain scene from the REAL Katwijk AHN 0.5 m DTM at ONE real RTK pose.

MILESTONE 1 of the "render the twin along the real Katwijk trajectory" build (ARGUS
articulation-parallax cue de-risking). This ingest:

  1. loads the Part4 RTK track (load_gps_real) and picks ONE fix (default index 50);
  2. anchors a LOCAL ENU frame at the FIRST RTK fix (== module LAT0/LON0 == the AHN
     sampler's native anchor == the declared start datum) via the RD/EPSG:28992 transform;
  3. crops a small square (default 40 m) of the AHN DTM centred on that pose and samples
     the REAL LiDAR height field (KatwijkAhnDem-style) into a base grid;
  4. injects that height grid via dart.dem_import.dem_to_base -> stewie.twin.io_fields.save_scene
     into a NEW scene dir, with world_bounds_m PINNED to the ENU frame so rover-rc and RTK
     share ONE frame (the round-trip that step 4 of the milestone verifies).

HONESTY LABEL (RENDERED-SENSOR SIMULATION -- ARGUS G2 evidence tier):
  The AHN DTM is 0.5 m/px. The REAL parts are the terrain MACRO-shape (national LiDAR DTM),
  the REAL RTK trajectory (ESA Katwijk 2015), and (at render time) the REAL EZ-RASSOR/IPEx
  8-camera rig geometry. ALL finer camera texture is PROCEDURAL infill in the Godot shader,
  NOT real Katwijk imagery. The mass_areal/density rasters are the dem_to_base datum-path
  bookkeeping (lunar-regolith injection defaults), NOT physical Katwijk beach soil -- only the
  heightmap is load-bearing here. Nothing produced by this pipeline is a real-image match.

FRAME NOTE (deliberate, evidence-based): the ENU frame is anchored at the FIRST RTK fix using
the SAME pyproj EPSG:4326->28992 transform KatwijkAhnDem uses internally, NOT
stewie.bridge.katwijk_io.gps_latlon_to_local_xy (which anchors at the track MEAN). Mixing a
mean-anchored pose with the first-fix-anchored AHN sampler would sample the DEM tens of metres
off the real pose. First-fix == start datum keeps pose and DEM in ONE exact frame.

Run:  /mnt/projects/stewie/code/.venv/bin/python benchmarks/katwijk/build_katwijk_scene.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt

ROOT = "/mnt/projects/stewie/code"
sys.path.insert(0, ROOT)

from dart.dem_import import Affine, dem_to_base  # noqa: E402
from stewie.bridge.katwijk_io import load_gps_real  # noqa: E402
from stewie.twin.io_fields import save_scene  # noqa: E402

# --- inputs (all REAL, on-disk) ------------------------------------------------------------
AHN = "/mnt/projects/datasets/katwijk/dem/katwijk_ahn_dtm_05m.tif"          # AHN 0.5 m DTM (EPSG:28992)
GPS = "/mnt/projects/datasets/katwijk/Part4/gps-latlong.txt"               # RTK ground truth
LAT0, LON0 = 52.217259107, 4.4034692045                                    # first Part4 fix == start datum
STATION = 50                                                               # the chosen RTK pose (0-based)
EXTENT_M = 40.0                                                            # square crop side (<< 100 m far-plane)
CELL_M = 0.5                                                               # base grid = native AHN resolution
GRAVITY_M_S2 = 9.80665                                                     # Katwijk = Earth (not exercised in a static render)
SCENE_NAME = "katwijk_part4_station50"
SCENE_DIR = os.path.join(ROOT, "out", "scenes", SCENE_NAME)


class KatwijkAhnDem:
    """AHN 0.5 m DTM sampler in the Katwijk local ENU frame anchored at (lat0,lon0) (RD/EPSG:28992).

    Reader PATTERN copied verbatim (attribution) from
    benchmarks/katwijk/run_katwijk_part4_dem.py:66-92 so this scene builder stays free of that
    module's heavy VO/torch imports. Bilinear-samples the real LiDAR height; sea/nodata filled by
    nearest land (distance_transform_edt), exactly as the source.
    """

    def __init__(self, tif: str, lat0: float, lon0: float) -> None:
        self.x0, self.y0 = Transformer.from_crs(
            "EPSG:4326", "EPSG:28992", always_xy=True).transform(lon0, lat0)
        with rasterio.open(tif) as ds:
            z = ds.read(1).astype(float)
            if ds.nodata is not None:
                z = np.where(z == ds.nodata, np.nan, z)
            self.tr = ds.transform
            self.h, self.w = z.shape
        m = ~np.isfinite(z)
        if m.any():
            z = z[tuple(distance_transform_edt(m, return_distances=False, return_indices=True))]
        self.z = z

    def _rc(self, e: float, n: float) -> tuple[float, float]:
        return (self.y0 + n - self.tr.f) / self.tr.e, (self.x0 + e - self.tr.c) / self.tr.a

    def height_enu(self, e: float, n: float) -> float:
        r, c = self._rc(float(e), float(n))
        r0 = int(np.clip(np.floor(r), 0, self.h - 2))
        c0 = int(np.clip(np.floor(c), 0, self.w - 2))
        fr, fc = r - r0, c - c0
        return float(self.z[r0, c0] * (1 - fr) * (1 - fc) + self.z[r0, c0 + 1] * (1 - fr) * fc
                     + self.z[r0 + 1, c0] * fr * (1 - fc) + self.z[r0 + 1, c0 + 1] * fr * fc)


def main() -> int:
    # 1. RTK track + chosen pose (ENU anchored at the FIRST fix via the SAME RD transform the DEM uses).
    gps = load_gps_real(GPS)
    if not (abs(gps[0]["lat"] - LAT0) < 1e-6 and abs(gps[0]["lon"] - LON0) < 1e-6):
        raise SystemExit(f"first RTK fix {gps[0]['lat']},{gps[0]['lon']} != LAT0/LON0 {LAT0},{LON0}")
    if STATION + 1 >= len(gps):
        raise SystemExit(f"need a next fix for heading; STATION={STATION} but only {len(gps)} fixes")

    to_rd = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True)
    rd0 = to_rd.transform(LON0, LAT0)                                   # RD of the start datum
    rd_p = to_rd.transform(gps[STATION]["lon"], gps[STATION]["lat"])    # RD of the chosen pose
    rd_n = to_rd.transform(gps[STATION + 1]["lon"], gps[STATION + 1]["lat"])  # RD of the next fix
    e_pose, n_pose = rd_p[0] - rd0[0], rd_p[1] - rd0[1]                 # ENU (east, north) of the pose
    e_next, n_next = rd_n[0] - rd0[0], rd_n[1] - rd0[1]
    heading_rad = float(np.arctan2(n_next - n_pose, e_next - e_pose))   # travel heading in ENU

    # 2. AHN sampler in the SAME (first-fix) ENU frame.
    dem = KatwijkAhnDem(AHN, LAT0, LON0)

    # 3. Crop square centred on the pose; pin world_bounds so the pose lands on an integer rover-rc.
    n = int(round(EXTENT_M / CELL_M))                                  # 80 cells
    half = n // 2                                                      # 40 -> rover-rc at grid centre
    x0 = e_pose - half * CELL_M                                        # world_bounds origin (ENU east)
    y0 = n_pose - half * CELL_M                                        # world_bounds origin (ENU north)
    rover_row, rover_col = half, half                                  # (N->row, E->col); worldZ=y0+row*cell

    # Build the base height grid: grid[row,col] = REAL AHN height at ENU (x0+col*cell, y0+row*cell).
    # Sampling per-cell at its ENU coord fixes orientation by construction (row -> +N/worldZ, col -> +E).
    Z = np.empty((n, n), dtype=np.float32)
    for row in range(n):
        nn = y0 + row * CELL_M
        for col in range(n):
            Z[row, col] = dem.height_enu(x0 + col * CELL_M, nn)

    # 4. Inject via the frozen datum path (heightmap round-trips to Z); affine is unused at base==px.
    cs = dem_to_base(Z, Affine(x0=float(x0), y0=float(y0), px=CELL_M), CELL_M)
    rt_err = float(np.max(np.abs(cs.derive_height() - Z.astype(np.float64))))

    x1, y1 = x0 + n * CELL_M, y0 + n * CELL_M
    hmin, hmax = float(Z.min()), float(Z.max())
    honesty = ("RENDERED-SENSOR SIMULATION (ARGUS G2 tier). Real: AHN 0.5 m LiDAR DTM macro-shape "
               "+ real Katwijk Part4 RTK pose + (at render) real EZ-RASSOR/IPEx 8-cam rig geometry. "
               "PROCEDURAL: all sub-0.5 m camera texture is Godot-shader infill, NOT real Katwijk "
               "imagery. mass_areal/density are dem_to_base datum-path defaults (lunar-regolith "
               "injection bookkeeping), NOT Katwijk beach soil; only heightmap is load-bearing. "
               "NOT a real-image match.")
    meta = {
        "schema_version": "1.0",
        "scene_name": SCENE_NAME,
        "producer": "benchmarks/katwijk/build_katwijk_scene.py (real AHN DTM -> dem_to_base -> save_scene)",
        "grid": {"width": n, "height": n, "cell_m": CELL_M, "order": "row-major-C"},
        "world_bounds_m": {"x0": round(x0, 6), "y0": round(y0, 6),
                           "x1": round(x1, 6), "y1": round(y1, 6)},
        "gravity_m_s2": GRAVITY_M_S2,
        "fields": {
            "heightmap": {"file": "heightmap.rf32", "dtype": "<f4", "units": "m"},
            "mass_areal": {"file": "mass_areal.rf32", "dtype": "<f4", "units": "kg/m^2"},
            "density": {"file": "density.rf32", "dtype": "<f4", "units": "kg/m^3"},
            "disturbance": {"file": "disturbance.rf32", "dtype": "<f4", "units": "1 (normalized)"},
            "state_label": {"file": "state_label.r8", "dtype": "u1",
                            "enum": ["VIRGIN", "TREAD", "EXCAVATED", "SPOIL",
                                     "COMPACTED_BERM", "SINTERED"]},
        },
        "ice_present": False,
        "height_range_m": [round(hmin, 5), round(hmax, 5)],
        "clasts": [],
        "active_zone": {"min_rc": [0, 0], "max_rc": [n, n]},
        "quadtree": [{"level": 0, "row0": 0, "col0": 0, "size": n, "label": "ROOT"}],
        "rover_rc": [rover_row, rover_col],
        "dem_provenance": {
            "source": "AHN 0.5 m national LiDAR DTM (Katwijk), " + AHN,
            "crs": "EPSG:28992 (RD New)",
            "native_cell_m": 0.5,
            "enu_anchor": {"lat": LAT0, "lon": LON0, "note": "first Part4 RTK fix = declared start datum"},
            "rtk_source": GPS,
            "station_index": STATION,
            "pose_enu_m": {"east": round(e_pose, 6), "north": round(n_pose, 6)},
            "heading_rad": round(heading_rad, 6),
        },
        "honesty": honesty,
        "notes": ("Real AHN DTM crop (" + f"{EXTENT_M:.0f} m @ {CELL_M} m" + ") centred on Katwijk Part4 "
                  f"RTK station {STATION}; world_bounds_m pinned to the first-fix ENU frame so rover-rc "
                  "and RTK share ONE frame. " + honesty),
    }
    save_scene(SCENE_DIR, cs.fields_dict(), meta)

    # Honesty README beside the scene (label required in every artifact).
    with open(os.path.join(SCENE_DIR, "README.md"), "w") as fh:
        fh.write("# " + SCENE_NAME + "\n\n" + honesty + "\n\n"
                 f"- Built by `benchmarks/katwijk/build_katwijk_scene.py`\n"
                 f"- AHN DTM: `{AHN}` (EPSG:28992, 0.5 m/px)\n"
                 f"- RTK pose: Part4 station {STATION}, ENU east={e_pose:.3f} north={n_pose:.3f} m "
                 f"(anchor = first fix {LAT0},{LON0})\n"
                 f"- Grid {n}x{n} @ {CELL_M} m; rover-rc (row,col)=({rover_row},{rover_col}) at the pose\n")

    # Provenance for the round-trip check (step 4).
    prov = {"scene_dir": SCENE_DIR, "scene_name": SCENE_NAME,
            "pose_enu_m": [e_pose, n_pose], "heading_rad": heading_rad,
            "world_bounds_m": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
            "grid": {"width": n, "height": n, "cell_m": CELL_M},
            "rover_rc": [rover_row, rover_col],
            "expected_position_xz_m": [x0 + rover_col * CELL_M, y0 + rover_row * CELL_M]}
    with open(os.path.join(SCENE_DIR, "_build_provenance.json"), "w") as fh:
        json.dump(prov, fh, indent=2)

    # Verify the 6 scene files exist + report.
    need = ["heightmap.rf32", "mass_areal.rf32", "density.rf32", "disturbance.rf32",
            "state_label.r8", "metadata.json"]
    sizes = {f: os.path.getsize(os.path.join(SCENE_DIR, f)) for f in need}
    missing = [f for f, s in sizes.items() if s == 0]
    print(f"[build] scene_dir = {SCENE_DIR}")
    print(f"[build] grid {n}x{n} @ {CELL_M} m  world_bounds x0={x0:.3f} y0={y0:.3f} x1={x1:.3f} y1={y1:.3f}")
    print(f"[build] pose ENU east={e_pose:.4f} north={n_pose:.4f} m  heading={np.degrees(heading_rad):.1f} deg")
    print(f"[build] rover-rc (row,col)=({rover_row},{rover_col})  expected worldXZ="
          f"({x0 + rover_col*CELL_M:.6f},{y0 + rover_row*CELL_M:.6f})")
    print(f"[build] height range {hmin:.3f}..{hmax:.3f} m  datum-path round-trip max|err|={rt_err:.2e} m")
    for f in need:
        print(f"[build]   {f:18s} {sizes[f]:>10d} bytes")
    if missing:
        raise SystemExit(f"[build] FAIL: empty/missing scene files: {missing}")
    print("[build] OK: all 6 scene files present + non-empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
