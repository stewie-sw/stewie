import numpy as np
import pytest

from solnav.geometry import shadow


def test_height_from_shadow_45deg():
    assert abs(shadow.height_from_shadow(1.0, 45.0) - 1.0) < 1e-9


def test_height_from_shadow_30deg():
    assert abs(shadow.height_from_shadow(2.0, 30.0) - 2.0 * np.tan(np.radians(30))) < 1e-9


def test_shadow_length_inverse():
    L = shadow.shadow_length_from_height(1.0, 45.0)
    assert abs(L - 1.0) < 1e-9
    H = shadow.height_from_shadow(L, 45.0)
    assert abs(H - 1.0) < 1e-9


def test_low_sun_gives_longer_shadow():
    assert shadow.shadow_length_from_height(1.0, 5.0) > shadow.shadow_length_from_height(1.0, 45.0)


def test_shadow_azimuth_opposes_sun():
    assert abs(shadow.shadow_azimuth_deg(215.0) - 35.0) < 1e-9
    assert abs(shadow.shadow_azimuth_deg(10.0) - 190.0) < 1e-9


def test_heading_from_shadow():
    # Sun az 215 -> shadow world az 35. If shadow seen straight ahead (0 in body),
    # body yaw = 35.
    yaw = shadow.heading_from_shadow(measured_shadow_azimuth_deg=0.0,
                                     known_sun_azimuth_deg=215.0,
                                     shadow_azimuth_in_body_deg=0.0)
    assert abs(yaw - 35.0) < 1e-9


def test_invalid_elevation_raises():
    with pytest.raises(ValueError):
        shadow.height_from_shadow(1.0, 0.0)
    with pytest.raises(ValueError):
        shadow.height_from_shadow(1.0, 90.0)


def test_height_uncertainty_positive_and_grows_at_low_sun():
    s_hi = shadow.height_uncertainty_m(1.0, 45.0, 0.02, 0.5)
    s_lo = shadow.height_uncertainty_m(11.4, 5.0, 0.02, 0.5)   # same ~1 m object, low sun
    assert s_hi > 0 and s_lo > 0
