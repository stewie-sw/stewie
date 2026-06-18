"""TW-07: solar incidence angle (the photometric cosine term) from the DEM normal + sun vector."""
import numpy as np
import pytest

from dart.illumination import incidence_angle_deg


def test_flat_surface_incidence_is_ninety_minus_elevation():
    flat = np.full((20, 20), 1500.0)                             # normal straight up everywhere
    for el in (10.0, 30.0, 75.0):
        inc = incidence_angle_deg(flat, cell_m=1.0, sun_az_deg=137.0, sun_el_deg=el)
        assert np.allclose(inc, 90.0 - el, atol=1e-6)            # acos(sin el) = 90 - el


def test_overhead_sun_on_flat_is_zero_incidence():
    flat = np.zeros((8, 8))
    inc = incidence_angle_deg(flat, cell_m=1.0, sun_az_deg=0.0, sun_el_deg=90.0)
    assert np.allclose(inc, 0.0, atol=1e-6)                      # sun at zenith, flat ground -> normal-on


def test_slope_toward_sun_lowers_incidence_away_raises_it():
    H, W = 16, 16
    col = np.arange(W, dtype=float)
    # sun from az=90 (=+col/+X). h DECREASING with col faces +col (toward the sun); INCREASING faces away.
    toward = np.tile(-0.3 * col, (H, 1))                         # dh/dcol < 0 -> normal tilts toward +col
    away = np.tile(+0.3 * col, (H, 1))
    el = 30.0
    flat_val = 90.0 - el
    inc_toward = incidence_angle_deg(toward, 1.0, 90.0, el).mean()
    inc_away = incidence_angle_deg(away, 1.0, 90.0, el).mean()
    assert inc_toward < flat_val < inc_away                      # sun-facing slope is lit more normal-on


def test_facet_pointing_away_exceeds_ninety():
    # a steep slope facing away from a low sun -> incidence > 90 (self-shadowed facet, no direct flux)
    H, W = 12, 12
    away = np.tile(np.arange(W, dtype=float), (H, 1))            # steep rise away from az=90 sun
    inc = incidence_angle_deg(away, 1.0, 90.0, 8.0)
    assert inc.max() > 90.0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        incidence_angle_deg(np.zeros(5), 1.0, 0.0, 30.0)         # 1-D
    with pytest.raises(ValueError):
        incidence_angle_deg(np.zeros((4, 4)), 0.0, 0.0, 30.0)    # bad cell
