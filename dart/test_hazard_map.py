"""Stanford-style rock+height hazard occupancy map + routing over it. Real Haworth DEM."""
import os

import numpy as np

from dart import hazard_map as HM
from dart import rock_taxonomy as RT

_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def _crop():
    from lode import mission_planner as MP
    Z, cell = MP.load_haworth_dem()
    ox, oy = MP.flattest_anchor((Z, cell))
    r0, c0 = int(oy / cell), int(ox / cell)
    return (Z[r0:r0 + 200, c0:c0 + 200].copy(), cell)


def test_hazard_map_marks_steep_and_hard_rocks_nogo():
    if not _HAVE:
        return
    dem = _crop()
    rocks = [(300.0, 250.0, RT.classify(0.8)), (500.0, 250.0, RT.classify(0.05))]  # E no-go + A traversable
    hm = HM.build_hazard_map(dem, (0.0, 0.0), rocks_world=rocks)
    assert not np.isfinite(hm.cost[hm.world_to_rc(300, 250)])     # E rock -> no-go
    assert np.isfinite(hm.cost[hm.world_to_rc(500, 250)])         # A rock -> traversable
    assert np.all(hm.cost[np.isfinite(hm.cost)] >= 1.0)           # base cost + penalties


def test_plan_route_avoids_hazards():
    if not _HAVE:
        return
    dem = _crop()
    barrier = [(450.0, y, RT.classify(0.9)) for y in np.linspace(150, 350, 9)]   # E-boulder wall at x=450
    hm = HM.build_hazard_map(dem, (0.0, 0.0), rocks_world=barrier)
    route = HM.plan_route(hm, (100.0, 250.0), (800.0, 250.0))
    assert route and len(route) > 2                              # found a corridor around the wall
    # the route must not pass through a no-go cell
    assert all(np.isfinite(hm.cost[hm.world_to_rc(x, y)]) for x, y in route)


def test_world_to_rc_nonzero_origin_consistency():
    # audit 2026-06-09: world_to_rc used +origin while rock placement used -origin (latent at origin 0)
    import numpy as np

    from dart import hazard_map as HM
    from dart import rock_taxonomy as RT
    dem = (np.zeros((40, 40)), 5.0)
    hm = HM.build_hazard_map(dem, (100.0, 50.0), rocks_world=[(150.0, 100.0, RT.classify(0.9))])
    r, c = hm.world_to_rc(150.0, 100.0)
    assert (r, c) == (10, 10)                                   # (y-oy)/cell, (x-ox)/cell
    assert not np.isfinite(hm.cost[r, c])                       # the E rock no-go lands at THAT cell
    route = HM.plan_route(hm, (105.0, 55.0), (190.0, 140.0))
    assert route and abs(route[0][0] - 105.0) < 5.0 and abs(route[0][1] - 55.0) < 5.0   # inverse maps back
