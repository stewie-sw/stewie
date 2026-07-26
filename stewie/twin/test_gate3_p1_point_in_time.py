"""[GATE3-P1] Point-in-time query over Terrain Memory, on the real Haworth LOLA DEM.

The prerequisite this proves solvable: before per-mission retention, ``TerrainMemory.apply`` folded
each mission's grid into a single accumulated ``_delta`` and kept only scalar metadata, so the
question the world-state design poses -- "what did we believe before mission N" -- was
UNANSWERABLE from persisted state. These tests answer it, across a save/load cycle, on real terrain.

Real data only: the base surface is a window of the committed LOLA Haworth DEM
(samples/lunar_dem/haworth_10km_5m). The per-mission deltas are cut/fill patterns applied to that
real surface, which is what the conserved authority produces; no terrain is synthesised.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from stewie.twin.terrain_memory import TerrainMemory

_DEM = os.path.join(os.path.dirname(__file__), "..", "..", "samples", "lunar_dem", "haworth_10km_5m")
_HEIGHT = os.path.abspath(os.path.join(_DEM, "heightmap.rf32"))

pytestmark = pytest.mark.skipif(not os.path.exists(_HEIGHT),
                                reason="real Haworth DEM not present on this host")

ROWS = COLS = 48
CELL_M = 5.0


def _real_base() -> np.ndarray:
    """A ROWSxCOLS window of the REAL Haworth heightmap (2000x2000 float32, row-major)."""
    z = np.fromfile(_HEIGHT, dtype=np.float32)
    side = int(round(float(np.sqrt(z.size))))
    z = z.reshape(side, side)
    return z[800:800 + ROWS, 800:800 + COLS].astype(np.float64)


def _memory() -> TerrainMemory:
    return TerrainMemory(site="haworth_gate3", rows=ROWS, cols=COLS, cell_m=CELL_M)


def _cut(r: int, c: int, depth: float) -> np.ndarray:
    """A localised cut: negative delta over an 8x8 footprint, as an excavation produces."""
    d = np.zeros((ROWS, COLS), dtype=np.float64)
    d[r:r + 8, c:c + 8] = -depth
    return d


def test_before_and_after_a_dig_are_both_recoverable_on_real_terrain():
    """The load-bearing case: reconstruct the surface BEFORE mission N after later missions ran."""
    base = _real_base()
    tm = _memory()
    tm.apply(_cut(4, 4, 0.30), mission="m1", mass_moved_kg=100.0)
    before_m2 = tm.current_height(base).copy()          # truth captured live
    tm.apply(_cut(20, 20, 0.55), mission="m2", mass_moved_kg=180.0)
    tm.apply(_cut(32, 8, 0.20), mission="m3", mass_moved_kg=60.0)

    # version 1 == the state after m1, i.e. immediately BEFORE m2
    assert np.allclose(tm.height_at(base, 1), before_m2, atol=0.0)
    # and it is genuinely different from the current surface
    assert not np.allclose(tm.height_at(base, 1), tm.current_height(base))
    # pristine base is recoverable at version 0
    assert np.allclose(tm.height_at(base, 0), base, atol=0.0)


def test_point_in_time_survives_a_save_load_cycle(tmp_path):
    """'From persisted state' is the actual requirement: a restart must not lose the past."""
    base = _real_base()
    tm = _memory()
    tm.apply(_cut(4, 4, 0.30), mission="m1")
    before_m2 = tm.current_height(base).copy()
    tm.apply(_cut(20, 20, 0.55), mission="m2")

    p = str(tmp_path / "haworth_gate3.npz")
    tm.save(p)
    back = TerrainMemory.load(p)

    assert back.history_len == 2
    assert np.allclose(back.height_at(base, 1), before_m2, atol=0.0)
    assert np.allclose(back.cumulative_delta_at(2), tm.cumulative_delta(), atol=0.0)
    assert back.verify_chain()


def test_retained_history_reconstructs_the_accumulated_state_exactly():
    """Sum of retained per-mission deltas must equal the independently accumulated grid."""
    tm = _memory()
    for i, (r, c, d) in enumerate([(2, 2, 0.1), (12, 30, 0.4), (30, 12, 0.25), (40, 40, 0.6)]):
        tm.apply(_cut(r, c, d), mission=f"m{i}")
    assert tm.history_len == 4
    assert np.allclose(tm.cumulative_delta_at(4), tm.cumulative_delta(), atol=0.0)


def test_revert_to_rolls_state_and_chain_back():
    """Rollback of world state is only possible BECAUSE the per-mission grids are retained."""
    base = _real_base()
    tm = _memory()
    tm.apply(_cut(4, 4, 0.30), mission="m1")
    after_m1 = tm.current_height(base).copy()
    tm.apply(_cut(20, 20, 0.55), mission="m2")
    assert tm.version == 2

    tm.revert_to(1)
    assert tm.version == 1
    assert tm.history_len == 1
    assert len(tm.chain) == 1
    assert np.allclose(tm.current_height(base), after_m1, atol=0.0)
    assert tm.verify_chain()


def test_out_of_range_versions_refuse_rather_than_invent():
    tm = _memory()
    tm.apply(_cut(4, 4, 0.1), mission="m1")
    for bad in (2, -1):
        with pytest.raises(ValueError):
            tm.cumulative_delta_at(bad)
    with pytest.raises(ValueError):
        tm.delta_at(0)          # deltas are 1-based; version 0 is the pristine base, not a mission


def test_legacy_npz_without_history_loads_with_an_empty_history(tmp_path):
    """A pre-retention file must load and REFUSE point-in-time rather than fabricate past states."""
    import json as _json
    p = str(tmp_path / "legacy.npz")
    meta = {"site": "legacy", "rows": ROWS, "cols": COLS, "cell_m": CELL_M,
            "origin": [0.0, 0.0], "version": 1, "chain": []}
    with open(p, "wb") as f:                    # written WITHOUT the hist_* keys, as the old save did
        np.savez(f, delta=np.zeros((ROWS, COLS)), meta=_json.dumps(meta))
    back = TerrainMemory.load(p)
    assert back.history_len == 0
    with pytest.raises(ValueError):
        back.cumulative_delta_at(1)


def test_sparse_retention_is_cheap_relative_to_dense(tmp_path):
    """Retention must not blow up storage: a dig touches a small fraction of the grid."""
    tm = _memory()
    for i in range(12):
        tm.apply(_cut(2 + i * 3, 2 + i * 3, 0.2), mission=f"m{i}")
    p = str(tmp_path / "sparse.npz")
    tm.save(p)
    on_disk = os.path.getsize(p)
    dense_equivalent = ROWS * COLS * 8 * 12          # what 12 full float64 grids would cost
    assert tm.history_len == 12
    assert on_disk < dense_equivalent, (on_disk, dense_equivalent)
