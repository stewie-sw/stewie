"""Topographic teach-and-repeat dock return (second docking method). Real a6 stereo frames."""
import glob
import os

import cv2

from solnav.world import dock_pose as DP
from solnav.world import teach_repeat as TR

_TR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "validation", "a6_traverse")
_FRAMES = sorted(glob.glob(os.path.join(_TR, "cam", "frame_*")))
_HAVE = bool(_FRAMES) and os.path.exists(os.path.join(_FRAMES[0], "front_left.png"))


def _stereo(d):
    return cv2.imread(os.path.join(d, "front_left.png")), cv2.imread(os.path.join(d, "front_right.png"))


def test_record_trail_and_reverse_match():
    if not _HAVE:
        return
    trail = TR.BreadcrumbTrail()
    sigs = []
    for k, d in enumerate(_FRAMES):
        L, R = _stereo(d)
        sig = TR.terrain_signature(L, R)
        sigs.append(sig)
        trail.record(DP.Pose2(float(k), 0.0, 0.0), {"front_left": d}, sig)
    assert len(trail.keyframes) == len(_FRAMES)
    # each frame's topography signature matches its own keyframe best (illumination-invariant descriptor)
    for k, sig in enumerate(sigs):
        idx, sim = trail.match(sig)
        assert idx == k and sim > 0.9
    # REVERSE: from a mid keyframe, step targets the next-earlier keyframe (toward the dock at index 0)
    if len(_FRAMES) >= 3:
        target, cur, sim = trail.reverse_dock_step(sigs[2])
        assert cur == 2 and target.index == 1
    # at the dock (index 0) the return hands off
    assert trail.at_dock(sigs[0])


def test_degenerate_signature_does_not_steer():
    # audit 2026-06-09: an all-zero live signature matched index 0 ("the dock") with sim 0
    import numpy as np

    from solnav.world import dock_pose as DP2
    from solnav.world import teach_repeat as TR2
    trail = TR2.BreadcrumbTrail()
    for k in range(3):
        sig = np.zeros(16); sig[k] = 1.0
        trail.record(DP2.Pose2(float(k), 0.0, 0.0), {}, sig)
    target, cur, sim = trail.reverse_dock_step(np.zeros(16))
    assert target is None and cur is None and sim < 0.2         # caller must stop/search, not steer
