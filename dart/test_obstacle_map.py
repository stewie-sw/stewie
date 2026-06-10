"""Size-gated obstacle avoidance (P1 perception): detect -> stereo-size -> IPEx-clearance gate ->
keep-outs. Real rendered stereo only; clast truth never enters detection (I3)."""
import inspect
import os

import cv2
import pytest

from dart import obstacle_map as OM

_F = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dissertation", "validation", "a6_traverse", "cam", "frame_000")
_HAVE = os.path.exists(os.path.join(_F, "front_left.png"))


def _stereo():
    return cv2.imread(os.path.join(_F, "front_left.png")), cv2.imread(os.path.join(_F, "front_right.png"))


def test_clearance_is_sourced_ipex_value():
    assert abs(OM.IPEX_CLEARANCE_M - 0.075) < 1e-9          # IPEx 7.5 cm step-over [SCHULER24]


def test_detect_takes_images_only_I3():
    # the obstacle classifier must not accept truth (no clast/pose/truth param) -- I3 firewall
    p = set(inspect.signature(OM.classify).parameters)
    assert not (p & {"clasts", "truth", "metadata", "pose", "slip", "gt"})


@pytest.mark.skipif(not _HAVE, reason="rendered stereo absent")
def test_sizes_are_metric_and_gate_works():
    left, right = _stereo()
    obs = OM.classify(left, right)
    assert obs, "expected some sized obstacles on the real boulder field"
    assert all(o.depth_m > 0 and o.diameter_m > 0 for o in obs)        # real metric sizes
    assert all(0.001 < o.diameter_m < 50.0 for o in obs)              # physically plausible band
    # gate monotonicity: a huge clearance -> all traversable; zero -> none traversable
    big = OM.classify(left, right, clearance_m=100.0)
    none = OM.classify(left, right, clearance_m=0.0)
    assert all(o.traversable for o in big) and not any(o.traversable for o in none)


@pytest.mark.skipif(not _HAVE, reason="rendered stereo absent")
def test_keepouts_for_nontraversable_only():
    left, right = _stereo()
    obs = OM.classify(left, right)                                    # IPEx 7.5 cm gate
    kos = OM.obstacle_keepouts(obs, hfov_deg=73.99, width_px=left.shape[1], height_px=left.shape[0])
    n_avoid = sum(1 for o in obs if not o.traversable)
    assert len(kos) == n_avoid and all(k["r"] > 0 for k in kos)       # one keep-out per avoided obstacle


def test_pose_compose_to_world_frame():
    import math
    # camera-relative {lateral, forward}; rover at (10,5) heading +x -> forward adds +x, right adds -y
    w = OM.discovered_keepouts_world([{"x": 2.0, "y": 3.0, "r": 0.5}], (10.0, 5.0, 0.0))[0]
    assert abs(w["x"] - 13.0) < 1e-6 and abs(w["y"] - 3.0) < 1e-6 and w["r"] == 0.5
    w90 = OM.discovered_keepouts_world([{"x": 2.0, "y": 3.0, "r": 0.5}], (10.0, 5.0, math.pi / 2))[0]
    assert abs(w90["x"] - 12.0) < 1e-6 and abs(w90["y"] - 8.0) < 1e-6   # heading +y: forward->+y, right->+x


@pytest.mark.skipif(not _HAVE, reason="rendered stereo absent")
def test_full_detect_avoid_replan_loop():
    # detect -> size -> gate -> camera keep-outs -> world keep-outs (known pose) -> the planner consumes them
    from lode import mission_planner as MP
    left, right = _stereo()
    obs = OM.classify(left, right)
    cam_kos = OM.obstacle_keepouts(obs, hfov_deg=73.99, width_px=left.shape[1], height_px=left.shape[0])
    dem = MP.load_haworth_dem(); o = MP.flattest_anchor(dem)
    world_kos = OM.discovered_keepouts_world(cam_kos, (0.0, 0.0, 0.0))     # rover at the local origin, heading +x
    pay = {"name": "avoid", "body": "moon", "charger": [0, 0],
           "orders": [{"action": "cut", "kind": "cut", "x": 0, "y": 0, "footprint_m2": 36, "depth_m": 0.1},
                      {"action": "fill", "kind": "fill", "x": 40, "y": 0, "footprint_m2": 36, "depth_m": 0.1}],
           "keepouts": [{"x": round(k["x"], 3), "y": round(k["y"], 3), "r": round(k["r"], 3)} for k in world_kos]}
    _, _, _, _, T = MP.plan_and_simulate(MP.mission_from_dict(pay), dem=dem, dem_origin=o)
    assert T["n_keepouts"] == len(world_kos) and len(world_kos) >= 1     # planner consumed the discovered obstacles
    assert "routes" in T                                                 # routed with the discovered keep-outs


@pytest.mark.skipif(not _HAVE, reason="rendered stereo absent")
def test_stereo_support_filter_cuts_false_positives():
    # requiring stereo support (matched 3D points on the blob) drops flat lit-terrain FPs -> fewer, but
    # still some real obstacles. (Measured precision 0.31 -> 0.41 vs the clast truth; recall trades down.)
    left, right = _stereo()
    base = OM.classify(left, right, min_stereo_support=0)
    filt = OM.classify(left, right, min_stereo_support=2)
    assert 0 < len(filt) < len(base)
