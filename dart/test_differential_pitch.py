"""AM-04: a controlled camera-PITCH from a DIFFERENTIAL front/rear arm pose, gated on kinematic (VT-03
arm-travel) + stability validation. The chassis tilt is the sourced posture kinematics
(``posture_pitch_rad``); the camera pitch composes VT-10 ``camera_extrinsics``. No fabricated geometry:
every premise (monotonicity, the stability refusal, the VT-10 sign per camera) is checked against the
real modules the action composes."""
import math

import pytest

from dart import differential_pitch as DP
from dart import posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.specs.arm_joint import ARM_TRAVEL_DEG


def test_am04_zero_camera_pitch_at_equal_arm_angles():
    """[REQ:AM-04] No differential -> no tilt: at ANY equal front/rear arm angle (planted, stowed, or
    arms-up) the chassis pitch and the camera pitch are both exactly 0. This is the zero-at-equal half
    of the acceptance, and it holds for every camera because the body does not rotate."""
    for angle in (-50.0, 0.0, 30.0, -80.0):
        for cam in ("front_left", "rear_left", "left_mono", "drum_front_cam"):
            r = DP.camera_pitch_from_differential(angle, angle, camera=cam)
            assert r.differential_deg == pytest.approx(0.0, abs=1e-12)
            assert r.chassis_pitch_rad == pytest.approx(0.0, abs=1e-12)
            assert r.camera_pitch_rad == pytest.approx(0.0, abs=1e-12)


def test_am04_camera_pitch_monotonic_as_front_plants_deeper():
    """[REQ:AM-04] The monotonic half: holding the rear arm planted and rotating the FRONT arm
    progressively deeper raises the front support monotonically, so both the chassis pitch and a
    forward-looking camera's pitch increase STRICTLY monotonically and are nose-up (> 0). For a forward
    CHASSIS camera the induced camera pitch equals the chassis pitch exactly (rigid body)."""
    rear = -40.0                                        # planted (drum below the wheels) reference
    prev_chassis = prev_cam = None
    for front in (-40.0, -45.0, -50.0, -60.0, -70.0, -80.0):
        r = DP.camera_pitch_from_differential(front, rear, camera="front_left")
        # forward chassis camera: pitch == chassis pitch (optical axis is fore/aft, in the pitch plane)
        assert r.camera_pitch_rad == pytest.approx(r.chassis_pitch_rad, abs=1e-12)
        if prev_chassis is not None:
            assert r.chassis_pitch_rad > prev_chassis + 1e-9      # strictly rising
            assert r.camera_pitch_rad > prev_cam + 1e-9
        else:
            assert r.chassis_pitch_rad == pytest.approx(0.0, abs=1e-12)   # front == rear -> 0
        prev_chassis, prev_cam = r.chassis_pitch_rad, r.camera_pitch_rad
    # front planted well below the rear tips the nose UP (front support higher) by a real amount
    assert DP.camera_pitch_from_differential(-80.0, -40.0).camera_pitch_deg > 5.0


def test_am04_sign_is_antisymmetric_in_the_differential():
    """[REQ:AM-04] Swapping which arm is deeper flips the pitch sign: (front deeper) is nose-up, (rear
    deeper) is nose-down, equal in magnitude. The controlled amount tracks the differential, not the
    absolute posture."""
    up = DP.camera_pitch_from_differential(-60.0, -40.0, camera="front_left")     # front deeper
    down = DP.camera_pitch_from_differential(-40.0, -60.0, camera="front_left")    # rear deeper
    assert up.camera_pitch_rad > 0.0 and down.camera_pitch_rad < 0.0
    assert up.camera_pitch_rad == pytest.approx(-down.camera_pitch_rad, abs=1e-12)


def test_am04_composes_vt10_extrinsics_per_camera():
    """[REQ:AM-04] The camera pitch is a genuine VT-10 composition, not "camera pitch == body pitch" for
    all: a REAR-looking chassis camera's optical axis DIPS as the nose rises (pitch == -chassis), and a
    SIDE camera whose optical axis lies on the lateral pitch axis does not pitch at all. Cross-checked
    against the chassis pitch from the sourced posture kinematics."""
    front, rear = -70.0, -40.0
    chassis = pk.posture_pitch_rad(math.radians(front), math.radians(rear))       # sourced mechanism
    assert chassis > 0.0

    fwd = DP.camera_pitch_from_differential(front, rear, camera="front_left")
    aft = DP.camera_pitch_from_differential(front, rear, camera="rear_left")
    side = DP.camera_pitch_from_differential(front, rear, camera="left_mono")

    assert fwd.chassis_pitch_rad == pytest.approx(chassis, abs=1e-12)
    assert fwd.camera_pitch_rad == pytest.approx(chassis, abs=1e-12)   # forward camera: +chassis
    assert aft.camera_pitch_rad == pytest.approx(-chassis, abs=1e-12)  # rear camera: -chassis (dips)
    assert side.camera_pitch_rad == pytest.approx(0.0, abs=1e-9)       # side camera: no pitch
    assert fwd.mount == "chassis" and side.mount == "chassis"


def test_am04_kinematic_validation_rejects_out_of_travel_arm():
    """[REQ:AM-04] The kinematic gate is VT-03's own arm-travel limit: an angle beyond the sweep is
    rejected loudly (ValueError) rather than used to fabricate a pitch. AM-04 is a controlled action
    only for a kinematically realizable pose."""
    beyond = ARM_TRAVEL_DEG[0] - 20.0                    # 20 deg past the lower travel limit
    assert beyond < ARM_TRAVEL_DEG[0]                    # premise: really out of range
    with pytest.raises(ValueError):
        DP.camera_pitch_from_differential(beyond, 0.0)


def test_am04_stability_gate_refuses_an_unstable_loaded_differential():
    """[REQ:AM-04] The stability half of "only after ... validation": a heavy drum load on the shallow,
    far-reaching front arm while the differential tilts the body drives the CG outside the support
    polygon, so the load-aware margin goes negative and the action is REFUSED (feasible=False). The
    refusal is real (the premise is the actual posture_select margin), and the induced geometry is still
    reported (a deterministic consequence of the valid arm angles, not a fabricated measurement)."""
    front, rear, fill = -30.0, -70.0, 30.0
    margin = ps._stability_margin_asym_m(math.radians(front), math.radians(rear), fill, 0.0)
    assert margin < 0.0                                  # premise from the real support-polygon geometry

    r = DP.camera_pitch_from_differential(front, rear, fill_front_kg=fill, fill_rear_kg=0.0)
    assert not r.feasible
    assert "stability margin" in r.reason
    assert r.stability_margin_m == pytest.approx(margin, abs=1e-9)
    # the differential still induces a real body/camera pitch; feasibility is a separate verdict
    assert abs(r.chassis_pitch_deg) > 5.0


def test_am04_balanced_differential_clears_the_gate():
    """[REQ:AM-04] The refusal is margin-driven, not a blanket "any differential refuses": an empty,
    balanced-enough differential posture clears the guard and stays feasible with a real commanded
    pitch."""
    r = DP.camera_pitch_from_differential(-60.0, -40.0, camera="front_left")
    assert ps._stability_margin_asym_m(math.radians(-60.0), math.radians(-40.0)) >= DP.DEFAULT_MIN_MARGIN_M
    assert r.feasible and r.reason == "ok"
    assert r.camera_pitch_deg > 0.0
