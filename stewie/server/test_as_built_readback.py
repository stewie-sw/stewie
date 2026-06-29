"""#242 read-back: _plan_impl plans on the AS-BUILT remembered surface (graphify INT-016/INT-046). The
_as_built_dem helper imprints a site's recorded TerrainMemory (resampled to the coarse planning-DEM cell)
so a SECOND mission routes/validates against what prior missions actually built; no memory -> the pristine
DEM; a None DEM (non-Moon body) passes through; a bad/mismatched memory must fall back, never fail a plan."""
import numpy as np

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
