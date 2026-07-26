"""[GATE3-P2] Two vehicles modifying ONE shared terrain region, with the conflict actually detected.

The prerequisite this proves solvable: STEWIE's fleet planner groups trips by site so no two vehicles
ever work the same ground, which makes its conflict count zero BY CONSTRUCTION
(``lode.planner_multivehicle._vehicle_conflicts``) and leaves ``lode.planner_sim`` with no terrain
reference at all. The world-state work needs the opposite: shared ground, real co-occupation, and the
resulting dependency made explicit.

The overlap these tests assert is the action-induced correlation set -- cells whose later observations
are dependent because two vehicles both changed them. That set is the primitive the promotion policy
needs; computing it is what makes the multi-robot half of the topic testable at all.

Real data only: the base surface is a window of the committed LOLA Haworth DEM.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.shared_terrain import (
    VehicleAction, apply_concurrent, correlation_mask, detect_shared_cells,
)
from stewie.twin.terrain_memory import TerrainMemory

_HEIGHT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m", "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

ROWS = COLS = 40
CELL_M = 5.0


def _real_base() -> np.ndarray:
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    return z.reshape(side, side)[900:900 + ROWS, 900:900 + COLS].astype(np.float64)


def _memory() -> TerrainMemory:
    return TerrainMemory(site="haworth_shared", rows=ROWS, cols=COLS, cell_m=CELL_M)


def _patch(r0: int, c0: int, r1: int, c1: int, v: float) -> np.ndarray:
    d = np.zeros((ROWS, COLS), dtype=np.float64)
    d[r0:r1, c0:c1] = v
    return d


def test_two_vehicles_on_the_same_ground_produce_a_detected_overlap():
    """The case the site-exclusive planner cannot represent: genuine co-occupation."""
    scout = VehicleAction("scout", _patch(10, 10, 20, 20, -0.10), t_start=0.0, t_end=100.0)
    excav = VehicleAction("excavator", _patch(15, 15, 25, 25, -0.40), t_start=50.0, t_end=200.0)

    c = detect_shared_cells([scout, excav])
    assert c["concurrent"] is True
    assert len(c["pairs"]) == 1
    # rows 15..19 x cols 15..19 = 25 cells are touched by BOTH
    assert c["n_correlated"] == 25
    assert c["pairs"][0]["overlap_window"] == (50.0, 100.0)


def test_disjoint_time_windows_are_not_concurrent_even_on_the_same_cells():
    """Same ground, different times, is sequential -- the terrain records both but the observations
    are not simultaneously dependent."""
    a = VehicleAction("scout", _patch(10, 10, 20, 20, -0.1), t_start=0.0, t_end=100.0)
    b = VehicleAction("excavator", _patch(10, 10, 20, 20, -0.3), t_start=100.0, t_end=200.0)
    c = detect_shared_cells([a, b])
    assert c["concurrent"] is False
    assert c["n_correlated"] == 0


def test_disjoint_ground_in_the_same_window_is_not_a_conflict():
    a = VehicleAction("scout", _patch(0, 0, 10, 10, -0.1), t_start=0.0, t_end=100.0)
    b = VehicleAction("excavator", _patch(30, 30, 40, 40, -0.3), t_start=0.0, t_end=100.0)
    c = detect_shared_cells([a, b])
    assert c["concurrent"] is False
    assert c["n_correlated"] == 0


def test_a_vehicle_never_conflicts_with_itself():
    a = VehicleAction("scout", _patch(10, 10, 20, 20, -0.1), t_start=0.0, t_end=100.0)
    b = VehicleAction("scout", _patch(10, 10, 20, 20, -0.1), t_start=10.0, t_end=110.0)
    assert detect_shared_cells([a, b])["concurrent"] is False


def test_concurrent_apply_conserves_mass_against_the_sum_of_actions():
    """Concurrent application must equal sequential application cell-wise: two vehicles each cutting
    0.1 m from a cell leave it 0.2 m lower. Conservation is not weakened by concurrency."""
    tm = _memory()
    scout = VehicleAction("scout", _patch(10, 10, 20, 20, -0.10), 0.0, 100.0, mass_moved_kg=90.0)
    excav = VehicleAction("excavator", _patch(15, 15, 25, 25, -0.40), 50.0, 200.0, mass_moved_kg=360.0)

    res = apply_concurrent(tm, [scout, excav], mission="shared01")
    expected = np.asarray(scout.delta) + np.asarray(excav.delta)
    assert np.allclose(tm.cumulative_delta(), expected, atol=0.0)
    # the doubly-cut overlap is exactly the sum of both cuts
    assert np.isclose(tm.cumulative_delta()[17, 17], -0.50)
    assert np.isclose(res["net_delta"].sum(), expected.sum())


def test_each_vehicles_contribution_stays_separately_recoverable():
    """P1 retention + P2 concurrency together: attribute the shared cells back to each vehicle."""
    tm = _memory()
    scout = VehicleAction("scout", _patch(10, 10, 20, 20, -0.10), 0.0, 100.0)
    excav = VehicleAction("excavator", _patch(15, 15, 25, 25, -0.40), 50.0, 200.0)
    res = apply_concurrent(tm, [scout, excav], mission="shared01")

    v_scout = res["versions"]["scout"]
    v_excav = res["versions"]["excavator"]
    assert np.allclose(tm.delta_at(v_scout), np.asarray(scout.delta), atol=0.0)
    assert np.allclose(tm.delta_at(v_excav), np.asarray(excav.delta), atol=0.0)
    # and the state before the excavator ran is recoverable
    base = _real_base()
    assert np.allclose(tm.height_at(base, v_scout), base + np.asarray(scout.delta), atol=0.0)
    assert tm.verify_chain()


def test_correlation_mask_marks_exactly_the_shared_cells():
    tm = _memory()
    scout = VehicleAction("scout", _patch(10, 10, 20, 20, -0.10), 0.0, 100.0)
    excav = VehicleAction("excavator", _patch(15, 15, 25, 25, -0.40), 50.0, 200.0)
    res = apply_concurrent(tm, [scout, excav], mission="shared01")

    m = correlation_mask(tm, res["conflicts"])
    assert m.sum() == 25
    assert m[15:20, 15:20].all()
    assert not m[10, 10] and not m[24, 24]      # touched by exactly one vehicle each


def test_three_vehicles_report_every_conflicting_pair():
    a = VehicleAction("a", _patch(10, 10, 20, 20, -0.1), 0.0, 100.0)
    b = VehicleAction("b", _patch(15, 15, 25, 25, -0.1), 0.0, 100.0)
    c = VehicleAction("c", _patch(18, 18, 30, 30, -0.1), 0.0, 100.0)
    out = detect_shared_cells([a, b, c])
    assert {tuple(sorted((p["a"], p["b"]))) for p in out["pairs"]} == {("a", "b"), ("a", "c"), ("b", "c")}


def test_malformed_actions_refuse():
    with pytest.raises(ValueError):
        VehicleAction("bad", _patch(0, 0, 5, 5, -0.1), t_start=10.0, t_end=0.0)
    with pytest.raises(ValueError):
        VehicleAction("bad", np.full((ROWS, COLS), np.nan), 0.0, 1.0)
    tm = _memory()
    with pytest.raises(ValueError):
        apply_concurrent(tm, [], mission="empty")
    with pytest.raises(ValueError):        # wrong grid shape for this site
        apply_concurrent(tm, [VehicleAction("v", np.zeros((5, 5)), 0.0, 1.0)], mission="m")
