"""P1 degeneracy gates from the architectural review: silent-wrong-output -> explicit rejection."""
import numpy as np
import pytest

from dart.geometry import dem
from dissertation import posegraph as pg
from dart import positioning as pos
from stewie.physics import sinkage as sk


# HIGH-05: collinear trilateration must raise, not return a min-norm wrong answer
def test_trilaterate_rejects_collinear():
    with pytest.raises(ValueError, match="rank-deficient"):
        pos.trilaterate([[0, 0], [1, 0], [2, 0]], [2.5, 1.8, 2.5])
    # well-conditioned (triangle) geometry still solves
    x = pos.trilaterate([[0, 0], [4, 0], [0, 3]], [5.0, 5.0, 4.0])
    assert x.shape == (2,) and np.all(np.isfinite(x))


def test_trilaterate_length_mismatch_raises():
    with pytest.raises(ValueError, match="equal length"):
        pos.trilaterate([[0, 0], [4, 0], [0, 3]], [5.0, 5.0])


# HIGH-06 / MED-04: DEM registration is NaN-safe and rejects flat patches
def test_dem_register_nan_safe():
    rng = np.random.default_rng(0)
    big = rng.normal(0, 5, (40, 40))
    c0 = (40 - 12) // 2                        # the centered patch -> true offset (0, 0)
    patch = big[c0:c0 + 12, c0:c0 + 12].copy()
    patch[5, 5] = np.nan                       # a PSR no-data cell in the patch
    dr, dc, rmse = dem.register_to_dem(patch, big, search_radius_cells=4)
    assert np.isfinite(rmse) and (dr, dc) == (0, 0)   # NaN cell does not poison the true match


def test_dem_register_rejects_flat_patch():
    with pytest.raises(ValueError, match="relief"):
        dem.register_to_dem(np.full((12, 12), 7.0), np.zeros((40, 40)))


# MED-09: pose-graph degenerate-geometry + empty-graph guards
def test_posegraph_landmark_at_pose_raises():
    g = pg.PoseGraph(); g.add_prior(0, [0, 0, 0])
    g.add_landmark(0, [0.0, 0.0], 0.0, info=100.0)    # landmark coincident with the pose
    with pytest.raises(ValueError, match="degenerate landmark"):
        g.solve(np.array([[0.0, 0.0, 0.0]]))


def test_posegraph_empty_graph_raises():
    with pytest.raises(ValueError, match="empty pose graph"):
        pg.PoseGraph().solve(np.array([[0.0, 0.0, 0.0]]))


# MED-12: terramechanics input guards (no complex sinkage, no div-by-zero, density clamp)
def test_sinkage_input_guards():
    with pytest.raises(ValueError):
        sk.contact_pressure(100.0, 0.0, 0.1)           # zero patch dimension
    assert sk.bekker_sinkage(-5.0, b_m=0.18) == 0.0    # negative pressure -> 0 (no complex root)
    assert sk.bekker_sinkage(0.0, b_m=0.18) == 0.0
    # density_factor < 1 is clamped to 1 (compaction only stiffens)
    z_loose = sk.bekker_sinkage(5000.0, b_m=0.18, density_factor=0.2)
    z_unit = sk.bekker_sinkage(5000.0, b_m=0.18, density_factor=1.0)
    assert z_loose == z_unit
    with pytest.raises(ValueError):
        sk.static_load_per_contact(30.0, n_contacts=0)
