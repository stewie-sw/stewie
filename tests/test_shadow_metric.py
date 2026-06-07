"""P5 cast-shadow metric geometry (spec sec 16): validated by geometric identity.

The cube render's exact camera (eye (4,3,4) -> target (0,0.3,0), fov 60, 1024x768). We place known
ground points, project them forward, then run the P5 back-projection + H=L*tan(e) and require exact
recovery. (A real-IMAGE P5 number is blocked on assets -- see shadow_metric module docstring.)
"""
import numpy as np
import pytest

from solnav.geometry import shadow_metric as sm

EYE = (4.0, 3.0, 4.0)
BASIS = sm.look_at_basis(EYE, (0.0, 0.3, 0.0))
W, H, FOV = 1024, 768, 60.0


def test_p5_recovers_known_height_and_length():
    e = 20.0
    L_true = 1.5
    base = np.array([0.0, 0.0, 0.0])
    tip = np.array([L_true * 0.6, 0.0, L_true * 0.8])      # horizontal |tip-base| = L_true
    ub = sm.project(base, EYE, BASIS, W, H, FOV)
    ut = sm.project(tip, EYE, BASIS, W, H, FOV)
    Hm, Lm = sm.shadow_height_from_pixels(ub, ut, EYE, BASIS, W, H, FOV, e)
    assert abs(Lm - L_true) < 1e-6
    assert abs(Hm - L_true * np.tan(np.radians(e))) < 1e-6


def test_pixel_to_ground_inverts_projection():
    p = np.array([0.7, 0.0, -0.4])
    u = sm.project(p, EYE, BASIS, W, H, FOV)
    back = sm.pixel_to_ground(u[0], u[1], EYE, BASIS, W, H, FOV)
    assert np.allclose(back, p, atol=1e-6)


def test_ray_above_horizon_rejected():
    with pytest.raises(ValueError):
        sm.pixel_to_ground(W / 2, 0.0, EYE, BASIS, W, H, FOV)   # top row -> ray up, no ground hit


def test_height_sigma_grows_with_noise_and_range():
    s_small = sm.shadow_height_sigma(1.0, 20.0, 0.01, 0.2)
    s_bigL = sm.shadow_height_sigma(3.0, 20.0, 0.01, 0.2)
    s_bigN = sm.shadow_height_sigma(1.0, 20.0, 0.05, 0.2)
    assert s_bigL > s_small and s_bigN > s_small and s_small > 0
