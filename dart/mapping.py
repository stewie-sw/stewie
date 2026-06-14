"""2.5D elevation + rock-count mapping: accumulate calibrated stereo depth along the traverse into a
world-frame elevation grid, and correlate the built map to the prior REAL DEM.

Pipeline (all on REAL rendered Godot frames + the prior REAL LOLA DEM; the global-map tier of the
perception stack):

  1. per frame, triangulate the rectified stereo pair into a metric point cloud in the reference
     (left) camera optical frame (reuses :func:`dart.stereo_vo.triangulate_stereo`);
  2. place each cloud in the Godot ground frame (x = col*cell, z = row*cell, elevation = world Y)
     with the camera centre for that frame and the FIXED camera-mount rotation -- a rig calibration
     constant (the camera looks +X, tilted down by atan(look_down_ratio), up = world +Y), the same
     for every frame on a yaw-0 traverse;
  3. accumulate the placed points into a 2.5D grid, keeping the median elevation per cell (robust to
     the per-cell spread of sparse low-texture matches) and a per-cell observation count (a coarse
     "rock"/structure-density proxy: cells that collect many returns are textured boulders/relief);
  4. correlate the built elevation patch to the prior DEM via
     :func:`dart.dem_anchor.anchor_offset` (NCC peak) to recover the horizontal map->DEM
     registration.

Pose source (invariant I3, truth firewall): :func:`build_elevation_map` takes the per-frame camera
CENTRES as an argument -- a PERCEPTION product (e.g. the VO trajectory from
:func:`dart.stereo_vo.estimate_vo` anchored at a single start localization fix). It has
NO pose/slip/truth/clast parameter; no per-frame ground-truth pose ever enters the builder. The prior
DEM is a legitimate prior map (a perception/eval input), not hidden state; comparing the built map to
the DEM (:func:`elevation_rmse_vs_dem`) is the eval/scoring path.

Why the elevation RMSE is reported as both raw and mean-removed: a constant datum offset (camera
height / pitch calibration residual) shifts every built elevation by the same amount, which inflates
the raw RMSE but carries no terrain-shape error. The mean-removed RMSE -- exactly the quantity the
mean-removed NCC anchor is invariant to -- isolates the recovered relief error, and the correlation
coefficient reports how much of the real DEM shape the built map recovered.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
import os
from dataclasses import dataclass

import numpy as np

from dart import dem_anchor
from .stereo_vo import StereoVOConfig, triangulate_stereo


@dataclass(frozen=True)
class MappingConfig:
    """Rig intrinsics + ground-frame grid + fixed camera mount for elevation accumulation.

    ``fx_px``/``fy_px``/``cx_px``/``cy_px`` are the pinhole intrinsics, ``baseline_m`` the stereo
    baseline (m). ``cell_m`` is the world grid posting (m); ``grid_rows``/``grid_cols`` its size, with
    cell (row, col) centred at Godot world (x = col*cell, z = row*cell) and elevation = world Y --
    the convention the dustgym heightmap.rf32 is stored in. ``camera_height_m`` is the camera mount
    height above the ground datum; ``look_down_ratio`` the rig look-at drop per metre forward (the
    a6 rig drops 0.4 m over 1 m -> ~21.8 deg downtilt). ``max_range_m`` range-gates triangulated
    points (far-range stereo error grows as range^2). All scales must be finite and positive.
    """

    fx_px: float
    fy_px: float
    cx_px: float
    cy_px: float
    baseline_m: float
    cell_m: float
    grid_rows: int
    grid_cols: int
    camera_height_m: float = 0.8
    look_down_ratio: float = 0.4
    max_range_m: float = 4.0

    def __post_init__(self) -> None:
        scale = np.asarray(
            [self.fx_px, self.fy_px, self.baseline_m, self.cell_m, self.max_range_m], dtype=float
        )
        if not np.all(np.isfinite(scale)) or np.any(scale <= 0.0):
            raise ValueError("intrinsics, baseline, cell size and range gate must be finite/positive")
        if not (np.isfinite(self.cx_px) and np.isfinite(self.cy_px)):
            raise ValueError("principal point must be finite")
        if self.grid_rows <= 0 or self.grid_cols <= 0:
            raise ValueError("grid dimensions must be positive")
        if self.look_down_ratio < 0.0 or not np.isfinite(self.look_down_ratio):
            raise ValueError("look_down_ratio must be finite and non-negative")

    @classmethod
    def from_fov(
        cls,
        *,
        width_px: int,
        height_px: int,
        hfov_deg: float,
        baseline_m: float,
        cell_m: float,
        grid_rows: int,
        grid_cols: int,
        camera_height_m: float = 0.8,
        look_down_ratio: float = 0.4,
        max_range_m: float = 4.0,
    ) -> MappingConfig:
        """Build the config with fx derived from the rig HFOV (square pixels, centred principal
        point): fx = (W/2)/tan(HFOV/2). This is the focal length the frames were rendered with."""
        if width_px <= 0 or height_px <= 0:
            raise ValueError("image dimensions must be positive")
        if not 0.0 < hfov_deg < 180.0:
            raise ValueError("hfov_deg must be in (0, 180)")
        fx = (width_px * 0.5) / math.tan(math.radians(hfov_deg) * 0.5)
        return cls(
            fx_px=fx, fy_px=fx, cx_px=width_px * 0.5, cy_px=height_px * 0.5,
            baseline_m=baseline_m, cell_m=cell_m, grid_rows=grid_rows, grid_cols=grid_cols,
            camera_height_m=camera_height_m, look_down_ratio=look_down_ratio, max_range_m=max_range_m,
        )

    def stereo_config(self, **overrides: float) -> StereoVOConfig:
        """The matching :class:`StereoVOConfig` for the triangulation front end (same intrinsics)."""
        return StereoVOConfig(
            fx_px=self.fx_px, fy_px=self.fy_px, cx_px=self.cx_px, cy_px=self.cy_px,
            baseline_m=self.baseline_m, **overrides,  # type: ignore[arg-type]
        )

    def optical_to_world_rotation(self) -> np.ndarray:
        """Fixed camera-mount rotation: optical frame (x right, y down, z forward) -> Godot ground
        frame (x, y up, z). Built from the rig look-at: the camera looks along
        normalize(1, -look_down_ratio, 0) with world up (0, 1, 0), exactly the Godot
        ``look_at_from_position(pos, pos + look_dir, UP)`` convention the frames were rendered with.

        Derivation: Godot camera basis has -Z = forward, +X = right = normalize(up x (-forward)),
        +Y = up = (-forward... ) reconstructed; the optical frame is x_opt = +X_gcam,
        y_opt = -Y_gcam, z_opt = -Z_gcam = forward. A proper rotation (orthonormal, det +1)."""
        fwd = np.array([1.0, -self.look_down_ratio, 0.0])
        fwd = fwd / np.linalg.norm(fwd)
        zc = -fwd                                          # Godot camera +Z (points back from look)
        up = np.array([0.0, 1.0, 0.0])
        xc = np.cross(up, zc)
        xc = xc / np.linalg.norm(xc)                       # camera right
        yc = np.cross(zc, xc)                              # camera up
        # optical axes in Godot world: x_opt = xc, y_opt = -yc (down), z_opt = -zc = fwd
        return np.column_stack([xc, -yc, -zc])

    def world_to_cell(self, x_m: float, z_m: float) -> tuple[int, int]:
        """Godot world (x, z) -> nearest grid (row, col); row from z, col from x."""
        return int(round(z_m / self.cell_m)), int(round(x_m / self.cell_m))

    def cell_to_world(self, row: int, col: int) -> tuple[float, float]:
        """Grid (row, col) -> Godot world (x, z) of the cell centre."""
        return col * self.cell_m, row * self.cell_m


@dataclass(frozen=True)
class ElevationMap:
    """A built 2.5D map. ``elevation`` (R,C) is the median accumulated world-Y per cell (NaN where
    unobserved); ``count`` (R,C) the per-cell observation count (a coarse structure/"rock"-density
    proxy -- textured boulders/relief return many points); ``cell_m`` the posting; ``n_points`` the
    total placed points; ``n_frames`` the number of accumulated frames."""

    elevation: np.ndarray
    count: np.ndarray
    cell_m: float
    n_points: int
    n_frames: int

    def covered_mask(self) -> np.ndarray:
        """Boolean mask of observed cells."""
        return np.isfinite(self.elevation)


@dataclass(frozen=True)
class ElevationStats:
    """Honest built-vs-DEM elevation comparison over the covered overlap.

    raw_rmse_m         : RMSE of (built - DEM) over covered cells (includes any datum bias)
    mean_removed_rmse_m: RMSE after removing the per-set mean from both (relief-shape error only)
    bias_m             : median(built - DEM) over the overlap (the datum offset)
    correlation        : Pearson correlation of built vs DEM elevations over the overlap
    covered_cells      : number of overlapping observed cells the statistics are computed on
    """

    raw_rmse_m: float
    mean_removed_rmse_m: float
    bias_m: float
    correlation: float
    covered_cells: int


def vo_trajectory_to_world_centres(
    trajectory_xyz_m: np.ndarray,
    config: MappingConfig,
    *,
    start_xz: tuple[float, float],
) -> np.ndarray:
    """Map a VO camera trajectory (left-optical frame, origin at frame 0) to Godot-world camera
    centres, given a single start (x, z) localization fix.

    The VO trajectory is a perception product; ``start_xz`` is the one localization fix the mapper is
    allowed (e.g. globe-pick siting of the start cell), NOT a per-frame pose. Each optical-frame
    camera centre is rotated by the fixed mount and offset to place frame 0 at
    (start_x, camera_height, start_z). Returns an (F, 3) array of Godot (x, y, z) centres.
    """
    traj = np.asarray(trajectory_xyz_m, dtype=float)
    if traj.ndim != 2 or traj.shape[1] != 3:
        raise ValueError("trajectory must be (F, 3)")
    rot = config.optical_to_world_rotation()
    x0, z0 = float(start_xz[0]), float(start_xz[1])
    c0 = np.array([x0, config.camera_height_m, z0])
    # frame 0 sits at c0; subsequent centres are c0 + R @ (traj_k - traj_0)
    rel = traj - traj[0]
    return (rot @ rel.T).T + c0


def build_elevation_map(
    stereo_pairs: list[tuple[np.ndarray, np.ndarray]],
    camera_centres_world: np.ndarray,
    config: MappingConfig,
    *,
    camera_orientations: "np.ndarray | None" = None,
) -> ElevationMap:
    """Accumulate triangulated stereo depth along the traverse into a 2.5D elevation + count map.

    For each stereo pair the reference frame is triangulated to a metric cloud in the left optical
    frame; points within ``max_range_m`` are rotated to world, translated to the frame's world camera
    centre, and binned into the ground grid (row from z, col from x). The per-cell elevation is the
    median of all world-Y returns landing in that cell (robust to the spread of sparse low-texture
    matches), and the per-cell count is the number of returns.

    H-17: ``camera_orientations`` is an optional (F, 3, 3) per-frame optical->world rotation, so the
    rover's per-frame yaw/pitch/roll/articulated posture is represented instead of one fixed mount for
    the whole traverse. When None (the default) every frame uses the fixed mount rotation
    (``config.optical_to_world_rotation()``), i.e. behaviour is unchanged.

    Truth firewall (invariant I3): images + camera centres + per-frame ORIENTATION (a perception/pose
    product) + calibration only. No slip/truth/clast field is an argument; no ground-truth position enters.
    """
    centres = np.asarray(camera_centres_world, dtype=float)
    if centres.ndim != 2 or centres.shape[1] != 3:
        raise ValueError("camera_centres_world must be (F, 3)")
    if len(stereo_pairs) != centres.shape[0]:
        raise ValueError("need one camera centre per stereo pair")
    if not stereo_pairs:
        raise ValueError("need at least one stereo pair to build a map")
    rots = None
    if camera_orientations is not None:                # H-17: per-frame orientation (else the fixed mount)
        rots = np.asarray(camera_orientations, dtype=float)
        if rots.shape != (centres.shape[0], 3, 3):
            raise ValueError("camera_orientations must be (F, 3, 3), one optical->world rotation per frame")

    R, C = config.grid_rows, config.grid_cols
    rot = config.optical_to_world_rotation()
    scfg = config.stereo_config()
    # per-cell accumulation of world-Y returns (lists kept until the per-cell median is taken)
    buckets: dict[tuple[int, int], list[float]] = {}
    n_points = 0

    for k, ((left, right), centre) in enumerate(zip(stereo_pairs, centres)):
        cloud = triangulate_stereo(left, right, scfg)
        pts = cloud.points_3d
        if pts.shape[0] == 0:
            continue
        keep = pts[:, 2] < config.max_range_m
        pts = pts[keep]
        if pts.shape[0] == 0:
            continue
        rot_k = rots[k] if rots is not None else rot  # H-17: this frame's orientation (else the fixed mount)
        world = (rot_k @ pts.T).T + centre            # Godot world (x, y, z)
        cols = np.rint(world[:, 0] / config.cell_m).astype(int)
        rows = np.rint(world[:, 2] / config.cell_m).astype(int)
        in_grid = (rows >= 0) & (rows < R) & (cols >= 0) & (cols < C)
        for r, c, y in zip(rows[in_grid], cols[in_grid], world[in_grid, 1]):
            buckets.setdefault((int(r), int(c)), []).append(float(y))
            n_points += 1

    elevation = np.full((R, C), np.nan, dtype=np.float64)
    count = np.zeros((R, C), dtype=np.int64)
    for (r, c), ys in buckets.items():
        elevation[r, c] = float(np.median(ys))
        count[r, c] = len(ys)

    return ElevationMap(
        elevation=elevation,
        count=count,
        cell_m=config.cell_m,
        n_points=n_points,
        n_frames=len(stereo_pairs),
    )


def elevation_rmse_vs_dem(built_elevation: np.ndarray, dem: np.ndarray) -> ElevationStats:
    """Honest built-vs-DEM elevation comparison over the covered overlap (eval/scoring path).

    Computes the raw RMSE, the mean-removed RMSE (datum-invariant relief error), the median bias, and
    the Pearson correlation of the built elevations against the prior DEM over the cells the built map
    actually observed and the DEM has finite data. Raises if there is no usable overlap (it never
    invents a number). The DEM is the prior map being scored against; no ground-truth pose enters.
    """
    built = np.asarray(built_elevation, dtype=np.float64)
    ref = np.asarray(dem, dtype=np.float64)
    if built.shape != ref.shape:
        raise ValueError("built map and DEM must share the same grid shape")
    overlap = np.isfinite(built) & np.isfinite(ref)
    n = int(overlap.sum())
    if n == 0:
        raise ValueError("no covered overlap between the built map and the DEM")
    b = built[overlap]
    d = ref[overlap]
    diff = b - d
    raw = float(np.sqrt(np.mean(diff ** 2)))
    mr_diff = (b - b.mean()) - (d - d.mean())
    mean_removed = float(np.sqrt(np.mean(mr_diff ** 2)))
    bias = float(np.median(diff))
    if n >= 2 and float(np.std(b)) > 0.0 and float(np.std(d)) > 0.0:
        correlation = float(np.corrcoef(b, d)[0, 1])
    else:
        correlation = 0.0
    return ElevationStats(
        raw_rmse_m=raw,
        mean_removed_rmse_m=mean_removed,
        bias_m=bias,
        correlation=correlation,
        covered_cells=n,
    )


def dense_window(
    emap: ElevationMap,
    *,
    half_cells: int = 24,
    center_rc: tuple[int, int] | None = None,
) -> tuple[np.ndarray, tuple[int, int]]:
    """Extract a square, gap-filled observed window from the dense core of the built map.

    The traverse leaves a sparse swath plus scattered far returns, so the full covered bounding box is
    nearly the whole grid. For registration we take a fixed ``2*half_cells`` window around the
    count-weighted coverage centroid (the dense core where the rover actually accumulated returns),
    filling unobserved cells with the window mean so they carry no shape signal. Returns
    ``(patch, (cr, cc))`` -- the gap-filled patch and the grid (row, col) of its centre.
    """
    covered = np.isfinite(emap.elevation)
    if not np.any(covered):
        raise ValueError("built map has no covered cells to register")
    if center_rc is None:
        weights = emap.count.astype(np.float64)
        total = float(weights.sum())
        rr, cc = np.indices(emap.elevation.shape)
        cr = int(round(float((rr * weights).sum()) / total))
        cc0 = int(round(float((cc * weights).sum()) / total))
    else:
        cr, cc0 = int(center_rc[0]), int(center_rc[1])
    H, W = emap.elevation.shape
    cr = int(np.clip(cr, half_cells, H - half_cells - 1))
    cc0 = int(np.clip(cc0, half_cells, W - half_cells - 1))
    patch = emap.elevation[cr - half_cells:cr + half_cells, cc0 - half_cells:cc0 + half_cells].copy()
    finite = np.isfinite(patch)
    if finite.sum() < 4:
        raise ValueError("dense window too sparse to register")
    patch = np.where(finite, patch, float(np.nanmean(patch)))
    return patch, (cr, cc0)


def register_within_map(
    emap: ElevationMap,
    *,
    known_offset_cells: tuple[int, int],
    half_cells: int = 12,
    window_cells: int = 20,
    center_rc: tuple[int, int] | None = None,
) -> dem_anchor.AnchorResult:
    """Recover a KNOWN injected horizontal offset of the built map against itself via the NCC anchor.

    Crops a ``2*window_cells`` reference window from the built map's dense core and a smaller
    ``2*half_cells`` observed sub-window shifted by ``known_offset_cells``, then reads the offset off
    the NCC surface. Recovering the injected (dr, dc) within a cell verifies (a) the registration
    mechanism and (b) that the built relief is genuinely 2-D-distinctive (a textured boulder/crater
    field, not a flat or 1-D ridge) -- a real numeric recovery, not a tautology. Both inputs are the
    built map (a perception product); no truth enters.
    """
    covered = np.isfinite(emap.elevation)
    if not np.any(covered):
        raise ValueError("built map has no covered cells to register")
    if center_rc is None:
        weights = emap.count.astype(np.float64)
        total = float(weights.sum())
        rr, cc = np.indices(emap.elevation.shape)
        cr = int(round(float((rr * weights).sum()) / total))
        cc0 = int(round(float((cc * weights).sum()) / total))
    else:
        cr, cc0 = int(center_rc[0]), int(center_rc[1])
    kdr, kdc = int(known_offset_cells[0]), int(known_offset_cells[1])
    H, W = emap.elevation.shape
    margin = window_cells + abs(kdr) + abs(kdc) + half_cells
    cr = int(np.clip(cr, margin, H - margin - 1))
    cc0 = int(np.clip(cc0, margin, W - margin - 1))

    def _fill(block: np.ndarray) -> np.ndarray:
        finite = np.isfinite(block)
        if finite.sum() < 4:
            raise ValueError("built window too sparse to register")
        return np.where(finite, block, float(np.nanmean(block)))

    base = _fill(emap.elevation[cr - window_cells:cr + window_cells,
                                cc0 - window_cells:cc0 + window_cells].copy())
    obs = _fill(emap.elevation[cr + kdr - half_cells:cr + kdr + half_cells,
                               cc0 + kdc - half_cells:cc0 + kdc + half_cells].copy())
    return dem_anchor.anchor_offset(obs, base, method="ncc", posting_m=emap.cell_m)


def correlate_to_dem(
    emap: ElevationMap,
    dem: np.ndarray,
    *,
    known_offset_cells: tuple[int, int] = (0, 0),
    half_cells: int = 24,
    search_pad_cells: int = 8,
    center_rc: tuple[int, int] | None = None,
) -> dem_anchor.AnchorResult:
    """Register the built elevation patch against the prior DEM via the NCC anchor.

    Takes a fixed dense observed window (:func:`dense_window`) from the built map's dense core, crops
    the matching DEM window padded by ``search_pad_cells`` and shifted by ``known_offset_cells``, and
    reads the offset off the NCC surface. The returned
    :class:`~dart.dem_anchor.AnchorResult` ``offset_cells`` is the recovered (dr, dc) of
    the built patch relative to the DEM-window centre.

    ``known_offset_cells`` lets the global-map tier verify the registration by injecting a controlled
    shift the recovered peak should report; with (0, 0) it reports where the built patch best aligns
    to the prior DEM. Eval/scoring path: the DEM is the prior map, not hidden truth.
    """
    ref = np.asarray(dem, dtype=np.float64)
    patch, (cr, cc) = dense_window(emap, half_cells=half_cells, center_rc=center_rc)
    ph, pw = patch.shape
    kdr, kdc = int(known_offset_cells[0]), int(known_offset_cells[1])
    pad = int(search_pad_cells)
    # DEM window centred on the observed patch's footprint, shifted by the injected known offset, padded.
    # The window moves by MINUS the offset: content then sits at +offset from the window centre, so the
    # recovered peak REPORTS the injected shift (it previously reported its negation; audit 2026-06-09).
    wr0 = (cr - half_cells) - kdr - pad
    wc0 = (cc - half_cells) - kdc - pad
    wr1 = wr0 + ph + 2 * pad
    wc1 = wc0 + pw + 2 * pad
    H, W = ref.shape
    if wr0 < 0 or wc0 < 0 or wr1 > H or wc1 > W:
        raise ValueError("DEM search window falls outside the prior DEM bounds")
    dem_window = ref[wr0:wr1, wc0:wc1]
    # fill any DEM no-data so the NCC surface stays finite
    if not np.all(np.isfinite(dem_window)):
        dem_window = np.where(np.isfinite(dem_window), dem_window, float(np.nanmean(dem_window)))

    return dem_anchor.anchor_offset(
        patch, dem_window, method="ncc", posting_m=emap.cell_m,
    )


def save_map_vs_dem_png(
    emap: ElevationMap,
    dem: np.ndarray,
    out_path: str,
    *,
    cfg: MappingConfig | None = None,
) -> str:
    """Save a side-by-side PNG: the built elevation map, the prior DEM (cropped to the built
    footprint), the per-cell observation/structure-density count, and the honest built-vs-DEM
    elevation statistics in the title. Agg backend (no display). Returns the written path.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    elev = emap.elevation
    ref = np.asarray(dem, dtype=np.float64)
    stats = elevation_rmse_vs_dem(elev, ref)
    covered = np.isfinite(elev)
    rows = np.where(covered.any(axis=1))[0]
    cols = np.where(covered.any(axis=0))[0]
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1
    built_crop = elev[r0:r1, c0:c1]
    dem_crop = ref[r0:r1, c0:c1]
    count_crop = emap.count[r0:r1, c0:c1].astype(float)

    # shared elevation color scale over the overlapping finite values
    both = np.concatenate([
        built_crop[np.isfinite(built_crop)], dem_crop[np.isfinite(dem_crop)],
    ])
    vmin, vmax = float(np.percentile(both, 2)), float(np.percentile(both, 98))

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.0))
    extent = None
    if cfg is not None:
        x_lo, z_lo = cfg.cell_to_world(r0, c0)
        x_hi, z_hi = cfg.cell_to_world(r1 - 1, c1 - 1)
        extent = (x_lo, x_hi, z_hi, z_lo)  # x (cols) horizontal, z (rows) vertical (upper origin)

    im0 = axes[0].imshow(built_crop, cmap="terrain", origin="upper", vmin=vmin, vmax=vmax,
                         extent=extent)
    axes[0].set_title(f"Built elevation map (stereo depth)\n"
                      f"{stats.covered_cells} cells, {emap.n_points} pts, {emap.n_frames} frames")
    fig.colorbar(im0, ax=axes[0], fraction=0.046, pad=0.04, label="elevation (m)")

    im1 = axes[1].imshow(dem_crop, cmap="terrain", origin="upper", vmin=vmin, vmax=vmax,
                         extent=extent)
    axes[1].set_title("Prior REAL DEM (crater_boulders)\nsame footprint")
    fig.colorbar(im1, ax=axes[1], fraction=0.046, pad=0.04, label="elevation (m)")

    im2 = axes[2].imshow(np.where(count_crop > 0, count_crop, np.nan), cmap="magma",
                         origin="upper", extent=extent)
    axes[2].set_title("Per-cell return count\n(structure / rock density proxy)")
    fig.colorbar(im2, ax=axes[2], fraction=0.046, pad=0.04, label="returns / cell")

    for ax in axes:
        if cfg is not None:
            ax.set_xlabel("Godot x (m)")
            ax.set_ylabel("Godot z (m)")
        else:
            ax.set_xlabel("col [cells]")
            ax.set_ylabel("row [cells]")

    fig.suptitle(
        "Built 2.5D elevation map vs prior REAL DEM  "
        f"(raw RMSE {stats.raw_rmse_m:.3f} m, mean-removed RMSE {stats.mean_removed_rmse_m:.3f} m, "
        f"bias {stats.bias_m:+.3f} m, corr {stats.correlation:.3f})",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out_path
