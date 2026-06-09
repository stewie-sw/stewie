import numpy as np

from solnav.geometry import height_ref as hr
from solnav.posture import kinematics as kin


# ---- DEM / landmark height referencing ----
def test_camera_elev_from_landmark_known():
    z = hr.camera_elev_from_landmark(1500.0, 10.0, 20.0)
    assert abs(z - (1500.0 + 20.0 * np.tan(np.radians(10.0)))) < 1e-9


def test_depression_roundtrip():
    z = hr.camera_elev_from_landmark(1500.0, 8.0, 25.0)
    d = hr.depression_to_landmark(z, 1500.0, 25.0)
    assert abs(d - 8.0) < 1e-9


def test_height_above_dem():
    assert abs(hr.height_above_dem(1503.5, 1500.0) - 3.5) < 1e-9


def test_residual_flags_model_error():
    assert abs(hr.height_residual_m(0.30, 0.298) - 0.002) < 1e-12


# ---- one-sided vs two-sided postures ----
def test_one_sided_pitches_two_sided_stays_level():
    one = kin.posture("MEERKAT_1S")     # (70, 0)
    two = kin.posture("MEERKAT")        # (70, 70)
    assert one.pitch_deg > 10.0         # one-sided -> strong pitch
    assert abs(two.pitch_deg) < 1e-6    # two-sided -> level


def test_two_sided_lifts_higher_than_one_sided():
    one = kin.posture("MEERKAT_1S")
    two = kin.posture("MEERKAT")
    assert two.chassis_lift_m > one.chassis_lift_m   # symmetric raise lifts more


def test_pushup_is_two_sided_partial():
    p = kin.posture("PUSHUP")           # (45, 45)
    assert abs(p.pitch_deg) < 1e-6 and p.chassis_lift_m >= 0.0
