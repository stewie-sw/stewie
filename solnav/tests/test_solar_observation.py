import pytest

from solnav.perception.solar_observation import ephemeris_fallback


def test_ephemeris_fallback_is_explicit_and_covariance_bearing():
    observation = ephemeris_fallback(
        215.0,
        5.0,
        sample_id="frame0:sun",
        sigma_azimuth_deg=0.5,
        sigma_elevation_deg=0.2,
    )
    assert observation.source == "EPHEMERIS_FALLBACK"
    assert observation.variance_azimuth_deg2 == 0.25
    assert not observation.covariance_calibrated


def test_invalid_solar_elevation_is_rejected():
    with pytest.raises(ValueError, match="elevation"):
        ephemeris_fallback(
            215.0,
            0.0,
            sample_id="frame0:sun",
            sigma_azimuth_deg=0.5,
            sigma_elevation_deg=0.2,
        )
