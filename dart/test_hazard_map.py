"""Stanford-style rock+height hazard occupancy map + routing over it. Real Haworth DEM."""
import os

import numpy as np
import pytest

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


def test_hazard_map_marks_steep_and_hard_rocks_nogo():  # [REQ:ML-02]
    """Terrain Assessment Model: alongside traversability/cost the hazard layer emits (a) a discrete
    hazard CLASS per cell, (b) slope/roughness SUMMARY stats, and (c) a per-cell CONFIDENCE in [0,1]
    that drops where inputs are nodata/UNKNOWN -- and nodata -> low confidence AND no-go. Real Haworth DEM."""
    if not _HAVE:
        return
    dem = _crop()
    e_rock = RT.classify(0.8)                          # E-class boulder -> no-go
    a_rock = RT.classify(0.05, confidence=0.3)         # A-class rock, traversable, LOW-confidence detection
    rocks = [(300.0, 250.0, e_rock), (500.0, 250.0, a_rock)]
    hm = HM.build_hazard_map(dem, (0.0, 0.0), rocks_world=rocks)
    rc_e, rc_a = hm.world_to_rc(300, 250), hm.world_to_rc(500, 250)

    # --- traversability (original acceptance, unchanged) ---
    assert not np.isfinite(hm.cost[rc_e])                        # E rock -> no-go
    assert np.isfinite(hm.cost[rc_a])                            # A rock -> traversable
    assert np.all(hm.cost[np.isfinite(hm.cost)] >= 1.0)         # base cost + penalties

    # --- (a) discrete hazard CLASS per cell ---
    assert hm.hazard_class.shape == hm.cost.shape
    assert set(int(v) for v in np.unique(hm.hazard_class)) <= {HM.SAFE, HM.CAUTION, HM.HAZARD, HM.NOGO}
    assert np.array_equal(hm.hazard_class == HM.NOGO, ~np.isfinite(hm.cost))   # NOGO class <=> no-go cost
    assert hm.hazard_class[rc_e] == HM.NOGO                      # E rock cell classed NOGO
    assert hm.hazard_class[rc_a] != HM.NOGO                      # A rock cell traversable-classed
    assert (hm.hazard_class == HM.NOGO).any() and (hm.hazard_class != HM.NOGO).any()

    # --- (c) per-cell CONFIDENCE in [0, 1], dropping on input uncertainty ---
    assert hm.confidence.shape == hm.cost.shape
    assert np.all(np.isfinite(hm.confidence))
    assert hm.confidence.min() >= 0.0 and hm.confidence.max() <= 1.0
    assert np.all(hm.confidence[np.isfinite(hm.cost)] > 0.0)     # traversable cells keep some confidence
    assert hm.confidence[rc_a] == pytest.approx(0.3)            # low-confidence detection -> lowered confidence
    assert hm.confidence[rc_e] == pytest.approx(1.0)           # confident this cell is blocked (real rock)

    # nodata -> low confidence AND no-go: inject a real missing-measurement patch into the DEM crop
    Z, cell = dem
    Znd = Z.copy(); Znd[98:103, 98:103] = np.nan                # a sensor-gap / nodata patch (real condition)
    hm_nd = HM.build_hazard_map((Znd, cell), (0.0, 0.0))
    zero_conf = hm_nd.confidence == 0.0
    assert zero_conf.any()                                       # the gap dropped confidence to zero somewhere
    assert not np.isfinite(hm_nd.cost[zero_conf]).any()         # every nodata cell is no-go
    assert np.all(hm_nd.hazard_class[zero_conf] == HM.NOGO)     # and classed NOGO
    assert hm_nd.confidence.mean() < 1.0                        # the gap strictly lowers mean confidence

    # --- (b) slope/roughness SUMMARY stats bracket the exposed layers ---
    s = hm.summary
    for k in ("slope_deg_min", "slope_deg_mean", "slope_deg_max",
              "roughness_m_min", "roughness_m_mean", "roughness_m_max"):
        assert np.isfinite(s[k])
    assert s["slope_deg_min"] <= s["slope_deg_mean"] <= s["slope_deg_max"]
    assert s["roughness_m_min"] <= s["roughness_m_mean"] <= s["roughness_m_max"]
    assert s["slope_deg_min"] == pytest.approx(float(np.nanmin(hm.slope_deg)))
    assert s["slope_deg_max"] == pytest.approx(float(np.nanmax(hm.slope_deg)))
    assert s["roughness_m_min"] == pytest.approx(float(np.nanmin(hm.roughness_m)))
    assert s["roughness_m_max"] == pytest.approx(float(np.nanmax(hm.roughness_m)))
    assert s["n_traversable"] + s["n_nogo"] == s["n_cells"] == hm.cost.size
    assert s["n_nogo"] == int((~np.isfinite(hm.cost)).sum())


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
    """Navigation T1.3 (TRL5): the 7.5 cm obstacle capability is the HARD limit -- a rock TALLER than
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
