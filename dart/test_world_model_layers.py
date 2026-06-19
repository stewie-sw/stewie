"""[REQ:AS-10] layered world-model acceptance (§25 Phase 8): the mapper updates the observed layer
from observations only, and truth / observed / forecast / edited stay SEPARATE (an update to one
never mutates another). Uses the real crater_boulders conserved DEM (no synthetic elevation)."""
import inspect
import os

import numpy as np
import pytest

from dart.world_model_layers import LAYERS, WorldModelLayers

_DEM = os.path.join(os.path.dirname(__file__), "..", "samples", "crater_boulders", "heightmap.rf32")


def _real_dem_window(n=64):
    if not os.path.exists(_DEM):
        pytest.skip("crater_boulders DEM not present")
    full = np.fromfile(_DEM, dtype="<f4").reshape(256, 256).astype(float)
    return full[96:96 + n, 96:96 + n].copy()      # a real 64x64 crater region


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
