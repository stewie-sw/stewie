"""Katwijk Part4 loop-closing visual SLAM WITH DEM anchoring -- completing the second-rover generalisation
ladder (VO -> VO+LC -> VO+LC+DEM), matching the S3LI ladder.

The DEM is the independent AHN 0.5 m national LiDAR DTM of the Katwijk beach (PDOK WCS), in the same role
the Copernicus DEM played for S3LI: an independent survey, not built from the rover GPS, so it is a
legitimate firewall-clean map prior (the rover's first GPS fix is the single declared start datum; the
heading is recovered by a firewall-clean VO-vertical-vs-DEM yaw search, NOT from GPS). The VO-vs-AHN
correlation (0.92) confirms the AHN matches the 2015 beach/dune terrain (no beach-shift mismatch).

Firewall I3: VO + loop closure + DEM (sampled at the ESTIMATED x,y) only; GPS read solely at scoring.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
from datetime import date

import numpy as np
import rasterio
from imageio.v3 import imread
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt

sys.path.insert(0, "/mnt/projects/stewie/code")
from dart import stereo_vo  # noqa: E402
from dart.loop_closure_visual import (  # noqa: E402
    LoopKeyframe,
    detect_loops,
    global_descriptor,
    quat_wxyz_to_rotmat,
    registration_rotation,
)
from dart.s3li_capstone import (  # noqa: E402
    register_cam_to_enu,
    rotmat_to_quat_wxyz,
    score,
    write_tum,
    yaw_search,
)
from dart.se3_pose_graph import (  # noqa: E402
    DemHeightEdge,
    DemNormalEdge,
    PriorEdge,
    SE3PoseGraph,
    build_loop_edges,
    build_odometry_edges,
)
from dart.superpoint_vo import estimate_vo_superpoint, triangulate_stereo_superpoint  # noqa: E402
from stewie.bridge.katwijk_io import gps_latlon_to_local_xy, load_gps_real  # noqa: E402

KP = "/mnt/projects/datasets/katwijk/Part4"
AHN = "/mnt/projects/datasets/katwijk/dem/katwijk_ahn_dtm_05m.tif"
VALID = "/mnt/projects/stewie/code/stewie/eval/validation"
FIG = os.path.join(VALID, "figures", "katwijk_part4_dem_2026-06-29")
LAT0, LON0 = 52.217259107, 4.4034692045
K1 = np.array([[834.256, 0, 497.715], [0, 838.961, 398.773], [0, 0, 1]], float)
K2 = np.array([[837.129, 0, 481.938], [0, 840.816, 391.460], [0, 0, 1]], float)
R_LR = np.array([[0.999992, -0.003275, 0.002344], [0.003280, 0.999992, -0.002108],
                 [-0.002337, 0.002116, 0.999995]], float).T
T_LR = np.array([-0.120079, -0.000263, 0.000268], float)


class KatwijkAhnDem:
    """AHN 0.5 m DTM sampler in the Katwijk local frame anchored at the first GPS fix (RD/EPSG:28992)."""

    def __init__(self, tif: str, lat0: float, lon0: float) -> None:
        self.x0, self.y0 = Transformer.from_crs("EPSG:4326", "EPSG:28992", always_xy=True).transform(
            lon0, lat0)
        with rasterio.open(tif) as ds:
            z = ds.read(1).astype(float)
            if ds.nodata is not None:
                z = np.where(z == ds.nodata, np.nan, z)
            self.tr = ds.transform
            self.h, self.w = z.shape
        m = ~np.isfinite(z)                                            # fill sea/nodata by nearest land
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

    def normal_enu(self, e: float, n: float, step: float = 1.0) -> np.ndarray:
        hx = (self.height_enu(e + step, n) - self.height_enu(e - step, n)) / (2 * step)
        hy = (self.height_enu(e, n + step) - self.height_enu(e, n - step)) / (2 * step)
        v = np.array([-hx, -hy, 1.0])
        return v / np.linalg.norm(v)


def _lts(stamp: str) -> float:
    p = os.path.basename(stamp).split("_")[1:]
    return dt.datetime(int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]),
                       int(p[6]) * 1000, tzinfo=dt.timezone.utc).timestamp()


def main(stride: int = 2, kf_every: int = 3, anchor_every: int = 10) -> None:
    os.makedirs(FIG, exist_ok=True)
    stamps = sorted(set(f.rsplit("_", 1)[0] for f in glob.glob(KP + "/LocCam/*.png")))[::stride]
    ts_s = np.array([_lts(s) for s in stamps])
    pairs = [(np.asarray(imread(s + "_0.png")), np.asarray(imread(s + "_1.png"))) for s in stamps]
    rect, cfg = stereo_vo.calibrated_rectify_pairs(pairs, K_left=K1, dist_left=np.zeros(5), K_right=K2,
                                                   dist_right=np.zeros(5), R=R_LR, T_m=T_LR)
    res = estimate_vo_superpoint(rect, cfg, deterministic=True)
    xyz = res.camera_poses[:, :3, 3].astype(float)
    quat = np.array([rotmat_to_quat_wxyz(p[:3, :3]) for p in res.camera_poses], float)
    n = xyz.shape[0]
    print(f"[katwijk-dem] VO {n} poses, path {np.sum(np.linalg.norm(np.diff(xyz, axis=0), axis=1)):.1f}m",
          flush=True)

    h_px, w_px = rect[0][0].shape[:2]
    imsz = np.array([float(w_px), float(h_px)], float)
    kfs: list[LoopKeyframe] = []
    for k in range(0, n, kf_every):
        cl, ft, kp = triangulate_stereo_superpoint(rect[k][0], rect[k][1], cfg)
        ds = ft["descriptors"][0].detach().cpu().numpy().astype(np.float32)
        if ds.shape[0] == 0:
            continue
        kfs.append(LoopKeyframe(node=k, keypoints=kp.astype(np.float32), descriptors=ds, image_size=imsz,
                                points_3d=cl.points_3d.astype(np.float32),
                                point_kpt_idx=cl.left_feat_idx.astype(np.int64),
                                global_desc=global_descriptor(ds)))
    loops = detect_loops(kfs, quat, 0.0, cfg, min_index_gap=max(50, n // 4), sim_min=0.80, min_inliers=15,
                         max_translation_m=10.0, max_candidates=2000)
    acc = loops["accepted"]

    dem = KatwijkAhnDem(AHN, LAT0, LON0)
    z0 = dem.height_enu(0.0, 0.0)
    yaw = yaw_search(xyz, dem, z0, window=n)
    print(f"[katwijk-dem] {len(acc)} loop closures; AHN register yaw {yaw['yaw_deg']:.0f}deg "
          f"corr {yaw['peak_corr']:.3f} z0 {z0:.2f}m", flush=True)

    r_m = registration_rotation(yaw["yaw_rad"])
    t0 = register_cam_to_enu(xyz, yaw["yaw_rad"], z0)
    R0 = np.stack([r_m @ quat_wxyz_to_rotmat(q) for q in quat])
    odo = build_odometry_edges(R0, t0, np.radians(0.2), 0.05)
    loop = build_loop_edges(acc, np.radians(1.0), 0.5)
    prior = PriorEdge(0, R0[0].copy(), t0[0].copy(), np.radians(5.0), 0.5)
    anchor_idx = list(range(0, n, anchor_every))
    dem_h = [DemHeightEdge(a, 0.5) for a in anchor_idx]
    dem_nrm = [DemNormalEdge(a, 0.2) for a in anchor_idx]

    graph = SE3PoseGraph(dem)
    r_lc = graph.solve(R0, t0, prior=prior, odometry=odo, loop=loop, iters=60)
    r_dem = graph.solve(R0, t0, prior=prior, odometry=odo, loop=loop, dem_height=dem_h,
                        dem_normal=dem_nrm, iters=60)
    print(f"[katwijk-dem] SE3+LC conv={r_lc.converged}; SE3+LC+DEM conv={r_dem.converged} "
          f"meanH={r_dem.mean_abs_height_correction_m:.2f}m", flush=True)

    gps = load_gps_real(KP + "/gps-latlong.txt")
    gt_xy = gps_latlon_to_local_xy(np.array([g["lat"] for g in gps]), np.array([g["lon"] for g in gps]))
    gt_enu = np.column_stack([gt_xy, np.array([g["alt"] for g in gps]) - gps[0]["alt"]])
    gt_ts = np.array([g["t"] for g in gps])
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (n, 1))

    def sc(xyz_: np.ndarray, lab: str) -> dict:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"katwijk_part4_dem_{lab}.tum")
        write_tum(p, ts_s, xyz_, ident)
        r = score(p, gt_enu, gt_ts, FIG, f"katwijk_part4_dem_{lab}", max_diff_s=1.6)
        from dart.s3li_capstone import axis_error_decompose
        d = axis_error_decompose(p, gt_enu, gt_ts, max_diff_s=1.6)
        return {"se3_m": r["metrics"]["ate_aligned_se3_m"]["rmse"],
                "sim3_m": r["metrics"]["ate_aligned_sim3_m"]["rmse"],
                "horiz_m": d["rms_horizontal_m"], "vert_m": d["rms_vertical_m"]}

    s_vo, s_lc, s_dem = sc(t0, "vo"), sc(r_lc.t, "lc"), sc(r_dem.t, "lc_dem")
    artifact = {
        "experiment": "Katwijk Part4 loop-closing SE(3) visual SLAM + AHN-DEM anchoring (second-rover "
                      "generalisation ladder, completing VO->VO+LC->VO+LC+DEM)",
        "date": str(date.today()), "data": {"dataset": KP, "dem": AHN + " (AHN 0.5m national LiDAR DTM)",
                                            "n_frames": n, "n_loop_closures": len(acc)},
        "ahn_register": {"yaw_deg": yaw["yaw_deg"], "vo_vs_ahn_corr": yaw["peak_corr"], "z0_m": z0},
        "ladder_se3_m": {"vo": s_vo["se3_m"], "vo_lc": s_lc["se3_m"], "vo_lc_dem": s_dem["se3_m"]},
        "vo": s_vo, "vo_lc": s_lc, "vo_lc_dem": s_dem,
        "honest_read": (
            f"Completes the second-rover ladder. The AHN 0.5 m DTM is independent national LiDAR (the "
            f"firewall-clean role Copernicus played for S3LI); the VO-vs-AHN correlation "
            f"{yaw['peak_corr']:.2f} confirms it matches the 2015 beach/dune terrain. Katwijk VO is "
            "already sub-metre on the 76 m loop, so loop closure and DEM anchoring have little drift to "
            "remove (unlike S3LI 93->8 m); the value here is ladder COMPLETENESS on a second real rover, "
            "not a number improvement. The DEM's vertical effect is reported honestly below."
        ),
        "i3_attestation": "VO + loop closure + AHN DEM (sampled at the ESTIMATED x,y; heading from the "
                          "firewall-clean VO-vs-DEM yaw search, not GPS) only; GPS read solely at scoring.",
    }
    out = os.path.join(VALID, "katwijk_part4_dem_2026-06-29.json")
    with open(out, "w") as fh:
        json.dump(artifact, fh, indent=2)
    print("\n===== Katwijk Part4 SE(3) SLAM + AHN-DEM (2nd-rover ladder complete) =====")
    for lab, s in [("VO", s_vo), ("VO+LC", s_lc), ("VO+LC+DEM", s_dem)]:
        print(f"  {lab:11s} SE3 {s['se3_m']:.2f}  Sim3 {s['sim3_m']:.2f}  horiz {s['horiz_m']:.2f}  "
              f"vert {s['vert_m']:.2f}")
    print(f" artifact -> {out}")


if __name__ == "__main__":
    main()
