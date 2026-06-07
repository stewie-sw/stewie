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


import os  # noqa: E402

P5IMG = os.path.join(os.path.dirname(__file__), "fixtures", "p5_post_e30.png")


@pytest.mark.skipif(not os.path.exists(P5IMG), reason="P5 render fixture absent")
def test_p5_recovers_real_rendered_post_height():
    """Recover a known 1.0 m post height from a REAL rendered cast shadow (ortho, m/px exact)."""
    from imageio.v3 import imread
    g = np.asarray(imread(P5IMG)).astype(float)
    if g.ndim == 3:
        g = g[..., :3].mean(2)
    dark = g < 0.5 * np.median(g)
    ys, xs = np.where(dark)
    center = np.array([g.shape[1] / 2.0, g.shape[0] / 2.0])   # post at world origin -> image center
    d = np.hypot(xs - center[0], ys - center[1])
    tip = np.array([xs[int(np.argmax(d))], ys[int(np.argmax(d))]])
    H, _ = sm.shadow_height_ortho(center, tip, 6.0 / 512, 30.0)
    assert 0.85 < H < 1.15        # true 1.0 m, from real pixels (~5% error)


def test_degenerate_camera_geometry_rejected():
    with pytest.raises(ValueError, match="distinct"):
        sm.look_at_basis((0, 0, 0), (0, 0, 0))
    with pytest.raises(ValueError, match="parallel"):
        sm.look_at_basis((0, 0, 0), (0, 1, 0), up=(0, 1, 0))
    with pytest.raises(ValueError, match="FOV"):
        sm.project((0, 0, 0), EYE, BASIS, W, H, 180.0)


@pytest.mark.parametrize(
    "args",
    [
        (1.0, 0.0, 0.01, 0.2),
        (-1.0, 20.0, 0.01, 0.2),
        (1.0, 20.0, -0.01, 0.2),
        (1.0, 20.0, 0.01, np.nan),
    ],
)
def test_shadow_height_sigma_rejects_invalid_domains(args):
    with pytest.raises(ValueError):
        sm.shadow_height_sigma(*args)
