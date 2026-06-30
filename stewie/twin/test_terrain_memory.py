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


def test_imprint_offset_uses_the_planner_add_convention_at_a_nonzero_anchor():  # #292
    """The planner maps a LOCAL order coord to a DEM pixel by ADDING dem_origin (planner_acceptance.py:
    cx=(ox+o.x)/dem_cell; comment "DEM meters where local (0,0) sits"). Terrain Memory's imprint must use
    the SAME sign, else the remembered as-built surface lands ~2*dem_origin away on every non-zero-anchor
    (real-Moon) plan. The bug was invisible because every prior imprint/as-built test used dem_origin=(0,0),
    the one value where +0 == -0."""
    cell = 5.0
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=cell, origin=(20.0, 20.0))
    tm.apply(_real_cut_delta(4, 4, cell, 0.2), mission="cut")    # a REAL conserved cut at local order (20,20)
    base = np.zeros((20, 20))
    anchor = (10.0, 30.0)                                        # a NON-zero planning anchor (dem_origin)
    out = tm.imprint_on_dem(base, dem_cell=cell, dem_origin=anchor)
    # planner ADD convention: DEM pixel = (order + dem_origin)/cell -> row=(20+30)/5=10, col=(20+10)/5=6
    r0 = int(round((20.0 + anchor[1]) / cell)); c0 = int(round((20.0 + anchor[0]) / cell))
    assert out[r0:r0 + 4, c0:c0 + 4].min() < 0.0, "imprint did not land at the planner ADD location (#292)"
    # the OLD subtract location (row=(20-30)/5=-2 clipped, col=(20-10)/5=2) must be untouched
    assert np.allclose(out[0:2, 2:6], 0.0), "imprint landed at the (wrong) subtract-convention location (#292)"
    # the coarse/resampled path must use the same ADD sign
    tmf = TerrainMemory(site="s", rows=10, cols=10, cell_m=cell / 2.0, origin=(20.0, 20.0))
    tmf.apply(_real_cut_delta(10, 10, cell / 2.0, 0.2), mission="cut")
    outr = tmf.imprint_on_dem_resampled(np.zeros((20, 20)), dem_cell=cell, dem_origin=anchor)
    assert outr[r0:r0 + 3, c0:c0 + 3].min() < 0.0              # lands at the ADD region (rows ~10, cols ~6)
    assert np.allclose(outr[0:3, 0:6], 0.0)                    # NOT at the subtract region


def test_imprint_rejects_cell_mismatch():
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=0.5)
    with pytest.raises(ValueError):
        tm.imprint_on_dem(np.zeros((6, 6)), dem_cell=1.0)


def test_imprint_on_dem_resampled_aggregates_fine_memory_onto_a_coarse_dem():
    # #242 read-back: a fine work-area memory (0.5 m) must add to a COARSE planning DEM (5 m). The 10x10
    # @0.5m memory (5x5 m) maps to ONE 5 m DEM cell; a uniform -0.2 m cut -> that cell drops by the MEAN
    # (-0.2). Mean is the VOLUME-CONSERVING downsample: mean*coarse_area == sum(fine)*fine_area.
    tm = TerrainMemory(site="s", rows=10, cols=10, cell_m=0.5, origin=(0.0, 0.0))
    tm.apply(np.full((10, 10), -0.2), mission="cut")
    base = np.full((4, 4), 100.0)                              # 4x4 DEM at 5 m
    cur = tm.imprint_on_dem_resampled(base, dem_cell=5.0, dem_origin=(0.0, 0.0))
    assert cur.shape == (4, 4)
    assert np.isclose(cur[0, 0], 99.8)                          # the memory block -> DEM cell (0,0), mean -0.2
    assert np.allclose(cur[1:, :], 100.0) and np.allclose(cur[0, 1:], 100.0)   # nothing elsewhere
    fine_vol = float(tm.cumulative_delta().sum()) * (0.5 ** 2)
    coarse_vol = float((cur - base).sum()) * (5.0 ** 2)
    assert abs(fine_vol - coarse_vol) < 1e-9                    # volume conserved across the resample
    assert np.allclose(base, 100.0)                            # base not mutated


def test_imprint_on_dem_resampled_conserves_volume_for_a_sub_cell_build():
    # a build SMALLER than one coarse DEM cell must NOT inflate volume: a 1 m x 1 m (2x2 @0.5m) +1.0 m berm
    # inside one 5 m DEM cell raises that cell by built_volume/coarse_area = 1.0 m^3 / 25 m^2 = 0.04 m,
    # NOT by 1.0 m (the mean over only the built fine-cells). This is the partial-tiling case the
    # capacity denominator fixes (council-caught: dividing by present-count over-stated moved volume).
    tm = TerrainMemory(site="s", rows=10, cols=10, cell_m=0.5, origin=(0.0, 0.0))
    d = np.zeros((10, 10)); d[0:2, 0:2] = 1.0                   # a 1 m x 1 m berm (4 fine cells) in cell (0,0)
    tm.apply(d, mission="berm")
    base = np.full((4, 4), 100.0)
    cur = tm.imprint_on_dem_resampled(base, dem_cell=5.0, dem_origin=(0.0, 0.0))
    fine_vol = float(tm.cumulative_delta().sum()) * (0.5 ** 2)  # 4 * 1.0 * 0.25 = 1.0 m^3
    coarse_vol = float((cur - base).sum()) * (5.0 ** 2)
    assert abs(fine_vol - coarse_vol) < 1e-9                    # volume conserved for the sub-cell build
    assert np.isclose(cur[0, 0], 100.04)                       # 0.04 m, not 1.0 m (would be the old bug)


def test_imprint_on_dem_resampled_equals_exact_when_cells_match():
    tm = TerrainMemory(site="s", rows=4, cols=4, cell_m=0.5, origin=(1.0, 1.0))
    tm.apply(np.full((4, 4), -0.1), mission="m")
    base = np.full((10, 10), 50.0)
    exact = tm.imprint_on_dem(base, dem_cell=0.5, dem_origin=(0.0, 0.0))
    resampled = tm.imprint_on_dem_resampled(base, dem_cell=0.5, dem_origin=(0.0, 0.0))
    assert np.allclose(exact, resampled)                        # equal cells -> identical to the exact path


def test_save_site_load_site_round_trip(tmp_path):
    import os

    from stewie.twin.terrain_memory import load_site, save_site, terrain_path
    assert load_site(str(tmp_path), "haworth") is None         # nothing recorded yet -> None (not an error)
    tm = TerrainMemory(site="haworth", rows=4, cols=4, cell_m=0.5)
    tm.apply(_real_cut_delta(4, 4, 0.5, 0.1), mission="m")
    p = save_site(str(tmp_path), tm)
    assert os.path.exists(p) and p == terrain_path(str(tmp_path), "haworth")
    back = load_site(str(tmp_path), "haworth")
    assert back is not None and back.version == 1 and back.verify_chain()
    assert np.allclose(back.cumulative_delta(), tm.cumulative_delta())


def test_save_is_atomic_a_failed_commit_keeps_the_prior_file(tmp_path, monkeypatch):
    """#277: TerrainMemory.save writes a .part then os.replace's it into place, so a crash/concurrent
    writer mid-write can never TORN the canonical .npz (as_built_dem would then silently discard all
    recorded memory). Guard: if the atomic commit (os.replace) fails mid-save, the PRIOR committed file is
    left intact -- pre-#277 the in-place np.savez overwrote the real file before any rename, corrupting it."""
    import os
    p = str(tmp_path / "haworth.npz")
    d = _real_cut_delta(8, 8, 1.0, 0.10)                       # a REAL conserved cut delta (no synthetic)
    v1 = TerrainMemory(site="haworth", rows=8, cols=8, cell_m=1.0, origin=(0.0, 0.0))
    v1.apply(d, mission="v1"); v1.save(p)
    committed = TerrainMemory.load(p).cumulative_delta().copy()

    v2 = TerrainMemory(site="haworth", rows=8, cols=8, cell_m=1.0, origin=(0.0, 0.0))
    v2.apply(d * 3.0, mission="v2")                            # a DIFFERENT surface
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("simulated crash")))
    with pytest.raises(OSError):
        v2.save(p)                                            # the commit fails AFTER writing the .part
    assert np.allclose(TerrainMemory.load(p).cumulative_delta(), committed), \
        "a failed save corrupted the prior committed terrain memory (#277)"
