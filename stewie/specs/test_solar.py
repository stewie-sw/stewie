"""Solar geometry at the Haworth site from MISSION TIME (the automatic sun directive).

Real spherical geometry, no fabrication: the sub-solar latitude oscillates +/-1.54 deg (the Moon's
spin-axis obliquity to the ecliptic, IAU value) over the sidereal month while the hour angle sweeps
360 deg per SYNODIC month; site elevation/azimuth follow from the standard alt-az transform at the
site latitude. Disclosed approximation: mean motion, no ephemeris perturbations/parallax -- the
upgrade path is SPICE, the structure does not change. Physics pins below are exact consequences of
the geometry, not tuned numbers.
"""
import math

import pytest

from stewie.specs import solar

HAWORTH_LAT = -87.45                                     # deg (LOLA polar product placement)


def test_elevation_bounded_by_colatitude_plus_obliquity():
    cap = (90.0 - abs(HAWORTH_LAT)) + solar.LUNAR_OBLIQUITY_DEG + 0.01
    for d in range(0, 60):
        _, el = solar.sun_az_el(HAWORTH_LAT, mission_time_s=d * 86400.0)
        assert -cap <= el <= cap


def test_azimuth_advances_one_rev_per_synodic_month():
    az0, _ = solar.sun_az_el(HAWORTH_LAT, mission_time_s=0.0)
    az1, _ = solar.sun_az_el(HAWORTH_LAT, mission_time_s=solar.SYNODIC_MONTH_S)
    assert abs((az1 - az0 + 180) % 360 - 180) < 1.5      # back within ~1.5 deg after one synodic rev


def test_polar_winter_and_summer_exist():
    els = [solar.sun_az_el(HAWORTH_LAT, mission_time_s=d * 86400.0)[1] for d in range(0, 28)]
    assert max(els) > 0.5 and min(els) < -0.5            # the site sees both sun-up and sun-down seasons


def test_equator_sees_high_sun():
    els = [solar.sun_az_el(0.0, mission_time_s=d * 86400.0)[1] for d in range(0, 28)]
    assert max(els) > 80.0                               # near-overhead at the equator


def test_deterministic_and_continuous():
    a = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1234567.0)
    b = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1234567.0)
    assert a == b
    az1, el1 = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1000.0)
    az2, el2 = solar.sun_az_el(HAWORTH_LAT, mission_time_s=1060.0)
    assert abs(el2 - el1) < 0.01 and abs((az2 - az1 + 180) % 360 - 180) < 0.05


def test_layer_endpoint_accepts_mission_time(tmp_path):
    import importlib

    from fastapi.testclient import TestClient
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    r = c.get("/layers/raster/illumination.png?mission_t_s=0")
    r2 = c.get("/layers/raster/illumination.png?mission_t_s=600000")   # ~1/4 synodic month later
    assert r.status_code == 200 and r2.status_code == 200
    assert r.content != r2.content                       # the sun MOVED -> shadows moved
