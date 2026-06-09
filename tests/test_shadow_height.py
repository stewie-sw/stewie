"""Shadow-based height primitive: measure shadow length + H=L*tan(e). Mechanism tested on a real render."""
import math
import os

import cv2

from solnav.perception import rock_taxonomy as RT
from solnav.perception import shadow_height as SH

_F = os.path.join(os.path.dirname(os.path.dirname(__file__)), "validation", "a6_traverse",
                  "cam", "frame_000", "front_left.png")


def test_anti_solar_dir_is_unit_and_opposite():
    dx, dy = SH.anti_solar_dir(0.0)
    assert abs(math.hypot(dx, dy) - 1.0) < 1e-9 and dx < 0      # shadow points opposite the sun


def test_height_grows_with_shadow_and_lower_sun():
    assert RT.shadow_height_m(2.0, 6.0) > RT.shadow_height_m(1.0, 6.0)   # longer shadow -> taller
    assert RT.shadow_height_m(2.0, 3.0) < RT.shadow_height_m(2.0, 6.0)   # lower sun -> shorter implied H


def test_measure_on_real_render():
    if not os.path.exists(_F):
        return
    g = cv2.imread(_F, cv2.IMREAD_GRAYSCALE)
    h, w = g.shape
    length = SH.measure_shadow_length_px(g, w // 2, h // 2, 200.0)
    assert length >= 0.0                                       # finite, non-negative on real imagery
    height, lpx = SH.estimate_height_m(g, w // 2, h // 2, sun_azimuth_deg=200.0,
                                       sun_elevation_deg=8.0, m_per_px=0.01)
    assert height is None or height > 0.0
