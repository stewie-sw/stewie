"""Stanford-style rock+height hazard occupancy map + routing over it. Real Haworth DEM."""
import os

import numpy as np

from dart import hazard_map as HM
from dart import rock_taxonomy as RT
_REPO_SAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))

_HAVE = os.path.exists(os.path.join(_REPO_SAMPLES, "lunar_dem/haworth_10km_5m/heightmap.rf32"))


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


def test_t13_obstacle_limit_makes_tall_rocks_hard():
    """ARGUS T1.3 (TRL5): the 7.5 cm obstacle capability is the HARD limit -- a rock TALLER than
    OBSTACLE_LIMIT_M is no-go regardless of its nav class; a shorter soft-class rock stays passable."""
    import numpy as np

    from dart.hazard_map import build_hazard_map
    from dart.rock_taxonomy import Rock
    dem = (np.zeros((40, 40)), 1.0)
    def _rock(h):
        return Rock(diameter_m=0.2, height_m=h, volume_m3=0.002, confidence=0.9,
                    nav_class="B", loc_class="L0", excav_class="E0")
    tall_soft = _rock(0.10)                               # B = soft class, but 10 cm tall
    short_soft = _rock(0.05)                              # under the limit
    hm = build_hazard_map(dem, rocks_world=[(10.0, 10.0, tall_soft), (30.0, 30.0, short_soft)])
    assert not np.isfinite(hm.cost[10, 10])              # 10 cm > 7.5 cm -> hard no-go
    assert np.isfinite(hm.cost[30, 30])                  # 5 cm: passable (penalty only)
