"""W2 (Terrain Memory): mission_terrain_delta -- the conserved per-cell height delta a mission imprints on
the terrain, reusing validate_plan's rasterize->execute path on the conserved authority, then feeding it to
the world-model store (stewie.twin.terrain_memory.TerrainMemory).

No synthetic data: the delta is the conserved authority's output for a REAL mission (cut/fill orders on the
uniform regolith model, the same surface validate_plan's own tests use). The cross-check asserts the delta
IS the surface change validate_plan measured -- the two paths cannot silently diverge.

Run: <venv>/bin/python -m pytest lode/test_terrain_delta.py -q
"""
import numpy as np
import pytest

import lode.mission_planner as MP
from lode.planner_acceptance import mission_terrain_delta, validate_plan
from stewie.twin.terrain_memory import TerrainMemory


def _mission(orders):
    return MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0], "orders": orders})


def test_default_validate_plan_stays_grid_free_byte_identical():
    # the additive return_grids flag must NOT perturb the default result (existing callers + JSON serialization)
    m = _mission([{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.2}])
    assert "terrain_grids" not in validate_plan(m)


def test_mission_terrain_delta_is_consistent_with_validate_plan_as_built():
    m = _mission([{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.2}])
    d = mission_terrain_delta(m)
    # delta == as_built - base, exactly -- the SAME conserved run validate_plan measured (no divergence)
    assert np.allclose(d["delta"], d["as_built"] - d["base"])
    assert d["delta"].shape == (d["rows"], d["cols"])
    # a cut drops the surface: the worked region has negative delta, nothing rises
    assert d["delta"].min() < 0.0 and d["delta"].max() <= 1e-9
    assert d["mass_moved_kg"] > 0.0


def test_cut_and_fill_delta_signs():
    d = mission_terrain_delta(_mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.3},
        {"action": "pad", "kind": "fill", "x": 20.0, "y": 20.0, "footprint_m2": 16.0, "depth_m": 0.1},
    ]))
    assert d["delta"].min() < 0.0    # the cut lowered terrain
    assert d["delta"].max() > 0.0    # the fill raised terrain


def test_delta_feeds_terrain_memory_apply():
    # the W1<->W2 seam: a mission's conserved delta folds into the authoritative world model
    m = _mission([{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.2}])
    d = mission_terrain_delta(m)
    tm = TerrainMemory(site="haworth", rows=d["rows"], cols=d["cols"], cell_m=d["cell_m"],
                       origin=(d["x0"], d["y0"]))
    tm.apply(d["delta"], mission="src-pad", mass_moved_kg=d["mass_moved_kg"])
    assert tm.version == 1 and tm.verify_chain()
    # the memory's net volume equals the conserved delta's net volume
    assert tm.summary()["net_volume_m3"] == pytest.approx(float(d["delta"].sum()) * d["cell_m"] ** 2, abs=1e-6)
    assert tm.summary()["max_cut_m"] > 0.0


def test_record_mission_folds_two_missions_into_one_site_at_separate_places():
    from stewie.twin.terrain_memory import TerrainMemory
    from lode.planner_acceptance import record_mission
    # a site big enough to contain both missions' footprints (incl. validate_plan's bbox margin) without clip
    site = TerrainMemory(site="haworth", rows=120, cols=120, cell_m=0.5, origin=(-10.0, -10.0))
    r1 = record_mission(site, _mission([
        {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.2}]))
    assert r1["version"] == 1 and r1["placed_cells"] > 0 and r1["clipped"] is False
    r2 = record_mission(site, _mission([
        {"action": "src", "kind": "cut", "x": 25.0, "y": 25.0, "footprint_m2": 36.0, "depth_m": 0.15}]))
    assert r2["version"] == 2 and site.verify_chain()
    d = site.cumulative_delta()
    # each cut lands at its own mapped centre: (5,5)->cell ~30, (25,25)->cell ~70 (origin -10, cell 0.5)
    assert d[30, 30] < 0.0 and d[70, 70] < 0.0          # both cuts present, in separate regions
    assert site.summary()["missions"] == ["S", "S"] and site.summary()["max_cut_m"] > 0.0


def test_plan_sees_remembered_terrain_after_imprint():
    import numpy as np
    from stewie.twin.terrain_memory import TerrainMemory
    from lode.planner_acceptance import record_mission, validate_plan
    base = np.full((120, 120), 100.0)                          # flat base DEM, cell 0.5, origin (0,0) -> 60 m
    site = TerrainMemory(site="haworth", rows=120, cols=120, cell_m=0.5, origin=(0.0, 0.0))
    # record a real cut -> the world model remembers a hole at (15,15)
    record_mission(site, _mission([
        {"action": "src", "kind": "cut", "x": 15.0, "y": 15.0, "footprint_m2": 36.0, "depth_m": 0.5}]),
        dem=(base, 0.5), dem_origin=(0.0, 0.0))
    assert site.summary()["max_cut_m"] > 0.0
    remembered = site.imprint_on_dem(base, dem_cell=0.5, dem_origin=(0.0, 0.0))
    assert remembered.min() < 100.0 and np.isclose(remembered[0, 0], 100.0)   # lower where built, else pristine
    # the PAYOFF: a NEW plan validates against the remembered surface, not the pristine DEM
    r = validate_plan(_mission([
        {"action": "pad", "kind": "cut", "x": 15.0, "y": 15.0, "footprint_m2": 36.0, "depth_m": 0.1}]),
        dem=(remembered, 0.5), dem_origin=(0.0, 0.0))
    assert r["as_built_on_real_dem"] is True
