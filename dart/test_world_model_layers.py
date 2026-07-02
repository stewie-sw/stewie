"""[REQ:AS-10] layered world-model acceptance (§25 Phase 8): the mapper updates the observed layer
from observations only, and truth / observed / forecast / edited stay SEPARATE (an update to one
never mutates another). Uses the real crater_boulders conserved DEM (no synthetic elevation)."""
import inspect
import os

import numpy as np
import pytest

from dart.world_model_layers import LAYERS, WorldModelLayers, WorldStateGrid

_SAMPLE = os.path.join(os.path.dirname(__file__), "..", "samples", "crater_boulders")
_DEM = os.path.join(_SAMPLE, "heightmap.rf32")


def _real_dem_window(n=64):
    if not os.path.exists(_DEM):
        pytest.skip("crater_boulders DEM not present")
    full = np.fromfile(_DEM, dtype="<f4").reshape(256, 256).astype(float)
    return full[96:96 + n, 96:96 + n].copy()      # a real 64x64 crater region


def _real_field_window(name, dtype="<f4", n=64):
    path = os.path.join(_SAMPLE, name)
    if not os.path.exists(path):
        pytest.skip(f"crater_boulders {name} not present")
    kind = np.uint8 if dtype == "u1" else float
    full = np.fromfile(path, dtype=dtype).reshape(256, 256)
    return full[96:96 + n, 96:96 + n].astype(kind).copy()


def _equal_nan(a, b):
    return np.array_equal(a, b, equal_nan=True)


def test_update_observed_takes_no_truth_input():
    params = set(inspect.signature(WorldModelLayers.update_observed).parameters)
    for forbidden in ("truth", "gt", "ground_truth", "pose", "slip"):
        assert forbidden not in params, f"observed-update path exposes a truth field: {forbidden}"


def test_layers_are_separate_backing_arrays():
    dem = _real_dem_window()
    wm = WorldModelLayers(dem.shape, cell_m=0.02)
    wm.set_truth(dem)
    wm.set_forecast(dem - 0.05)                    # a planned 5 cm cut everywhere (real DEM derived)
    truth0, fc0 = wm.layer("truth"), wm.layer("forecast")

    # the mapper observed only a central sub-window (partial coverage), with the real DEM elevation there
    obs = np.full(dem.shape, np.nan)
    obs[16:48, 16:48] = dem[16:48, 16:48]
    wm.update_observed(obs)
    wm.apply_edit(np.full(dem.shape, dem[0, 0] + 1.0), mask=(np.arange(dem.size).reshape(dem.shape) == 0))

    # observed + edited updates left truth and forecast byte-identical (separate storage)
    assert _equal_nan(wm.layer("truth"), truth0)
    assert _equal_nan(wm.layer("forecast"), fc0)
    # mutating a returned copy does not reach into the store
    g = wm.layer("truth"); g[:] = -999.0
    assert _equal_nan(wm.layer("truth"), truth0)


def test_observed_is_partial_and_distinct_from_full_truth():
    dem = _real_dem_window()
    wm = WorldModelLayers(dem.shape)
    wm.set_truth(dem)
    obs = np.full(dem.shape, np.nan); obs[16:48, 16:48] = dem[16:48, 16:48]
    wm.update_observed(obs)
    assert wm.coverage_frac("truth") == 1.0
    assert 0.0 < wm.coverage_frac("observed") < 1.0          # a partial observation, not the whole truth
    assert int(wm.observed_count.max()) >= 1


def test_edit_touches_only_the_edited_layer():
    dem = _real_dem_window()
    wm = WorldModelLayers(dem.shape)
    wm.set_truth(dem)
    obs = np.full(dem.shape, np.nan); obs[16:48, 16:48] = dem[16:48, 16:48]
    wm.update_observed(obs)
    obs0 = wm.layer("observed")
    m = np.zeros(dem.shape, bool); m[0, 0] = True
    wm.apply_edit(np.full(dem.shape, 99.0), mask=m)
    assert wm.layer("edited")[0, 0] == 99.0
    assert _equal_nan(wm.layer("observed"), obs0)            # the edit did not bleed into observed
    assert set(wm.provenance) == set(LAYERS)


def test_update_observed_from_real_elevationmap():
    # the observed layer is fed by the real mapper output type (dart.mapping.ElevationMap)
    from dart.mapping import ElevationMap
    dem = _real_dem_window()
    cover = np.zeros(dem.shape, bool); cover[20:40, 20:40] = True
    elev = np.where(cover, dem, np.nan)
    em = ElevationMap(elevation=elev, count=cover.astype(int), cell_m=0.02,
                      n_points=int(cover.sum()), n_frames=1)
    wm = WorldModelLayers(dem.shape)
    wm.set_truth(dem)
    n = wm.update_observed_from_map(em)
    assert n == int(cover.sum())
    assert wm.provenance["observed"] == "stereo_mapper"
    assert np.isfinite(wm.layer("observed")[cover]).all()


def test_worldstate_carries_material_traversability_observed_uncertainty():
    """[REQ:TW-05] ONE WorldState grid carries all four per-cell fields together -- material,
    traversability (cost + passable), observed/unobserved state, and calibrated uncertainty -- instead
    of four scattered rasters, proven on the real crater_boulders (Haworth-lineage) DEM window.

    Asserts: all four channels share the grid shape; unobserved cells carry NO uncertainty (NaN sigma,
    locked to the observed mask); observed cells get a finite, positive sigma; the observed coverage is
    partial (not the whole tile); and the grid surfaces through the typed stewie.contracts.WorldState
    descriptor with matching geometry + observed fraction. Every channel is fed by its REAL source
    object -- ColumnState (material density), lode CompositeCostmap (traversability), WorldModelLayers
    (observed coverage), dart.mapping.ElevationMap.cell_uncertainty (calibrated sigma)."""
    from lode.costmap_layers import CostmapContext, compose
    from stewie.physics.column_state import ColumnState

    from dart.mapping import ElevationMap

    dem = _real_dem_window()
    # MATERIAL: a real conserved ColumnState from the sample's density/mass/state rasters
    cs = ColumnState(width=64, height=64, cell_m=0.02,
                     density=_real_field_window("density.rf32"),
                     mass_areal=_real_field_window("mass_areal.rf32"),
                     state_label=_real_field_window("state_label.r8", "u1"))
    # TRAVERSABILITY: the composed per-cell costmap over the same real DEM window
    costmap = compose(CostmapContext(Z=dem, cell_m=0.02))
    # OBSERVED + UNCERTAINTY: a partial central survey fed through the real mapper output type
    cover = np.zeros(dem.shape, bool); cover[16:48, 16:48] = True
    em = ElevationMap(elevation=np.where(cover, dem, np.nan), count=cover.astype(int) * 5,
                      cell_m=0.02, n_points=int(cover.sum()) * 5, n_frames=1)
    wm = WorldModelLayers(dem.shape, cell_m=0.02)
    wm.set_truth(dem)
    wm.update_observed_from_map(em)
    observed_mask = np.isfinite(wm.layer("observed"))

    ws = WorldStateGrid.assemble(material=cs, traversability=costmap,
                                 observed_mask=observed_mask, uncertainty=em, cell_m=0.02)

    # (a) all four per-cell channels share the one grid shape
    assert ws.shape == dem.shape == (64, 64)
    for grid in (ws.material_density, ws.traversability_cost, ws.traversability_passable,
                 ws.observed_mask, ws.cell_uncertainty_sigma):
        assert grid.shape == (64, 64)

    # (b) observed coverage is partial (a real survey, not the whole tile) and matches the mapper
    assert 0.0 < ws.observed_fraction < 1.0
    assert np.array_equal(ws.observed_mask, cover)

    # (c) unobserved cells carry NO uncertainty (sigma is locked to the observed mask), observed cells
    #     get a finite, positive sigma
    assert np.isnan(ws.cell_uncertainty_sigma[~ws.observed_mask]).all()
    obs_sigma = ws.cell_uncertainty_sigma[ws.observed_mask]
    assert np.isfinite(obs_sigma).all()
    assert (obs_sigma > 0.0).all()

    # (d) the channels carry the REAL source data, not placeholders
    assert np.array_equal(ws.material_density, cs.density)   # conserved per-cell material density
    assert ws.traversability_passable.dtype == bool
    assert ws.impassable.sum() == int((~costmap.passable).sum())

    # (e) it surfaces through the typed WorldState metadata descriptor (FS-02 twin/descriptor split)
    descriptor = ws.contract(dem_source="crater_boulders")
    assert (descriptor.rows, descriptor.cols) == (64, 64)
    assert descriptor.cell_m == 0.02
    assert descriptor.dem_source == "crater_boulders"
    assert abs(descriptor.observed_fraction - ws.observed_fraction) < 1e-9
