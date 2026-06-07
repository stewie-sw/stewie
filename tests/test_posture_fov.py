from solnav.geometry import fov
from solnav.posture import kinematics as kin


# ---- posture kinematics ----
def test_transit_is_flat():
    p = kin.posture("TRANSIT")
    assert p.chassis_lift_m == 0.0 and abs(p.pitch_deg) < 1e-9 and p.within_nominal


def test_meerkat_lifts_above_transit():
    assert kin.posture("MEERKAT").chassis_lift_m > kin.posture("TRANSIT").chassis_lift_m


def test_cobra_pitches_nose_up():
    assert kin.posture("COBRA").pitch_deg > 5.0     # front raised, rear neutral


def test_iron_cross_arms_parallel():
    assert kin.posture("IRON_CROSS").arm_front_deg == 90.0


def test_nominal_vs_extreme_flags():
    assert kin.posture("TRANSIT").within_nominal and kin.posture("COBRA").within_nominal
    assert not kin.posture("MEERKAT").within_nominal      # >55 deg = extreme mode
    assert all(kin.posture(n).within_mech_limit for n in kin.POSTURES)  # all <=135 deg


def test_stability_margin_shrinks_when_raised():
    m_t = kin.stability_margin_m(kin.posture("TRANSIT"), 15, 15)
    m_i = kin.stability_margin_m(kin.posture("IRON_CROSS"), 15, 15)
    assert m_t > m_i                                  # raised -> smaller support polygon


def test_parallax_gain_positive():
    assert kin.parallax_baseline_m(kin.posture("TRANSIT"), kin.posture("MEERKAT")) > 0.05


# ---- FOV / lander visibility ----
def test_hfov_from_real_intrinsics():
    h = fov.hfov_deg_from_intrinsics(1024, 679.57)
    assert abs(h - 74.0) < 1.0                        # the twin render FOV


def test_tag_angular_size_and_detect():
    px = fov.tag_angular_size_px(0.15, 2.5, 679.57)
    assert abs(px - 0.15 / 2.5 * 679.57) < 1e-6
    assert fov.tag_detectable(0.15, 2.5, 679.57)      # close lander -> detectable
    assert not fov.tag_detectable(0.15, 200.0, 679.57)  # far -> too small


def test_in_fov():
    assert fov.in_fov(0.0, 0.0, 0.0, 74.0)            # straight ahead
    assert not fov.in_fov(180.0, 0.0, 0.0, 74.0)      # behind -> not in front FOV


def test_yaw_sweep_structure():
    cams = {"front": (0.0, 74.0), "left": (90.0, 74.0)}
    s = fov.yaw_sweep(0.0, 2.5, cams, 0.15, 679.57, yaws_deg=[0, 90, 180])
    assert "front" in s[0]["cameras_framing"]
    assert s[0]["tag_detectable"] is True
