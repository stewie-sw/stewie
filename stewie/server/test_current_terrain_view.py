"""Step 2 (gap A2): state.current_terrain_view gathers the layer inputs (the site's recorded
TerrainMemory + the observed twin) and composes the one typed CurrentTerrainView, while
state.as_built_dem keeps its (z, cell) contract by returning the view's heights.

The as-built layer is checked on a small grid (cheap); the both-layers precedence + provenance on the
real Haworth tile (skipped if the bundle is absent), mirroring test_as_built_readback's overlay test.
"""
from __future__ import annotations

import importlib
import os

import numpy as np
import pytest

from stewie.twin import terrain_memory as TM
from stewie.twin.terrain_view import CurrentTerrainView

_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "samples", "lunar_dem", "haworth_10km_5m")


def test_view_tags_as_built_cells_and_retains_version(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state
    mem = TM.TerrainMemory(site="rb", rows=10, cols=10, cell_m=0.5, origin=(0.0, 0.0))
    mem.apply(np.full((10, 10), 0.5), mission="berm")     # a recorded +0.5 m build (version -> 1)
    TM.save_site(str(tmp_path), mem)
    base_z = np.full((4, 4), 100.0)
    view = state.current_terrain_view("rb", (base_z, 5.0), (0.0, 0.0))
    assert view is not None
    assert np.isclose(view.heights[0, 0], 100.5)          # the berm raised the mapped cell
    assert view.source[0, 0] == CurrentTerrainView.AS_BUILT
    assert (view.source[1:, :] == CurrentTerrainView.PRISTINE).all()
    assert view.as_built_version == 1                     # provenance retained
    assert view.twin_version == 0 and view.observed_fraction == 0.0
    assert np.allclose(base_z, 100.0)                     # caller's base never mutated


def test_current_terrain_view_reads_the_twin_under_the_resync_lock(monkeypatch, tmp_path):
    """[REQ:DT-06] The observed-twin READ holds state._RESYNC_LOCK, so a concurrent twin_resync
    (apply_patch..world-log-commit..compensating undo) can't be observed mid-rollback -- a dirty read of a
    patch that is about to be undone. We spy on the lock inside the twin read to prove it is held. (The WRITE
    half + the same-lock proof are in test_dt06_resync_consistency.py; together = no torn read.)"""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state
    z = np.zeros((4, 4))
    held = {"locked": None}

    class _FakeTwin:
        base = z
        version = 0

        def observed_mask(self):
            held["locked"] = state._RESYNC_LOCK.locked()   # the resync lock MUST be held while reading the twin
            return np.zeros((4, 4), dtype=bool)

        def current(self):
            return z

    monkeypatch.setattr(state, "twin", lambda *a, **k: _FakeTwin())
    state.current_terrain_view("rb", (z, 5.0), (0.0, 0.0))
    assert held["locked"] is True


def test_as_built_dem_matches_the_view_heights(monkeypatch, tmp_path):
    """as_built_dem (z, cell) parity: it IS the view's composed heights -- one composition path."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state
    mem = TM.TerrainMemory(site="rb", rows=10, cols=10, cell_m=0.5, origin=(0.0, 0.0))
    mem.apply(np.full((10, 10), 0.5), mission="berm")
    TM.save_site(str(tmp_path), mem)
    base_z = np.full((4, 4), 100.0)
    z, cell = state.as_built_dem("rb", (base_z, 5.0), (0.0, 0.0))
    view = state.current_terrain_view("rb", (base_z, 5.0), (0.0, 0.0))
    assert np.array_equal(z, view.heights) and cell == view.cell_m


def test_none_dem_passthrough(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state
    assert state.current_terrain_view("x", None, (0.0, 0.0)) is None
    assert state.as_built_dem("x", None, (0.0, 0.0)) is None   # contract preserved


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth bundle absent")
def test_observed_wins_over_as_built_on_real_tile(monkeypatch, tmp_path):
    """On the real Haworth tile: a recorded as-built build AND a measured observed patch both appear in
    the view, observed wins where they overlap, and provenance (versions + observed fraction) is set."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from lode import mission_planner as MP
    from stewie.server import state
    importlib.reload(state)                               # fresh _TWIN + DEM caches under the tmp data dir
    z0, cell = MP.load_haworth_dem()
    # an as-built memory over the full tile: +0.3 m everywhere (so every cell is AS_BUILT before observe)
    mem = TM.TerrainMemory(site="haworth", rows=z0.shape[0], cols=z0.shape[1], cell_m=cell,
                           origin=(0.0, 0.0))
    mem.apply(np.full(z0.shape, 0.3), mission="pad")
    TM.save_site(str(tmp_path), mem)
    r0, c0 = 100, 200                                     # a measured 4x4 region, observed +5 m vs pristine
    state.twin().apply_patch(z0[r0:r0 + 4, c0:c0 + 4] + 5.0, origin_rc=(r0, c0), provenance="resync")
    view = state.current_terrain_view("haworth", (z0.copy(), cell), (0.0, 0.0))
    assert view.as_built_version == 1 and view.twin_version >= 1
    assert view.source[r0, c0] == CurrentTerrainView.OBSERVED          # observed wins in the measured region
    assert np.isclose(view.heights[r0, c0], z0[r0, c0] + 5.0)
    assert view.source[0, 0] == CurrentTerrainView.AS_BUILT            # as-built elsewhere
    assert np.isclose(view.heights[0, 0], z0[0, 0] + 0.3)
    assert 0.0 < view.observed_fraction < 1.0
    importlib.reload(state)                               # restore default module for other tests
