"""Terrain Memory (world model) -- the authoritative per-site terrain state that accumulates the
mass-conserving per-cell changes of every applied mission, versioned + hash-chained + persisted.

No synthetic data: every delta fed to the store is produced by the REAL conserved authority
(stewie.physics.column_state.ColumnState), i.e. an actual cut through the mass-conserving model, not a
fabricated array. That is what a real mission would hand the world model.

Run: <venv>/bin/python -m pytest stewie/twin/test_terrain_memory.py -q
"""
import numpy as np
import pytest

from stewie.physics.column_state import ColumnState
from stewie.specs import constants as K
from stewie.twin.terrain_memory import TerrainMemory


def _real_cut_delta(rows: int, cols: int, cell_m: float, depth_m: float) -> np.ndarray:
    """A REAL conserved per-cell height delta: build a thick ColumnState, cut ``depth_m`` over a 2x2
    footprint via the conserved authority, return derive_height(after) - derive_height(before). The cut
    removes depth_m*density kg/m^2, so the surface drops exactly depth_m over the footprint (negative)."""
    cs = ColumnState(width=cols, height=rows, cell_m=cell_m,
                     mass_areal=np.full((rows, cols), K.RHO_SURFACE * 5.0, dtype=np.float64))  # 5 m thick -> no datum floor
    before = cs.derive_height().copy()
    mask = np.zeros((rows, cols), dtype=bool)
    mask[1:3, 1:3] = True                                   # a real 2x2 worked footprint
    cs.cut_to_inventory(mask, depth_m * K.RHO_SURFACE)      # conserved removal -> surface drops depth_m
    return cs.derive_height() - before                      # negative over the cut cells, 0 elsewhere


def test_apply_accumulates_real_conserved_delta_and_versions():
    tm = TerrainMemory(site="haworth", rows=4, cols=4, cell_m=0.5)
    d1 = _real_cut_delta(4, 4, 0.5, 0.10)
    assert tm.apply(d1, mission="pad-A", mass_moved_kg=123.0) == 1 and tm.version == 1
    assert np.allclose(tm.cumulative_delta(), d1)
    s = tm.summary()
    assert s["cells_changed"] == 4 and s["max_cut_m"] == pytest.approx(0.10, abs=1e-6) and s["max_fill_m"] == 0.0
    # a SECOND mission ACCUMULATES -- the terrain remembers the first
    d2 = _real_cut_delta(4, 4, 0.5, 0.05)
    assert tm.apply(d2, mission="pad-B") == 2
    assert np.allclose(tm.cumulative_delta(), d1 + d2)
    assert tm.summary()["missions"] == ["pad-A", "pad-B"]
    assert tm.summary()["max_cut_m"] == pytest.approx(0.15, abs=1e-6)   # the two cuts stack at the footprint


def test_current_height_is_base_plus_accumulated():
    tm = TerrainMemory(site="s", rows=3, cols=3, cell_m=1.0)
    base = np.full((3, 3), 100.0)
    d = _real_cut_delta(3, 3, 1.0, 0.2)
    tm.apply(d, mission="m")
    assert np.allclose(tm.current_height(base), base + d)            # world surface = base DEM + memory


def test_net_volume_matches_the_conserved_delta():
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=0.5)
    d = _real_cut_delta(4, 4, 0.5, 0.10)
    tm.apply(d, mission="m")
    expected_m3 = float(d.sum()) * (0.5 * 0.5)                       # 4 cells * 0.25 m^2 * -0.10 m
    assert tm.summary()["net_volume_m3"] == pytest.approx(expected_m3, abs=1e-6)
    assert tm.chain[-1]["net_volume_m3"] == pytest.approx(expected_m3, abs=1e-6)


def test_provenance_chain_verifies_and_detects_tamper():
    tm = TerrainMemory(site="s", rows=3, cols=3, cell_m=1.0)
    tm.apply(_real_cut_delta(3, 3, 1.0, 0.1), mission="m1")
    tm.apply(_real_cut_delta(3, 3, 1.0, 0.1), mission="m2")
    assert tm.verify_chain()
    tm.chain[0]["mission"] = "tampered"                             # edit a committed record
    assert not tm.verify_chain()


def test_persistence_round_trips(tmp_path):
    tm = TerrainMemory(site="haworth", rows=4, cols=4, cell_m=0.5, origin=(10.0, 20.0))
    tm.apply(_real_cut_delta(4, 4, 0.5, 0.15), mission="pad-A", mass_moved_kg=99.0)
    p = str(tmp_path / "haworth.npz")
    tm.save(p)
    cold = TerrainMemory.load(p)
    assert cold.site == "haworth" and cold.version == 1 and cold.origin == (10.0, 20.0)
    assert np.allclose(cold.cumulative_delta(), tm.cumulative_delta())
    assert cold.verify_chain() and cold.summary()["missions"] == ["pad-A"]


def test_apply_rejects_mismatched_or_nonfinite_delta():
    tm = TerrainMemory(site="s", rows=3, cols=3, cell_m=1.0)
    with pytest.raises(ValueError):
        tm.apply(np.zeros((2, 2)), mission="bad-shape")
    bad = np.zeros((3, 3))
    bad[0, 0] = np.inf
    with pytest.raises(ValueError):
        tm.apply(bad, mission="bad-nonfinite")


def test_constructor_rejects_bad_grid():
    with pytest.raises(ValueError):
        TerrainMemory(site="s", rows=0, cols=3, cell_m=1.0)
    with pytest.raises(ValueError):
        TerrainMemory(site="s", rows=3, cols=3, cell_m=0.0)


def test_apply_subgrid_places_local_delta_at_the_global_offset():
    # site grid 8x8 at origin (0,0), cell 0.5 -> a local 2x2 mission delta at sub_origin (1.0, 1.5) lands at
    # col_off=round(1.0/0.5)=2, row_off=round(1.5/0.5)=3 (x->col, y->row), nothing elsewhere.
    tm = TerrainMemory(site="haworth", rows=8, cols=8, cell_m=0.5, origin=(0.0, 0.0))
    res = tm.apply_subgrid(np.full((2, 2), -0.1), sub_origin=(1.0, 1.5), cell_m=0.5, mission="pad")
    assert res == {"version": 1, "placed_cells": 4, "clipped": False}
    d = tm.cumulative_delta()
    assert np.allclose(d[3:5, 2:4], -0.1) and np.count_nonzero(np.abs(d) > 1e-9) == 4


def test_apply_subgrid_clips_a_mission_partly_outside_the_site():
    # a 3x3 delta at offset (2,2) of a 4x4 site: only the 2x2 overlap [2:4,2:4] lands; the rest is clipped
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=1.0, origin=(0.0, 0.0))
    res = tm.apply_subgrid(np.full((3, 3), 0.2), sub_origin=(2.0, 2.0), cell_m=1.0, mission="edge")
    assert res["clipped"] is True and res["placed_cells"] == 4
    assert np.allclose(tm.cumulative_delta()[2:4, 2:4], 0.2)


def test_apply_subgrid_rejects_cell_mismatch():
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=0.5)
    with pytest.raises(ValueError):
        tm.apply_subgrid(np.zeros((2, 2)), sub_origin=(0.0, 0.0), cell_m=1.0, mission="m")


def test_imprint_on_dem_adds_memory_to_a_larger_base_surface():
    # memory over a 4x4 site at order-frame origin (1.0, 1.0), cell 0.5; a base DEM 10x10 at origin (0,0)
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=0.5, origin=(1.0, 1.0))
    tm.apply(_real_cut_delta(4, 4, 0.5, 0.2), mission="m")      # real conserved cut -> negative over its 2x2
    base = np.full((10, 10), 100.0)
    cur = tm.imprint_on_dem(base, dem_cell=0.5, dem_origin=(0.0, 0.0))
    # offset round((1-0)/0.5)=2 -> memory occupies cur[2:6,2:6]; the cut lowered the surface there
    assert cur.shape == (10, 10) and cur[2:6, 2:6].min() < 100.0
    assert np.allclose(cur[0, 0], 100.0)                        # untouched away from the memory
    assert np.allclose(base, 100.0)                            # base DEM not mutated (returns a copy)


def test_imprint_rejects_cell_mismatch():
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=0.5)
    with pytest.raises(ValueError):
        tm.imprint_on_dem(np.zeros((6, 6)), dem_cell=1.0)
