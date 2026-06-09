"""Posture forward kinematics: arm angle faithfully drives chassis height / camera vantage."""
import math

from terrain_authority import posture_kinematics as pk
from terrain_authority.postures import get_posture


def test_arms_up_no_lift():
    assert pk.chassis_lift_m(0.65, 0.65) == 0.0          # TRANSIT: wheels support, no lift
    assert pk.arm_drop_below_pivot_m(0.5) == 0.0         # arm above horizontal -> no drop


def test_arms_down_lift_positive_and_bounded():
    lift = pk.chassis_lift_m(-1.0, -1.0)                 # MEERKAT
    assert 0.1 < lift < 0.4                              # raises the body, bounded by arm length


def test_lift_monotonic_in_arm_down_angle():
    lifts = [pk.chassis_lift_m(-a, -a) for a in (0.2, 0.6, 1.0, 1.4)]
    assert all(b >= a for a, b in zip(lifts, lifts[1:])) and lifts[-1] > lifts[0]


def test_full_down_arm_drops_full_length():
    assert math.isclose(pk.arm_drop_below_pivot_m(-math.pi / 2), pk.ARM_LENGTH_M, rel_tol=1e-9)


def test_camera_vantage_rises_with_meerkat():
    t = pk.camera_vantage_m(*[get_posture("TRANSIT").arm_front_pitch_rad,
                              get_posture("TRANSIT").arm_back_pitch_rad], cam_vert_offset_m=-0.10)
    m = pk.camera_vantage_m(*[get_posture("MEERKAT").arm_front_pitch_rad,
                              get_posture("MEERKAT").arm_back_pitch_rad], cam_vert_offset_m=-0.10)
    assert m > t + 0.1                                   # MEERKAT raises the camera vantage


def _h(P="TRANSIT", sa=0.0, sc=0.0):
    from terrain_authority.postures import get_posture
    p = get_posture(P)
    return pk.camera_heights_m(p.arm_front_pitch_rad, p.arm_back_pitch_rad, sa, sc)


def test_eight_cameras_returned():
    assert set(_h()) == set(pk.CAMERA_MOUNTS) and len(_h()) == 8


def test_flat_fore_aft_equal_but_mounts_differ():
    h = _h()
    assert math.isclose(h["front_left"], h["rear_left"])         # flat: fore/aft same height
    assert h["drum_front_cam"] > h["front_left"]                  # mast cam higher by mount


def test_pitch_makes_front_higher_than_rear():
    h = _h(sa=math.radians(15))                                   # nose-up slope
    assert h["front_left"] > h["rear_left"] + 0.1                 # fore/aft differ BY SLOPE


def test_roll_makes_one_side_higher():
    h = _h(sc=math.radians(15))
    assert abs(h["left_mono"] - h["right_mono"]) > 0.1           # widest lateral mounts split by roll


def test_meerkat_raises_every_camera():
    flat, meer = _h("TRANSIT"), _h("MEERKAT")
    assert all(meer[c] > flat[c] for c in pk.CAMERA_MOUNTS)


def test_asymmetric_arms_pitch_the_body_cobra():
    # COBRA: front arm down, back arm up -> body rears nose-up (posture pitch > 0) with no terrain slope
    from terrain_authority.postures import get_posture
    c = get_posture("COBRA")
    assert pk.posture_pitch_rad(c.arm_front_pitch_rad, c.arm_back_pitch_rad) > math.radians(15)
    h = pk.camera_heights_m(c.arm_front_pitch_rad, c.arm_back_pitch_rad)   # flat terrain
    assert h["front_left"] > h["rear_left"] + 0.1                          # rearing lifts the front cams


def test_symmetric_arms_no_posture_pitch():
    assert abs(pk.posture_pitch_rad(-1.0, -1.0)) < 1e-9                    # MEERKAT symmetric -> no pitch


def test_sinkage_lowers_every_camera():
    dry = pk.camera_heights_m(0.65, 0.65)
    sunk = pk.camera_heights_m(0.65, 0.65, sinkage_m=0.05)                # wheels sink 5 cm
    assert all(sunk[c] < dry[c] - 0.04 for c in pk.CAMERA_MOUNTS)
