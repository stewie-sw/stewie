"""#242 read-back: _plan_impl plans on the AS-BUILT remembered surface (graphify INT-016/INT-046). The
_as_built_dem helper imprints a site's recorded TerrainMemory (resampled to the coarse planning-DEM cell)
so a SECOND mission routes/validates against what prior missions actually built; no memory -> the pristine
DEM; a None DEM (non-Moon body) passes through; a bad/mismatched memory must fall back, never fail a plan."""
import numpy as np
import pytest

from stewie.server.routers.plan import _as_built_dem
from stewie.twin import terrain_memory as TM


def test_as_built_imprints_recorded_memory_onto_the_coarse_dem(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    # a recorded +0.5 m berm at 0.5 m over a 10x10 site (5x5 m) at origin (0,0)
    mem = TM.TerrainMemory(site="rb", rows=10, cols=10, cell_m=0.5, origin=(0.0, 0.0))
    mem.apply(np.full((10, 10), 0.5), mission="berm")
    TM.save_site(str(tmp_path), mem)
    base_z = np.full((4, 4), 100.0)                       # 4x4 planning DEM at 5 m
    z2, cell = _as_built_dem("rb", (base_z, 5.0), (0.0, 0.0))
    assert cell == 5.0
    assert np.isclose(z2[0, 0], 100.5)                    # the berm raised the DEM cell the memory maps to
    assert np.allclose(z2[1:, :], 100.0) and np.allclose(z2[0, 1:], 100.0)   # untouched elsewhere
    assert np.allclose(base_z, 100.0)                     # base not mutated (a 2nd plan still sees pristine if asked)


def test_as_built_no_memory_is_pristine(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    base_z = np.full((4, 4), 100.0)
    z, cell = _as_built_dem("nosuch", (base_z, 5.0), (0.0, 0.0))
    assert np.array_equal(z, base_z) and cell == 5.0      # no recorded build -> pristine, unchanged


def test_as_built_none_dem_passthrough(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    assert _as_built_dem("x", None, (0.0, 0.0)) is None   # non-Moon body (no DEM) -> passthrough


import os  # noqa: E402

_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "samples", "lunar_dem", "haworth_10km_5m")


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth bundle absent")
def test_observed_twin_overlays_planning_surface_where_measured(monkeypatch, tmp_path):
    """#280: the planning surface is OBSERVED-where-measured > as-built > pristine. A durable resync patch
    in the perception TwinStore must override the planning DEM at the cells it MEASURED, while unmeasured
    cells fall back to pristine (here, no as-built memory). An empty twin is a no-op (back-compat with
    #242/#267). Real Haworth tile; the observed patch is a controlled +5 m perturbation of the real DEM."""
    import importlib

    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from lode import mission_planner as MP
    from stewie.server import state
    importlib.reload(state)                               # fresh _TWIN + DEM caches under the tmp data dir

    z0, cell = MP.load_haworth_dem()                      # the real tile == twin().base grid (1:1)
    origin = (0.0, 0.0)
    # (a) no resync recorded -> as_built_dem is pristine (no as-built memory, empty observed twin)
    z_base, _ = state.as_built_dem("haworth", (z0.copy(), cell), origin)
    assert np.array_equal(z_base, z0), "empty twin must be a no-op (#280 back-compat)"
    # (b) record a real perception resync: a 4x4 measured region 5 m above the pristine surface
    r0, c0 = 100, 200
    observed = z0[r0:r0 + 4, c0:c0 + 4] + 5.0
    state.twin().apply_patch(observed, origin_rc=(r0, c0), provenance="test resync")
    z_obs, _ = state.as_built_dem("haworth", (z0.copy(), cell), origin)
    assert np.allclose(z_obs[r0:r0 + 4, c0:c0 + 4], observed), "measured region must reflect the observed surface"
    outside = np.ones(z0.shape, dtype=bool); outside[r0:r0 + 4, c0:c0 + 4] = False
    assert np.array_equal(z_obs[outside], z0[outside]), "unmeasured cells must fall back to pristine"
    importlib.reload(state)                               # restore the default module for other tests
