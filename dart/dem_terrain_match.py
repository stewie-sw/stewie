"""Horizontal DEM terrain-correlation anchor for the S3LI ``s3li_crater`` stereo-VIO traverse.

THE PROBLEM THIS FIXES. On the real DLR S3LI Etna traverse the gyro-fused stereo-VIO trajectory still
drifts ~78 m, and the residual is HORIZONTAL-dominated (~78 m horizontal vs ~16 m vertical): the gyro
tamed the heading, so what remains is stereo-VO TRANSLATION / SCALE drift (Sim3 scale ~0.95-1.04 over
1.3 km). DEM *height-normal* anchoring acts on the vertical and cannot recover a horizontal error -- in
fact it makes it worse, because a wrong (x, y) makes the DEM sample the wrong terrain. The fix is an
ABSOLUTE HORIZONTAL position constraint: match the rover's own locally-observed terrain elevation to
the independent global DEM (terrain-relative navigation / terrain contour matching).

THE METHOD (per sliding window along the VIO trajectory):

  1. Accumulate the per-frame stereo 3-D points (transformed by the ESTIMATED VIO camera poses) into a
     local 2.5-D elevation patch in the DEM ENU frame. The S3LI stereo sees terrain within a few metres
     of the camera, so a window sweeps out a thin terrain ribbon along the rover's path.
  2. Downsample the patch to ~DEM scale (grid the points into cells, one mean elevation per cell) -- the
     metre-scale stereo detail is far below the 30 m DEM posting, so only the large-scale relief trend
     can register.
  3. Search over a horizontal shift ``(dx, dy)`` for the offset that maximises the de-meaned elevation
     cross-correlation between the local cells and the DEM sampled at the shifted cell centres. The peak
     gives an absolute (E, N) fix for the window; the peak correlation + its sharpness are the
     confidence. Flat / ambiguous / boundary-pinned windows are REJECTED.

RESOLUTION CEILING (reported honestly, not hidden). The DEM is Copernicus GLO-30 (~30 m) over a
245 x 309 m traverse (~10 cells). That caps the horizontal-match precision at roughly 15-30 m; the
strong crater relief (~66 m) is the matchable signal. A paper-level (sub-10 m) fix would need a
higher-resolution DEM.

TRUTH FIREWALL (invariant I3). Registration reads ONLY the estimated terrain (stereo points at the
ESTIMATED VIO poses) and the DEM prior, sampled at the ESTIMATED (shifted) cell centres. It NEVER
compares to a ground-truth position. The shift is found by terrain correlation, not by knowing where
the rover truly was. GT enters only downstream at scoring, after the anchored estimate is frozen.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey). Data: DLR S3LI s3li_crater (public); DEM: Copernicus
# GLO-30 (public). No ground truth enters any function here.
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


class DemHeightSampler(Protocol):
    """The DEM interface the terrain match needs (satisfied by :class:`dart.s3li_dem.S3liDem`)."""

    def heights_enu(self, east_m: np.ndarray, north_m: np.ndarray) -> np.ndarray: ...


@dataclass(frozen=True)
class DemXyFix:
    """One window's horizontal terrain-correlation result (firewall-clean; no GT).

    ``keyframe`` is the anchored node (the window centre); ``enu_xy`` (2,) is the absolute (E, N) fix =
    the node's estimated (E, N) plus the registered shift; ``shift_m`` (2,) is the ``(dx, dy)`` that
    maximised the elevation cross-correlation; ``corr`` is the peak correlation (the match quality);
    ``margin`` is the peak prominence over the best COMPETING peak far from it (the ambiguity guard --
    low margin = another terrain feature matches comparably, so the fix is unreliable); ``sigma_m`` is
    the fix's horizontal 1-sigma, derived from the correlation-peak BREADTH and floored at the DEM
    resolution ceiling (a smooth 30 m DEM gives an honestly broad, ~15-30 m peak); ``relief_std_m`` is
    the std of the de-meaned local cell elevations (the matchable signal); ``n_cells`` / ``n_points``
    size the patch; ``on_boundary`` flags a shift pinned to the search edge; ``accepted`` +
    ``reject_reason`` record the gate decision."""

    keyframe: int
    enu_xy: np.ndarray
    shift_m: np.ndarray
    corr: float
    margin: float
    sigma_m: float
    relief_std_m: float
    n_cells: int
    n_points: int
    on_boundary: bool
    accepted: bool
    reject_reason: str

    def to_json(self) -> dict[str, object]:
        return {
            "keyframe": int(self.keyframe),
            "enu_xy_m": [float(self.enu_xy[0]), float(self.enu_xy[1])],
            "shift_m": [float(self.shift_m[0]), float(self.shift_m[1])],
            "shift_norm_m": float(np.hypot(self.shift_m[0], self.shift_m[1])),
            "corr": float(self.corr),
            "margin": float(self.margin),
            "sigma_m": float(self.sigma_m),
            "relief_std_m": float(self.relief_std_m),
            "n_cells": int(self.n_cells),
            "n_points": int(self.n_points),
            "on_boundary": bool(self.on_boundary),
            "accepted": bool(self.accepted),
            "reject_reason": self.reject_reason,
        }


def transform_cloud_to_enu(
    points_cam: np.ndarray, r_enu_cam: np.ndarray, enu_pos: np.ndarray
) -> np.ndarray:
    """Map a frame's camera-optical stereo points (M,3) into the DEM ENU frame:
    ``p_enu = R_enu_cam @ p_cam + enu_pos``."""
    p = np.asarray(points_cam, float)
    if p.size == 0:
        return np.empty((0, 3))
    return (np.asarray(r_enu_cam, float) @ p.T).T + np.asarray(enu_pos, float)


def grid_patch(
    points_enu: np.ndarray, grid_m: float, *, min_pts_per_cell: int = 4
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Downsample a local elevation patch to ~DEM scale: snap ENU points to a ``grid_m`` grid and take
    the MEDIAN ``up`` per occupied cell (median = robust to the few far/noisy stereo points). Returns
    ``(cell_centres (C,2) ENU, cell_heights (C,), cell_counts (C,))`` for cells with >= min_pts_per_cell
    points. Cells with too few points are dropped (no fabricated elevation)."""
    p = np.asarray(points_enu, float)
    if p.shape[0] == 0:
        return np.empty((0, 2)), np.empty(0), np.empty(0, dtype=int)
    g = float(grid_m)
    keys = np.floor(p[:, :2] / g).astype(np.int64)
    # unique cell ids; group heights by cell
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    centres = (uniq.astype(float) + 0.5) * g
    heights = np.empty(uniq.shape[0])
    counts = np.zeros(uniq.shape[0], dtype=int)
    for c in range(uniq.shape[0]):
        sel = inv == c
        counts[c] = int(sel.sum())
        heights[c] = float(np.median(p[sel, 2]))
    keep = counts >= int(min_pts_per_cell)
    return centres[keep], heights[keep], counts[keep]


@dataclass(frozen=True)
class _RegResult:
    shift_m: np.ndarray
    corr: float
    margin: float
    sigma_m: float
    on_boundary: bool


def register_patch_xy(
    cell_centres: np.ndarray, cell_heights: np.ndarray, dem: DemHeightSampler,
    *, search_radius_m: float = 60.0, search_step_m: float = 3.0,
    ambig_dist_m: float = 40.0, sigma_floor_m: float = 12.0, sigma_ceiling_m: float = 35.0,
) -> _RegResult:
    """Find the horizontal shift ``(dx, dy)`` that best aligns the local elevation patch to the DEM.

    For each candidate shift on a ``+/- search_radius_m`` grid, sample the DEM at the shifted cell
    centres and take the Pearson correlation of the DE-MEANED local cell elevations against the
    DE-MEANED DEM elevations. The de-meaning cancels the (unknown, drifting) absolute height and the
    EGM2008-vs-ellipsoidal datum offset, so only RELIEF SHAPE is matched.

    Confidence (firewall-clean -- all from the correlation surface, never GT):
      * ``corr``   the peak correlation (match quality).
      * ``margin`` the peak minus the best COMPETING peak more than ``ambig_dist_m`` away (the
        ambiguity guard: a small margin means a different terrain feature matches comparably).
      * ``sigma_m`` the fix 1-sigma from the BREADTH of the high-correlation blob (shifts within 0.05
        of the peak), floored at the DEM resolution ceiling -- a smooth 30 m DEM yields an honestly
        broad ~15-30 m peak, so the precision is reported, not invented.

    Firewall I3: the DEM is sampled at the ESTIMATED (shifted) cell centres; no GT is read."""
    centres = np.asarray(cell_centres, float)
    h_loc = np.asarray(cell_heights, float)
    m = centres.shape[0]
    if m < 3:
        return _RegResult(np.zeros(2), -2.0, 0.0, sigma_ceiling_m, False)
    loc = h_loc - h_loc.mean()
    loc_norm = float(np.linalg.norm(loc))
    if loc_norm <= 0.0:
        return _RegResult(np.zeros(2), -2.0, 0.0, sigma_ceiling_m, False)

    offs = np.arange(-search_radius_m, search_radius_m + 0.5 * search_step_m, search_step_m)
    dx, dy = np.meshgrid(offs, offs, indexing="xy")
    shifts = np.column_stack([dx.ravel(), dy.ravel()])               # (S,2)
    s = shifts.shape[0]
    # sample the DEM at every (cell + shift): query (S, M, 2) -> flat -> heights (S, M)
    q = centres[None, :, :] + shifts[:, None, :]
    qf = q.reshape(-1, 2)
    h_dem = np.asarray(dem.heights_enu(qf[:, 0], qf[:, 1]), float).reshape(s, m)
    h_dem_dm = h_dem - h_dem.mean(axis=1, keepdims=True)             # de-mean per shift
    num = h_dem_dm @ loc                                            # (S,)
    den = loc_norm * np.sqrt(np.sum(h_dem_dm * h_dem_dm, axis=1))
    corr = np.where(den > 0.0, num / np.maximum(den, 1e-12), -2.0)

    best = int(np.argmax(corr))
    best_corr = float(corr[best])
    best_shift = shifts[best].astype(float)
    dist = np.linalg.norm(shifts - best_shift[None, :], axis=1)
    # ambiguity guard: the best competing peak more than ambig_dist_m from the chosen one
    far = dist > ambig_dist_m
    corr_far = float(np.max(corr[far])) if np.any(far) else -2.0
    margin = best_corr - corr_far
    # fix sigma from the high-correlation blob breadth (positional spread within 0.05 of the peak)
    blob = corr >= best_corr - 0.05
    if int(blob.sum()) >= 2:
        sigma_est = float(np.sqrt(np.mean(dist[blob] ** 2)))
    else:
        sigma_est = sigma_floor_m
    sigma_m = float(min(max(sigma_est, sigma_floor_m), sigma_ceiling_m))
    on_boundary = bool(
        np.isclose(abs(best_shift[0]), search_radius_m, atol=0.5 * search_step_m)
        or np.isclose(abs(best_shift[1]), search_radius_m, atol=0.5 * search_step_m)
    )
    return _RegResult(best_shift, best_corr, float(margin), sigma_m, on_boundary)


def register_windows(
    frame_idx: np.ndarray, points_cam_per_frame: list[np.ndarray],
    r_enu_cam: np.ndarray, enu_pos: np.ndarray, dem: DemHeightSampler,
    *, n_nodes: int, window_len: int = 1500, window_step: int = 300,
    grid_m: float = 10.0, min_pts_per_cell: int = 4, min_cells: int = 10,
    min_total_points: int = 200, relief_min_m: float = 4.0, corr_min: float = 0.6,
    margin_min: float = 0.05, search_radius_m: float = 60.0, search_step_m: float = 3.0,
    max_shift_m: float = 60.0, ambig_dist_m: float = 40.0,
) -> list[DemXyFix]:
    """Slide windows over the trajectory and register each to the DEM, yielding one :class:`DemXyFix`
    per window (accepted or rejected, so the confidence distribution is fully visible).

    ``frame_idx`` (F,) are the node indices of the F sampled stereo-cloud frames; ``points_cam_per_frame``
    are their camera-optical point sets; ``r_enu_cam`` / ``enu_pos`` (N,3,..) place each node's camera in
    the DEM ENU frame (from :func:`dart.s3li_vio.vio_enu_camera_frames`). A window spans node indices
    ``[lo, lo+window_len)``; its accepted fix anchors the window-centre node at the registered absolute
    (E, N). Firewall I3: GT is never read."""
    frame_idx = np.asarray(frame_idx, np.int64)
    fixes: list[DemXyFix] = []
    lo = 0
    while lo < n_nodes:
        hi = min(lo + window_len, n_nodes)
        in_win = (frame_idx >= lo) & (frame_idx < hi)
        sel = np.nonzero(in_win)[0]
        centre = int(min((lo + hi) // 2, n_nodes - 1))
        node_xy = np.asarray(enu_pos, float)[centre, :2]

        if sel.size == 0:
            lo += window_step
            continue
        # accumulate this window's stereo points into the ENU frame at the ESTIMATED VIO poses
        chunks = []
        for f in sel:
            k = int(frame_idx[f])
            pts = points_cam_per_frame[f]
            if pts is None or len(pts) == 0:
                continue
            chunks.append(transform_cloud_to_enu(pts, r_enu_cam[k], enu_pos[k]))
        pts_enu = np.concatenate(chunks, axis=0) if chunks else np.empty((0, 3))
        n_points = int(pts_enu.shape[0])

        centres, heights, _counts = grid_patch(pts_enu, grid_m, min_pts_per_cell=min_pts_per_cell)
        n_cells = int(centres.shape[0])
        relief_std = float(np.std(heights - heights.mean())) if n_cells else 0.0

        reason = "ok"
        if n_points < min_total_points:
            reason = "too_few_points"
        elif n_cells < min_cells:
            reason = "too_few_cells"
        elif relief_std < relief_min_m:
            reason = "flat_patch"

        if reason != "ok":
            fixes.append(DemXyFix(centre, node_xy.copy(), np.zeros(2), -2.0, 0.0, 0.0, relief_std,
                                  n_cells, n_points, False, False, reason))
            lo += window_step
            continue

        reg = register_patch_xy(centres, heights, dem, search_radius_m=search_radius_m,
                                search_step_m=search_step_m, ambig_dist_m=ambig_dist_m)
        shift_norm = float(np.hypot(reg.shift_m[0], reg.shift_m[1]))
        if reg.corr < corr_min:
            reason = "low_corr"
        elif reg.margin < margin_min:
            reason = "ambiguous_peak"
        elif reg.on_boundary or shift_norm > max_shift_m:
            reason = "shift_out_of_range"
        accepted = reason == "ok"
        enu_xy = node_xy + reg.shift_m if accepted else node_xy.copy()
        fixes.append(DemXyFix(centre, enu_xy, reg.shift_m.copy(), reg.corr, reg.margin, reg.sigma_m,
                              relief_std, n_cells, n_points, reg.on_boundary, accepted, reason))
        lo += window_step
    return fixes


def accepted_fixes(fixes: list[DemXyFix]) -> list[DemXyFix]:
    """The accepted fixes, de-duplicated by anchored node (keep the highest-correlation one)."""
    best: dict[int, DemXyFix] = {}
    for f in fixes:
        if not f.accepted:
            continue
        cur = best.get(f.keyframe)
        if cur is None or f.corr > cur.corr:
            best[f.keyframe] = f
    return [best[k] for k in sorted(best)]


def whole_patch_cells(
    frame_idx: np.ndarray, points_cam_per_frame: list[np.ndarray], r_enu_cam: np.ndarray,
    enu_pos: np.ndarray, *, grid_m: float = 15.0, min_pts_per_cell: int = 8,
) -> tuple[np.ndarray, np.ndarray]:
    """The whole-trajectory accumulated terrain patch, gridded: ``(cell_centres (C,2), cell_heights
    (C,))``. Firewall-clean (estimated terrain only)."""
    chunks = []
    for f in range(np.asarray(frame_idx).shape[0]):
        k = int(frame_idx[f])
        pts = points_cam_per_frame[f]
        if pts is not None and len(pts):
            chunks.append(transform_cloud_to_enu(pts, r_enu_cam[k], enu_pos[k]))
    pts_enu = np.concatenate(chunks, axis=0) if chunks else np.empty((0, 3))
    centres, heights, _ = grid_patch(pts_enu, grid_m, min_pts_per_cell=min_pts_per_cell)
    return centres, heights


def global_registration(
    cell_centres: np.ndarray, cell_heights: np.ndarray, dem: DemHeightSampler, origin_xy: np.ndarray,
    *, dyaw_max_deg: float = 40.0, dyaw_step_deg: float = 4.0, scale_lo: float = 0.80,
    scale_hi: float = 1.20, scale_step: float = 0.05, trans_radius_m: float = 60.0,
    trans_step_m: float = 6.0,
) -> dict:
    """Best 4-DOF (heading + horizontal scale + translation, about ``origin_xy``) terrain registration
    of the WHOLE accumulated patch to the DEM, by de-meaned height correlation. A single well-posed fit
    (hundreds of cells constrain 4 DOF), unlike the per-window search -- it is the honest test of whether
    the DEM relief is observable at all. Returns the peak correlation + the transform + a boundary flag.
    Firewall I3: matches estimated terrain to the DEM; no GT."""
    centres = np.asarray(cell_centres, float)
    h_loc = np.asarray(cell_heights, float)
    o = np.asarray(origin_xy, float).reshape(2)
    if centres.shape[0] < 4:
        return {"best_corr": -2.0, "dyaw_deg": 0.0, "scale": 1.0, "shift_m": [0.0, 0.0],
                "on_boundary": False, "n_cells": int(centres.shape[0])}
    loc = h_loc - h_loc.mean()
    loc_norm = float(np.linalg.norm(loc))
    txs = np.arange(-trans_radius_m, trans_radius_m + 0.5 * trans_step_m, trans_step_m)
    tg, sg = np.meshgrid(txs, txs)
    trans = np.column_stack([tg.ravel(), sg.ravel()])
    dyaws = np.arange(-dyaw_max_deg, dyaw_max_deg + 0.5 * dyaw_step_deg, dyaw_step_deg)
    scales = np.arange(scale_lo, scale_hi + 0.5 * scale_step, scale_step)
    best_corr = -2.0
    best_dyaw = 0.0
    best_scale = 1.0
    best_shift = (0.0, 0.0)
    for dyaw in dyaws:
        th = np.radians(dyaw)
        rm = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
        for scale in scales:
            base = (scale * (rm @ (centres - o).T)).T + o                  # (M,2)
            qx = base[None, :, 0] + trans[:, 0:1]
            qy = base[None, :, 1] + trans[:, 1:2]
            hd = np.asarray(dem.heights_enu(qx.ravel(), qy.ravel()), float).reshape(trans.shape[0], -1)
            hd = hd - hd.mean(axis=1, keepdims=True)
            den = loc_norm * np.sqrt(np.sum(hd * hd, axis=1))
            co = np.where(den > 0.0, (hd @ loc) / np.maximum(den, 1e-12), -2.0)
            b = int(np.argmax(co))
            if float(co[b]) > best_corr:
                best_corr = float(co[b])
                best_dyaw = float(dyaw)
                best_scale = float(scale)
                best_shift = (float(trans[b, 0]), float(trans[b, 1]))
    on_boundary = bool(
        abs(best_dyaw) >= dyaw_max_deg - 1e-6
        or best_scale <= scale_lo + 1e-6 or best_scale >= scale_hi - 1e-6
        or max(abs(best_shift[0]), abs(best_shift[1])) >= trans_radius_m - 1e-6
    )
    return {"best_corr": best_corr, "dyaw_deg": best_dyaw, "scale": best_scale,
            "shift_m": [best_shift[0], best_shift[1]], "on_boundary": on_boundary,
            "n_cells": int(centres.shape[0])}


def estimate_demxy_and_freeze(
    enu_vio: np.ndarray, r_enu_cam: np.ndarray, ts_ns: np.ndarray,
    frame_idx: np.ndarray, points_cam_per_frame: list[np.ndarray], dem, out_dir: str,
    *, sigma_vo_m: float = 0.05, sigma_dem_m: float = 2.0, sigma_prior_m: float = 0.5,
    anchor_every: int = 10, demxy_name: str = "vio_demxy_anchored_enu.tum",
    window_len: int = 1500, window_step: int = 300, grid_m: float = 10.0,
    min_pts_per_cell: int = 4, min_cells: int = 10, min_total_points: int = 200,
    relief_min_m: float = 4.0, corr_min: float = 0.6, margin_min: float = 0.05,
    search_radius_m: float = 60.0, search_step_m: float = 3.0, max_shift_m: float = 60.0,
    ambig_dist_m: float = 40.0, xy_only_name: str = "vio_demxy_only_enu.tum",
) -> dict:
    """Build + FREEZE the VIO + horizontal-DEM-terrain-correlation-anchored estimate from the registered
    VIO ENU trajectory, the per-frame stereo clouds, and the DEM ONLY (no GT; invariant I3).

    Registers sliding windows of the rover's locally-observed terrain to the DEM (horizontal absolute
    fixes), then re-solves the pose graph TWICE -- (1) the JOINT solve with the VIO between-factors + DEM
    height-normal anchors + the DEM_XY horizontal fixes (``demxy_name``, the task's joint anchor); (2) an
    XY-ONLY solve with the between-factors + DEM_XY fixes but NO height-normal anchor (``xy_only_name``),
    which isolates the horizontal anchor's effect from the separately-behaving vertical anchor. Pure
    function of (estimate, stereo clouds, DEM, declared start); no ground-truth argument."""
    from dart.dem_height_graph import (
        DemHeightPoseGraph,
        build_between_factors,
        build_dem_anchor_factors,
        build_dem_xy_factors,
    )
    from dart.s3li_capstone import write_tum

    import os

    enu_vio = np.asarray(enu_vio, float)
    n = enu_vio.shape[0]
    fixes = register_windows(
        frame_idx, points_cam_per_frame, r_enu_cam, enu_vio, dem, n_nodes=n,
        window_len=window_len, window_step=window_step, grid_m=grid_m,
        min_pts_per_cell=min_pts_per_cell, min_cells=min_cells, min_total_points=min_total_points,
        relief_min_m=relief_min_m, corr_min=corr_min, margin_min=margin_min,
        search_radius_m=search_radius_m, search_step_m=search_step_m, max_shift_m=max_shift_m,
        ambig_dist_m=ambig_dist_m,
    )
    acc = accepted_fixes(fixes)

    between = build_between_factors(np.diff(enu_vio, axis=0), sigma_vo_m)
    anchor_idx = list(range(0, n, anchor_every))
    height_anchors = build_dem_anchor_factors(anchor_idx, sigma_dem_m)
    xy_anchors = build_dem_xy_factors(
        [f.keyframe for f in acc], np.array([f.enu_xy for f in acc]).reshape(-1, 2),
        np.array([f.sigma_m for f in acc]) if acc else np.array([]),
    )
    graph = DemHeightPoseGraph(dem)
    result = graph.solve(enu_vio, between, height_anchors, prior_idx=0,
                         prior_xyz=enu_vio[0].copy(), prior_sigma_m=sigma_prior_m,
                         xy_anchors=xy_anchors)
    # XY-only: between + DEM_XY fixes, no height-normal anchor (isolates the horizontal anchor)
    result_xy = graph.solve(enu_vio, between, [], prior_idx=0, prior_xyz=enu_vio[0].copy(),
                            prior_sigma_m=sigma_prior_m, xy_anchors=xy_anchors)

    ts_s = np.asarray(ts_ns, np.int64) / 1e9
    ident = np.tile(np.array([1.0, 0.0, 0.0, 0.0]), (ts_s.size, 1))
    demxy_path = os.path.join(out_dir, demxy_name)
    xy_only_path = os.path.join(out_dir, xy_only_name)
    write_tum(demxy_path, ts_s, result.xyz, ident)
    write_tum(xy_only_path, ts_s, result_xy.xyz, ident)
    return {
        "fixes": fixes,
        "accepted": acc,
        "result": result,
        "result_xy_only": result_xy,
        "demxy_tum": demxy_path,
        "xy_only_tum": xy_only_path,
        "n_windows": len(fixes),
        "n_accepted": len(acc),
        "n_anchors": len(xy_anchors),
    }
