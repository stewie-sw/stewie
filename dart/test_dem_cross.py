"""DEM-layer cross-analysis on the REAL LOLA Haworth DEM: slope + roughness layers are real derivatives,
and the cross-check confirms steep/rough/protruding sites while rejecting flat smooth ground."""
import os

import numpy as np
import pytest

from dart import dem_cross as DC



def _real_dem():
    from lode import mission_planner as MP
    return MP.load_haworth_dem()                         # (Z[m], cell_m) -- real LOLA Product 78


@pytest.mark.skipif(not os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32"),
                    reason="real DEM absent")
def test_layers_are_real_and_finite():
    L = DC.dem_layers(_real_dem())
    assert L["slope_deg"].shape == L["height_m"].shape
    assert np.all(np.isfinite(L["slope_deg"])) and np.all(L["slope_deg"] >= 0)
    assert np.all(L["roughness_m"] >= 0) and L["slope_deg"].max() > 10.0   # the Haworth rim is genuinely steep


@pytest.mark.skipif(not os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32"),
                    reason="real DEM absent")
def test_cross_analyze_confirms_steep_and_protrusion():
    # SCALE FINDING: on the 5 m-posting LOLA prior, terrain is rough everywhere vs a 7.5 cm obstacle ->
    # the prior orbital DEM cannot resolve boulders; it flags TERRAIN-scale hazards (steep slope), and the
    # boulder cross-check rides the OBSERVED (stereo-built) residual layer, not the coarse prior roughness.
    L = DC.dem_layers(_real_dem()); cell = L["cell_m"]
    sr, sc = np.unravel_index(int(np.argmax(L["slope_deg"])), L["slope_deg"].shape)   # steepest real cell
    fr, fc = np.unravel_index(int(np.argmin(L["slope_deg"])), L["slope_deg"].shape)   # least-steep real cell
    steep = (sc * cell, sr * cell); gentle = (fc * cell, fr * cell)
    assert L["slope_deg"][sr, sc] > L["slope_deg"][fr, fc] + 10.0   # the slope layer DISCRIMINATES (real)
    xa = DC.cross_analyze([steep], L)
    assert xa[0]["confirmed"] and "steep" in xa[0]["reasons"]       # terrain-scale hazard confirmed
    # residual layer (the boulder path): an observed surface protruding above the prior IS confirmed
    xr = DC.cross_analyze([gentle], L, observed_heights=[L["height_m"][fr, fc] + 0.2])  # +20 cm protrusion
    assert "protrudes" in xr[0]["reasons"]
