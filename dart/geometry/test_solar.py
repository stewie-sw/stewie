from dart.geometry import solar


def test_subsolar_point_is_overhead():
    elev, _ = solar.sun_elevation_azimuth(10, 20, 10, 20)
    assert abs(elev - 90.0) < 1e-6


def test_equator_noon_overhead():
    elev, _ = solar.sun_elevation_azimuth(0, 0, 0, 0)
    assert abs(elev - 90.0) < 1e-6


def test_terminator_is_zero_elevation():
    elev, _ = solar.sun_elevation_azimuth(0, 0, 0, 90)   # hour angle 90 deg
    assert abs(elev) < 1e-6


def test_south_pole_persistent_grazing_sun():
    # At the pole the Sun elevation equals -delta_s for ALL hour angles:
    # the Sun just circles near the horizon (the core motivation of the work).
    for lam_s in (-150, -30, 0, 45, 170):
        elev, _ = solar.sun_elevation_azimuth(-90, 0, 1.54, lam_s)
        assert abs(elev - (-1.54)) < 1e-6
    # max obliquity bounds how high the Sun ever gets at the pole
    elev_max, _ = solar.sun_elevation_azimuth(-90, 0, -solar.MOON_OBLIQUITY_ECLIPTIC_DEG, 0)
    assert abs(elev_max - solar.MOON_OBLIQUITY_ECLIPTIC_DEG) < 1e-6


def test_azimuth_eastward_when_subsolar_is_east():
    # site at lon 0, sub-solar point to the east (lon +10) -> Sun in the eastern half
    _, az = solar.sun_elevation_azimuth(0, 0, 0, 10)
    assert 0.0 < az < 180.0


def test_daylight_fraction_equator_half():
    assert abs(solar.daylight_fraction(0, 0) - 0.5) < 1e-9


def test_daylight_fraction_polar_degenerate():
    # South pole: lit when the sub-solar latitude is negative (Sun in the south),
    # dark when it is positive (Sun over the north). This is the real polar nuance.
    assert solar.daylight_fraction(-89.9, -1.54) == 1.0   # polar day (Sun south)
    assert solar.daylight_fraction(-89.9, 1.54) == 0.0    # polar night (Sun north)


def test_subsolar_longitude_completes_360_per_synodic_month():
    p = solar.SYNODIC_MONTH_S
    a = solar.subsolar_longitude_deg(0.0, lam0_deg=0.0)
    b = solar.subsolar_longitude_deg(p, lam0_deg=0.0)     # one full synodic month
    assert abs(((a - b) + 180) % 360 - 180) < 1e-6        # back to start
    # quarter month -> 90 deg of westward motion
    q = solar.subsolar_longitude_deg(p / 4, lam0_deg=0.0)
    assert abs(q - (-90.0)) < 1e-6


def test_synodic_day_length():
    assert abs(solar.synodic_day_length_s() - 29.530589 * 86400) < 1e-3
