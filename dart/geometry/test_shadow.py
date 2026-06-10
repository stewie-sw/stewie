import numpy as np
import pytest

from dart.geometry import shadow


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
    assert abs(shadow.heading_from_shadow(0.0, 215.0) - 35.0) < 1e-9
    # the body-frame measurement is now actually used: different obs -> different yaw
    assert abs(shadow.heading_from_shadow(10.0, 215.0) - 25.0) < 1e-9
    assert abs(shadow.heading_from_shadow(90.0, 215.0) - 305.0) < 1e-9


def test_invalid_elevation_raises():
    with pytest.raises(ValueError):
        shadow.height_from_shadow(1.0, 0.0)
    with pytest.raises(ValueError):
        shadow.height_from_shadow(1.0, 90.0)


def test_height_uncertainty_positive_and_low_sun_elevation_term_grows():
    s_hi = shadow.height_uncertainty_m(1.0, 45.0, 0.02, 0.5)
    s_lo = shadow.height_uncertainty_m(11.4, 5.0, 0.02, 0.5)   # same ~1 m object, low sun
    assert s_lo > s_hi > 0


@pytest.mark.parametrize(
    ("fn", "args"),
    [
        (shadow.height_from_shadow, (-1.0, 20.0)),
        (shadow.shadow_length_from_height, (-1.0, 20.0)),
        (shadow.shadow_azimuth_deg, (np.nan,)),
        (shadow.heading_from_shadow, (np.inf, 30.0)),
        (shadow.height_uncertainty_m, (1.0, 20.0, -0.1, 0.2)),
        (shadow.height_uncertainty_m, (1.0, 20.0, 0.1, -0.2)),
    ],
)
def test_shadow_geometry_rejects_invalid_domains(fn, args):
    with pytest.raises(ValueError):
        fn(*args)
