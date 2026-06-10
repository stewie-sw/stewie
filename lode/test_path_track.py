"""Planned-vs-actual tracking: drape to 3D, cross-track deviation, replan trigger. Real DEM."""
import os

import numpy as np

from lode import path_track as PT
from dart import rock_taxonomy as RT

_HAVE = os.path.exists("/mnt/projects/foss_ipex/dustgym/samples/lunar_dem/haworth_10km_5m/heightmap.rf32")


def test_cross_track_deviation():
    planned = [(0, 0), (100, 0)]
    actual = [(10, 3), (50, -5), (90, 0)]                 # offsets 3, 5, 0
    dev, mean, mx = PT.cross_track_deviation(planned, actual)
    assert abs(mx - 5.0) < 1e-6 and abs(dev[0] - 3.0) < 1e-6


def test_needs_replan_on_hazard_and_deviation():
    planned = [(0, 0), (100, 0)]
    hz = [(20, 0, RT.classify(0.8)), (90, 0, RT.classify(0.05))]   # an E-boulder + a traversable pebble
    # at (10,0): the E-boulder at (20,0) is within 18 m -> replan; the pebble never triggers
    replan, new = PT.needs_replan((10, 0), planned, hz, sensor_range_m=18)
    assert replan and len(new) == 1 and new[0][2].nav_class == "E"
    # far from any hazard, on the line -> no replan
    assert not PT.needs_replan((60, 0), planned, hz, sensor_range_m=18)[0]
    # off the line past the threshold -> replan even with no hazard
    assert PT.needs_replan((60, 20), planned, [], deviation_max_m=8)[0]


def test_known_hazards_not_rediscovered():
    hz = [(20, 0, RT.classify(0.8))]
    assert not PT.discover_hazards((10, 0), hz, sensor_range_m=18, known=[{"x": 20, "y": 0, "r": 1}])


def test_drape_to_3d_on_real_dem():
    if not _HAVE:
        return
    from lode import mission_planner as MP
    dem = MP.load_haworth_dem()
    # corrected convention (audit M11): dem_origin is the WORLD coordinate of cell (0,0) and the
    # path is in world metres -- the old +origin code treated origin as an additive offset
    ox, oy = MP.flattest_anchor(dem)
    p3 = PT.drape_path([(ox, oy), (ox + 50, oy + 10), (ox + 100, oy + 20)], dem, (0.0, 0.0))
    assert p3.shape == (3, 3) and np.all(np.isfinite(p3[:, 2]))   # 2D->3D: heights appended


def test_cross_track_deviation_empty_inputs_no_crash():
    # audit 2026-06-09: empty actual crashed with IndexError on [:, :2]
    from lode.path_track import cross_track_deviation
    dev, mean, mx = cross_track_deviation([(0, 0), (1, 0)], [])
    assert len(dev) == 0 and mean == 0.0 and mx == 0.0
    dev2, _, _ = cross_track_deviation([], [(0, 0)])
    assert len(dev2) == 0
