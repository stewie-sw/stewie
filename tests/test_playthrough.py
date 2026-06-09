"""Operational classification wired into the sim playthrough: each rendered stereo frame -> classified
Rocks (nav/loc/excav). Real a6 renders only."""
import os

import cv2

from solnav.perception import playthrough as PT

_TR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "validation", "a6_traverse")
_HAVE = os.path.exists(os.path.join(_TR, "cam", "frame_000", "front_left.png"))


def test_estimate_rock_fusion_classes():
    r = PT.estimate_rock(0.40, 0.9)                          # 40 cm -> nav D
    assert r.nav_class == "D" and r.loc_class == "L1" and r.excav_class == "E2" and r.confidence == 0.9


def test_classify_stereo_frame_real():
    if not _HAVE:
        return
    left = cv2.imread(os.path.join(_TR, "cam", "frame_000", "front_left.png"))
    right = cv2.imread(os.path.join(_TR, "cam", "frame_000", "front_right.png"))
    rocks = PT.classify_stereo_frame(left, right)
    assert rocks
    for s, rk in rocks:
        assert rk.nav_class in "ABCDE" and rk.diameter_m > 0
        assert rk.loc_class in ("L0", "L1", "L2") and rk.excav_class in ("E0", "E1", "E2", "E3")


def test_classify_traverse_builds_world_model():
    if not _HAVE:
        return
    per_frame, summary = PT.classify_traverse(_TR, sun_azimuth_deg=200, sun_elevation_deg=8)
    assert per_frame and sum(summary.values()) > 0 and set(summary) <= set("ABCDE")
