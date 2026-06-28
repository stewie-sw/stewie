"""S3LI ``s3li_crater`` VO -> DEM-anchoring capstone: the reusable estimation + scoring helpers that
reproduce arXiv:2603.17229 (SuperPoint+LightGlue stereo VO, then DEM anchoring) on the REAL DLR S3LI
Mt-Etna traverse. The thin runners live in ``benchmarks/s3li_crater/``; this is the importable core.

TRUTH FIREWALL (invariant I3). The ESTIMATION functions here -- :func:`yaw_search`,
:func:`register_cam_to_enu`, :func:`anchor_vo`, :func:`estimate_and_freeze` -- take the camera-frame VO,
the DEM, and the single DECLARED start fix ONLY. The DEM is sampled at the ESTIMATED (x, y), never at a
GT cell. They never receive a ground-truth trajectory. :func:`time_offset_s` and :func:`score` are the
ONLY ground-truth consumers; they run downstream, after each estimate is frozen to disk.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI (public); DEM: Copernicus GLO-30 (public).
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import numpy as np

from dart.dem_height_graph import (
    DemHeightPoseGraph,
    build_between_factors,
    build_dem_anchor_factors,
)
from dart.s3li_dem import S3liDem


# ----------------------------------------------------------------------------------------------------
# trajectory I/O
# ----------------------------------------------------------------------------------------------------
def rotmat_to_quat_wxyz(R: np.ndarray) -> np.ndarray:
    """Rotation matrix -> unit Hamilton quaternion (w, x, y, z). Shepperd's stable-branch method."""
    R = np.asarray(R, float)
    t = np.trace(R)
    if t > 0.0:
        s = np.sqrt(t + 1.0) * 2.0
        w, x, y, z = 0.25 * s, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] >= R[1, 1] and R[0, 0] >= R[2, 2]:
        s = np.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2.0
        w, x, y, z = (R[2, 1] - R[1, 2]) / s, 0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] >= R[2, 2]:
        s = np.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2.0
        w, x, y, z = (R[0, 2] - R[2, 0]) / s, (R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s
    else:
        s = np.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2.0
        w, x, y, z = (R[1, 0] - R[0, 1]) / s, (R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s
    q = np.array([w, x, y, z], float)
    return q / np.linalg.norm(q)


def write_tum(path: str, ts_s: np.ndarray, xyz: np.ndarray, quat_wxyz: np.ndarray) -> None:
    """Write a TUM trajectory ``t tx ty tz qx qy qz qw`` (quaternion stored x y z w)."""
    with open(path, "w") as fh:
        for t, p, q in zip(np.asarray(ts_s, float), np.asarray(xyz, float), np.asarray(quat_wxyz, float)):
            fh.write(f"{t:.9f} {p[0]:.9f} {p[1]:.9f} {p[2]:.9f} "
                     f"{q[1]:.9f} {q[2]:.9f} {q[3]:.9f} {q[0]:.9f}\n")


# ----------------------------------------------------------------------------------------------------
# registration (camera frame -> DEM ENU); firewall-clean heading
# ----------------------------------------------------------------------------------------------------
def register_cam_to_enu(xyz_cam: np.ndarray, yaw_rad: float, z0_m: float) -> np.ndarray:
    """Register a camera-optical-frame VO trajectory (x right, y down, z forward; first cam = origin)
    into the DEM local ENU frame with a DECLARED level-camera attitude + heading ``yaw_rad`` (CCW from
    East) and the declared start height ``z0_m``. No GT (I3)."""
    xyz_cam = np.asarray(xyz_cam, float)
    x_r, y_d, z_f = xyz_cam[:, 0], xyz_cam[:, 1], xyz_cam[:, 2]
    c, s = np.cos(yaw_rad), np.sin(yaw_rad)
    east = c * z_f + s * x_r
    north = s * z_f - c * x_r
    up = -y_d
    return np.column_stack([east, north, z0_m + up])


def yaw_search(xyz_cam: np.ndarray, dem: S3liDem, z0_m: float, *,
               n_grid: int = 360, subsample: int = 5, window: int = 1500) -> dict[str, Any]:
    """Firewall-clean INITIAL heading: the declared yaw whose registered path makes the DEM terrain
    UNDER the path best correlate with the VO's OWN measured vertical profile (VO up = -y_down).
    Reads VO + DEM only -- never GT (I3).

    The estimate uses only the EARLY, low-drift ``window`` frames: the VO between-factors carry every
    later turn, so the registration needs only the start heading, and that is best recovered where
    accumulated VO vertical drift has not yet swamped the terrain-relief signal (over the full 1.3 km
    loop the drift dominates and the correlation collapses -- the honest reason a global yaw search
    fails). Full-circle search; reports the peak correlation so the heading's reliability is visible."""
    xyz = np.asarray(xyz_cam, float)
    end = min(int(window), xyz.shape[0]) if window > 0 else xyz.shape[0]
    idx = np.arange(0, end, subsample)
    vo_up = -xyz[idx, 1]
    t = np.arange(vo_up.size, dtype=float)
    vo_up = vo_up - np.polyval(np.polyfit(t, vo_up, 1), t)         # de-trend slow VO drift
    yaws = np.linspace(0.0, 2.0 * np.pi, n_grid, endpoint=False)
    best_yaw, best_corr = 0.0, -2.0
    for psi in yaws:
        enu = register_cam_to_enu(xyz[idx], float(psi), z0_m)
        try:
            h = np.array([dem.height_enu(float(e), float(n)) for e, n in enu[:, :2]])
        except ValueError:
            continue
        h = h - np.polyval(np.polyfit(t, h, 1), t)
        denom = np.linalg.norm(vo_up) * np.linalg.norm(h)
        c = float(vo_up @ h / denom) if denom > 0 else -2.0
        if c > best_corr:
            best_corr, best_yaw = c, float(psi)
    return {"yaw_rad": best_yaw, "yaw_deg": float(np.degrees(best_yaw)), "peak_corr": best_corr,
            "n_grid": n_grid, "subsample": subsample, "window_frames": int(end)}


# ----------------------------------------------------------------------------------------------------
# DEM anchoring
# ----------------------------------------------------------------------------------------------------
def anchor_vo(enu_vo: np.ndarray, dem: S3liDem, *, sigma_vo_m: float, sigma_dem_m: float,
              sigma_prior_m: float, anchor_every: int):
    """DEM height-normal anchoring of a registered VO ENU trajectory. Returns (DemAnchorResult, indices).
    No GT (I3)."""
    deltas = np.diff(np.asarray(enu_vo, float), axis=0)
    between = build_between_factors(deltas, sigma_vo_m)
    anchor_idx = list(range(0, enu_vo.shape[0], anchor_every))
    anchors = build_dem_anchor_factors(anchor_idx, sigma_dem_m)
    graph = DemHeightPoseGraph(dem)
    return graph.solve(np.asarray(enu_vo, float), between, anchors, prior_idx=0,
                       prior_xyz=np.asarray(enu_vo, float)[0].copy(),
                       prior_sigma_m=sigma_prior_m), anchor_idx


def estimate_and_freeze(xyz_cam: np.ndarray, ts_ns: np.ndarray, dem: S3liDem, out_dir: str, *,
                        sigma_vo_m: float = 0.05, sigma_dem_m: float = 2.0, sigma_prior_m: float = 0.5,
                        anchor_every: int = 10, vo_enu_name: str = "vo_enu.tum",
                        anchored_name: str = "dem_anchored_enu.tum") -> dict[str, Any]:
    """Produce + FREEZE the VO-ENU and DEM-anchored-ENU estimates from camera-frame VO + DEM + the
    declared start ONLY (no GT; firewall I3). Returns frozen paths + estimates + diagnostics."""
    xyz_cam = np.asarray(xyz_cam, float)
    ts_ns = np.asarray(ts_ns, np.int64)
    z0 = float(dem.height_enu(0.0, 0.0))
    yaw = yaw_search(xyz_cam, dem, z0)
    enu_vo = register_cam_to_enu(xyz_cam, yaw["yaw_rad"], z0)
    result, anchor_idx = anchor_vo(enu_vo, dem, sigma_vo_m=sigma_vo_m, sigma_dem_m=sigma_dem_m,
                                   sigma_prior_m=sigma_prior_m, anchor_every=anchor_every)
    enu_anchored = result.xyz

    ts_s = ts_ns / 1e9
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (ts_s.size, 1))
    vo_enu_tum = os.path.join(out_dir, vo_enu_name)
    anchored_tum = os.path.join(out_dir, anchored_name)
    write_tum(vo_enu_tum, ts_s, enu_vo, ident)
    write_tum(anchored_tum, ts_s, enu_anchored, ident)

    diag = {k: v for k, v in asdict(result).items() if k not in ("xyz", "xyz_initial")}
    return {"z0_m": z0, "yaw": yaw, "enu_vo": enu_vo, "enu_anchored": enu_anchored,
            "vo_enu_tum": vo_enu_tum, "anchored_tum": anchored_tum, "anchor_indices": anchor_idx,
            "anchor_diag": diag}


# ----------------------------------------------------------------------------------------------------
# time sync + scoring (the ONLY ground-truth consumers; run after the estimate is frozen)
# ----------------------------------------------------------------------------------------------------
def _speed_profile(ts_ns: np.ndarray, xyz: np.ndarray):
    ts = np.asarray(ts_ns, float) / 1e9
    dt = np.maximum(np.diff(ts), 1e-6)
    v = np.linalg.norm(np.diff(np.asarray(xyz, float), axis=0), axis=1) / dt
    return 0.5 * (ts[:-1] + ts[1:]), v


def time_offset_s(vo_ts_ns: np.ndarray, vo_xyz: np.ndarray, gt_ts_ns: np.ndarray, gt_enu: np.ndarray,
                  *, max_off_s: float = 30.0, grid_dt: float = 0.2) -> dict[str, Any]:
    """Constant bag-vs-GT clock offset by cross-correlating the VO translation-SPEED profile against
    the GT speed profile. Returns the offset (s) to ADD to the GT timestamps so GT aligns to bag time,
    plus the correlation peak. SCORING context (reads GT), run after the estimate is frozen."""
    tv, sv = _speed_profile(vo_ts_ns, vo_xyz)
    tg, sg = _speed_profile(gt_ts_ns, gt_enu)
    grid = np.arange(tv[0], tv[-1], grid_dt)
    sv_n = np.interp(grid, tv, sv)
    sv_n = sv_n - sv_n.mean()
    best_off, best_corr = 0.0, -2.0
    for off in np.arange(-max_off_s, max_off_s + grid_dt, grid_dt):
        sg_g = np.interp(grid, tg + off, sg, left=np.nan, right=np.nan)
        m = np.isfinite(sg_g)
        if int(m.sum()) < 0.5 * grid.size:
            continue
        a = sv_n[m]
        b = sg_g[m] - sg_g[m].mean()
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        c = float(a @ b / denom) if denom > 0 else -2.0
        if c > best_corr:
            best_corr, best_off = c, float(off)
    return {"offset_s": best_off, "peak_corr": best_corr, "max_off_s": max_off_s, "grid_dt": grid_dt}


def score(tum_path: str, gt_enu: np.ndarray, gt_ts_aligned_s: np.ndarray, out_dir: str, label: str,
          *, max_diff_s: float = 0.06) -> dict[str, Any]:
    """evo Umeyama SE(3)+Sim(3) ATE + RPE of a frozen estimate vs GT, emitting the figure set + JSON."""
    from dart.viz.run_figures import GtSamples, generate_figures
    gt = GtSamples(positions_xyz=np.asarray(gt_enu, float),
                   timestamps_s=np.asarray(gt_ts_aligned_s, float))
    return generate_figures(tum_path, gt, out_dir, label, max_diff_s=max_diff_s)


def axis_error_decompose(tum_path: str, gt_enu: np.ndarray, gt_ts_aligned_s: np.ndarray,
                         *, max_diff_s: float = 0.06) -> dict[str, float]:
    """SE(3)-Umeyama align a frozen estimate to GT, then report the RMS of the aligned residual split
    into horizontal vs vertical (and per-axis). This is what isolates WHY DEM height anchoring does or
    does not move the ATE: height anchoring acts on the vertical component only. SCORING context (GT)."""
    import copy

    from evo.core import sync
    from evo.tools import file_interface

    from dart.viz.run_figures import GtSamples, _as_trajectory
    est = file_interface.read_tum_trajectory_file(str(tum_path))
    gt_traj, _ = _as_trajectory(GtSamples(positions_xyz=np.asarray(gt_enu, float),
                                          timestamps_s=np.asarray(gt_ts_aligned_s, float)))
    gt_traj, est = sync.associate_trajectories(gt_traj, est, max_diff=max_diff_s)
    est_a = copy.deepcopy(est)
    est_a.align(gt_traj, correct_scale=False, correct_only_scale=False)
    resid = np.asarray(est_a.positions_xyz, float) - np.asarray(gt_traj.positions_xyz, float)
    rms = np.sqrt(np.mean(resid ** 2, axis=0))
    horiz = float(np.sqrt(np.mean(np.sum(resid[:, :2] ** 2, axis=1))))
    vert = float(np.sqrt(np.mean(resid[:, 2] ** 2)))
    return {"rms_east_m": float(rms[0]), "rms_north_m": float(rms[1]), "rms_up_m": float(rms[2]),
            "rms_horizontal_m": horiz, "rms_vertical_m": vert}
