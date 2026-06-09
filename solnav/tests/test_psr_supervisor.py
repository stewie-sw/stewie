"""Dual illuminated/PSR mode supervisor on the real Haworth DEM."""
import os
import sys

from solnav.world import psr_supervisor as PS

sys.path.insert(0, os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym"))
_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def test_mode_selection_and_factor_gating():
    if not _HAVE:
        return
    from planet_browser import mission_planner as MP
    dem = MP.load_haworth_dem()
    obs = MP.flattest_anchor(dem)
    # sun well up clears the low local horizon -> ILLUMINATED; sun down -> PSR
    illum = PS.select_mode(dem, (0, 0), obs, sun_az_deg=0.0, sun_el_deg=40.0, n_az=36, max_range_m=3000)
    psr = PS.select_mode(dem, (0, 0), obs, sun_az_deg=0.0, sun_el_deg=0.0, n_az=36, max_range_m=3000)
    assert illum == PS.Mode.ILLUMINATED and psr == PS.Mode.PSR
    # shadow factors are active ONLY when illuminated; PSR disables them
    assert "shadow" in PS.factors_for(PS.Mode.ILLUMINATED) and "shadow" not in PS.factors_for(PS.Mode.PSR)
    assert PS.shadows_enabled(PS.Mode.ILLUMINATED) and not PS.shadows_enabled(PS.Mode.PSR)
    assert "thermal" in PS.factors_for(PS.Mode.PSR)                  # PSR adds thermal/lidar/stereo
