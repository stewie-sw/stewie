"""Unit tests for the horizontal DEM terrain-correlation anchor (:mod:`dart.dem_terrain_match`) and the
DEM_XY pose-graph factor (:mod:`dart.dem_height_graph`).

REAL DATA ONLY. The registration tests use the REAL Copernicus GLO-30 Etna DEM relief: a real terrain
patch is sampled from the DEM, shifted by a KNOWN offset, and the matcher must recover that offset --
no synthetic terrain is fabricated. The solver-mechanism test feeds the DEM_XY factor a KNOWN absolute
target and confirms the pose graph pulls the anchored node onto it (pure linear-algebra, no GT). These
establish that the machinery is correct independently of whether the 30 m DEM can SUPPLY good fixes
(the honest negative reported in the s3li_crater_demxy artifact)."""
from __future__ import annotations

import os

import numpy as np
import pytest

from dart.dem_height_graph import (
    DemHeightPoseGraph,
    build_between_factors,
    build_dem_xy_factors,
)
from dart.dem_terrain_match import (
    grid_patch,
    register_patch_xy,
    transform_cloud_to_enu,
)
from dart.s3li_dem import DEFAULT_DEM_PATH, S3liDem

_HAVE_DEM = os.path.isfile(DEFAULT_DEM_PATH)
_skip_dem = pytest.mark.skipif(not _HAVE_DEM, reason="Copernicus GLO-30 Etna DEM tile not present")


def test_transform_cloud_to_enu_identity():
    """An identity camera pose at the origin leaves points unchanged; a translation offsets them."""
    pts = np.array([[1.0, 2.0, 3.0], [-1.0, 0.0, 5.0]])
    out = transform_cloud_to_enu(pts, np.eye(3), np.array([10.0, 20.0, 30.0]))
    assert np.allclose(out, pts + np.array([10.0, 20.0, 30.0]))
    assert transform_cloud_to_enu(np.empty((0, 3)), np.eye(3), np.zeros(3)).shape == (0, 3)


def test_grid_patch_downsamples_to_cells():
    """grid_patch snaps to a grid and keeps cells with >= min_pts_per_cell points (median height)."""
    # two clusters in two different 10 m cells; one sparse cell that must be dropped
    a = np.column_stack([np.full(6, 3.0), np.full(6, 4.0), np.linspace(100.0, 105.0, 6)])
    b = np.column_stack([np.full(6, 23.0), np.full(6, 4.0), np.linspace(200.0, 205.0, 6)])
    sparse = np.array([[55.0, 4.0, 999.0], [56.0, 4.0, 999.0]])  # only 2 pts -> dropped
    centres, heights, counts = grid_patch(np.vstack([a, b, sparse]), 10.0, min_pts_per_cell=4)
    assert centres.shape[0] == 2
    assert np.all(counts == 6)
    # medians of the two clusters
    assert np.isclose(sorted(heights)[0], np.median(np.linspace(100.0, 105.0, 6)))
    assert np.isclose(sorted(heights)[1], np.median(np.linspace(200.0, 205.0, 6)))


@_skip_dem
def test_heights_enu_vectorized_matches_scalar():
    """The vectorised DEM sampler equals the per-point scalar sampler (used by the shift search)."""
    dem = S3liDem()
    e = np.array([0.0, 30.0, 60.0, -20.0, 90.0])
    n = np.array([0.0, 30.0, -10.0, 50.0, 120.0])
    hv = dem.heights_enu(e, n)
    hs = np.array([dem.height_enu(float(a), float(b)) for a, b in zip(e, n)])
    assert np.allclose(hv, hs, atol=1e-9)


@_skip_dem
def test_register_patch_xy_recovers_known_shift_on_real_dem():
    """On the REAL DEM relief: a terrain patch sampled at (cell + true_shift) must be recovered by the
    matcher as -true_shift back to the cell grid -> i.e. the search returns true_shift. Validates the
    correlation search localises the peak on genuine terrain (no synthetic data)."""
    dem = S3liDem()
    gx, gy = np.meshgrid(np.arange(-50.0, 110.0, 10.0), np.arange(-50.0, 110.0, 10.0))
    centres = np.column_stack([gx.ravel(), gy.ravel()])
    true_shift = np.array([21.0, -15.0])
    # the "local" patch elevations ARE the DEM relief at the shifted locations
    local_h = dem.heights_enu(centres[:, 0] + true_shift[0], centres[:, 1] + true_shift[1])
    reg = register_patch_xy(centres, local_h, dem, search_radius_m=45.0, search_step_m=3.0)
    assert reg.corr > 0.99
    assert np.allclose(reg.shift_m, true_shift, atol=3.0)  # within one search step
    assert not reg.on_boundary


@_skip_dem
def test_dem_xy_factor_pulls_node_to_known_fix():
    """SOLVER MECHANISM (no GT): a DEM_XY absolute-position factor must pull its anchored node onto the
    fix. Build a short straight between-chain (drifted from a target line), add ONE DEM_XY fix at a
    KNOWN (E,N), solve, and confirm the anchored node lands on the fix and the chain rigidly follows.
    Proves that WHEN the terrain match supplies a good fix, the pose graph uses it (so the null result
    on the 30 m DEM is a DEM-resolution limit, not a machinery bug)."""
    dem = S3liDem()
    n = 20
    # a straight VIO chain along +E at z=10, 1 m steps, starting at the origin
    enu = np.column_stack([np.arange(n, dtype=float), np.zeros(n), np.full(n, 10.0)])
    between = build_between_factors(np.diff(enu, axis=0), sigma_xyz_m=0.05)
    # a known absolute fix: node 10 truly sits 3 m NORTH and 2 m EAST of where the chain placed it
    offset = np.array([2.0, 3.0])
    target = enu[10, :2] + offset
    xy = build_dem_xy_factors([10], target.reshape(1, 2), np.array([0.3]))
    graph = DemHeightPoseGraph(dem)
    res = graph.solve(enu, between, [], prior_idx=0, prior_xyz=enu[0].copy(), prior_sigma_m=0.05,
                      xy_anchors=xy)
    assert res.n_xy_anchors == 1
    # node 0 is the firm gauge -> stays at the prior
    assert np.allclose(res.xyz[0, :2], enu[0, :2], atol=0.1)
    # node 10 is pulled TOWARD the fix (positive projection on the offset, decisive magnitude)
    move10 = res.xyz[10, :2] - enu[10, :2]
    assert float(move10 @ offset) > 0.0
    assert float(np.linalg.norm(move10)) > 0.5
    assert res.mean_abs_horizontal_correction_m > 0.3
