"""#183/#79 shadow-nav landmarks: cast-shadow blobs on the panorama + their azimuth bearings (the ARGUS
measurements). The detector + the column->bearing map are unit-tested on controlled fixtures; the full
detection runs on a REAL render-derived panorama when present and SKIPs otherwise (the egress is render
output, not committed). The fixtures are literal arrays exercising the image-processing logic, not stand-in
sensor data; the real validation is the real-panorama test.

Run: <venv>/bin/python -m pytest scripts/ros2_bridge/test_shadow_landmarks.py -q
"""
import os

import numpy as np
import pytest

pytest.importorskip("scipy")
import shadow_landmarks as SL  # noqa: E402  (same-dir import, mirrors the other bridge scripts)

_EGRESS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "stewie", "godot", "out", "cam", "crater_boulders", "000")


def test_detects_a_dark_blob_on_a_lit_field_but_not_uniform_black():
    img = np.full((80, 80), 120, np.uint8)                    # a lit regolith field (test fixture)
    img[30:50, 30:50] = 20                                    # a cast-shadow blob darker than its surround
    lms = SL.detect_shadow_landmarks(img, box=15, delta=20, lit_floor=10, min_area=50)
    assert lms, "no shadow landmark found on the lit field"
    assert 28 < lms[0]["x"] < 52 and 28 < lms[0]["y"] < 52 and lms[0]["contrast"] > 40
    # uniform black (sky / occluded void) has no LIT neighborhood -> no fabricated landmark
    assert SL.detect_shadow_landmarks(np.zeros((80, 80), np.uint8)) == []


def test_column_to_bearing_maps_tile_centers_to_camera_headings():
    order = [("a", 0.0, ""), ("b", 90.0, "")]                 # two tiles at heading 0 and 90
    assert abs(SL.column_to_bearing_deg(SL.CAM_W * 0.5, order) - 0.0) < 1e-6
    assert abs(SL.column_to_bearing_deg(SL.CAM_W * 1.5, order) - 90.0) < 1e-6
    b = SL.column_to_bearing_deg(0, order)                    # tile-0 left edge -> heading - FOV/2, wrapped
    assert 0.0 <= b < 360.0


def test_shadow_landmarks_on_real_panorama():
    if not os.path.exists(os.path.join(_EGRESS, "sensors.json")):
        pytest.skip("no render egress (render with sidecar.tscn --cameras first)")
    import panorama as P
    pano = P.build_panorama(_EGRESS)
    order = P.panorama_order(_EGRESS)
    lms = SL.landmark_bearings(SL.detect_shadow_landmarks(pano), order)
    assert lms, "no shadow landmarks on the real panorama"
    assert all(0.0 <= lm["bearing_deg"] < 360.0 for lm in lms)       # real bearings around the surround
    assert all(lm["contrast"] > 0 for lm in lms)
