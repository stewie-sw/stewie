"""SN-10 Godot bridge: render-at-posture capture + frame->pixel measurement -> estimator."""
import math
import os

import numpy as np
import pytest

from stewie.godot import articulation_bridge as AB

_RENDER_PAIR = os.path.join(os.path.dirname(__file__), "out", "parallax")
_REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _frame_with_shadow(h, w, anchor_uv, sun_az_deg, length_px, *, bright=210.0, dark=40.0):
    """A grayscale frame fixture (the shadow_height test pattern): bright surface + a dark shadow
    band running anti-solar from the anchor for length_px. Tests the pixel reader, not the GPU render."""
    img = np.full((h, w), bright, dtype=float)
    dx, dy = AB.anti_solar_dir(sun_az_deg)
    u0, v0 = anchor_uv
    for s in range(0, int(length_px)):
        u, v = int(round(u0 + s * dx)), int(round(v0 + s * dy))
        if 0 <= v < h and 0 <= u < w:
            img[max(0, v - 1):v + 2, max(0, u - 1):u + 2] = dark
    return img


def test_capture_plan_is_two_postures_same_sun_distinct_lift():
    p = AB.parallax_capture_plan("samples/crater_boulders", sun_az_deg=215.0, sun_el_deg=5.0)
    assert len(p["frames"]) == 2
    a, b = p["frames"]
    assert a["chassis_lift_m"] != b["chassis_lift_m"]            # distinct postures
    assert p["dh_m"] > 0.05                                      # a usable parallax baseline (MEERKAT ~0.17)
    # same sun + scene + the 8-camera rig in both render commands
    for f in p["frames"]:
        assert "--cameras" in f["argv"] and "215.0" in f["argv"] and "5.0" in f["argv"]


def test_shadow_tip_px_reads_the_tip_from_a_frame():
    img = _frame_with_shadow(200, 400, (100, 100), sun_az_deg=180.0, length_px=40)  # anti-solar = +x
    u, v = AB.shadow_tip_px(img, (100, 100), 180.0)
    assert u > 130 and abs(v - 100) < 3                          # tip ~40 px east of the anchor


def test_localize_from_frames_corrects_a_drifted_node():
    """Render -> measure -> estimator: shadow-tip shifts measured from two posture frames inject a
    standstill fix that pulls a drifted pose-graph node toward truth."""
    from dart.pose_graph_se2 import PoseGraphSE2
    from dart import articulated_parallax as AP
    from stewie.specs import ipex_specs as S
    fx = S.flight_fx_px(6.0); dh = 0.1743; sun = 180.0

    truth = np.array([4.0, -2.0])
    L = np.array([[6.0, 0.0], [0.0, 5.0], [-3.0, -4.0]])
    frame_pairs, anchors = [], []
    for Li in L:
        R = float(np.hypot(*(truth - Li)))
        shift = AP.pixel_shift_for_range(dh, R, fx)              # the real forward-model tip shift
        anchor = (60, 100)
        fa = _frame_with_shadow(220, 420, anchor, sun, 30)              # posture A: shorter tip distance
        fb = _frame_with_shadow(220, 420, anchor, sun, 30 + shift)      # posture B: tip shifted by parallax
        frame_pairs.append((fa, fb)); anchors.append(anchor)

    g = PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    g.add_between(0, 1, (5.0, -3.0, 0.0), sigma_xy=1.5, sigma_yaw=1.5)
    before = g.optimize_with_cov()
    err0 = math.hypot(before["pose"][1][0] - truth[0], before["pose"][1][1] - truth[1])

    res = AB.localize_from_frames(g, 1, L, frame_pairs, anchors, dh_m=dh, fx_px=fx, sun_az_deg=sun)
    err1 = math.hypot(res["pose"][1][0] - truth[0], res["pose"][1][1] - truth[1])
    assert err1 < err0                                          # render-measured fix corrects the node
    assert res["xy_sigma"][1] < before["xy_sigma"][1]


@pytest.mark.skipif(not os.path.exists(os.path.join(_RENDER_PAIR, "A", "front_left.png")),
                    reason="committed two-posture render-pair absent")
def test_localize_on_render_pair_recovers_pose_truth_free():
    """[REQ:SN-10] REAL measured articulation-parallax fix on the committed render-pair: a truth-free
    confidence gate + RANSAC recovers the rover ground pose to well under a metre from a ~1.4 m drift,
    using features INSIDE the TRL-5 rig's sourced 0.37-1.9 m resolvable range (no far-field render)."""
    res = AB.localize_on_render_pair(_RENDER_PAIR, os.path.join(_REPO, "samples", "crater_boulders"))
    assert res["n_inliers"] >= 3
    assert res["error_m"] < 0.6                                 # recovers truth -> a real measured fix
    assert res["error_m"] < res["drift_m"]                      # improves on the drifted prior
    lo, hi = res["range_span_m"]
    assert 0.3 < lo and hi < 2.0                                # features within the resolvable rig range
    assert res["fix_sigma_m"] > 0.0                             # geometry-derived covariance
