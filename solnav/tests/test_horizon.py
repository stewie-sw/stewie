"""Horizon-profile localization factor on the real Haworth DEM (excavation-immune)."""
import os
import sys

import numpy as np

from solnav.world import horizon as H

sys.path.insert(0, os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym"))
_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def test_horizon_profile_and_self_match():
    if not _HAVE:
        return
    from planet_browser import mission_planner as MP
    dem = MP.load_haworth_dem()
    cx, cy = 5000.0, 5000.0                              # a point well inside the tile (m)
    prof = H.horizon_profile(dem, (0, 0), cx, cy, n_az=36, max_range_m=3000)
    assert prof.shape == (36,) and np.all(prof >= -np.pi / 2 - 1e-6)
    # the true pose matches its own profile best; offset poses have a larger residual
    cands = [(cx, cy), (cx + 200, cy), (cx, cy + 300), (cx - 400, cy - 200)]
    best, resid, allres = H.match_horizon(prof, dem, (0, 0), cands, n_az=36, max_range_m=3000)
    assert best == (cx, cy) and resid < 1e-9
    assert allres[0][0] < allres[-1][0]                 # sorted; true beats the worst offset


def test_nearfield_berm_excluded_by_standoff():
    # audit 2026-06-09: without a min-range standoff a fresh berm 10 m away entered the "excavation-
    # immune" skyline
    import numpy as np

    from solnav.world import horizon as H2
    z = np.zeros((80, 80)); cell = 5.0
    obs = (200.0, 200.0)
    base = H2.horizon_profile((z, cell), (0, 0), *obs, n_az=8, max_range_m=150)
    zb = z.copy(); zb[40, 42] = 3.0                              # a 3 m berm ~10 m east of the observer
    after = H2.horizon_profile((zb, cell), (0, 0), *obs, n_az=8, max_range_m=150)
    assert np.allclose(base, after)                              # the near-field berm cannot enter the skyline
