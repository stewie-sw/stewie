"""SN-11: the Meerkat observation action -- multi-height parallax + shadow, gated on a legal, stable
MEERKAT posture transition (composes dart.posture_select + stewie.specs.posture_machine +
stewie.physics.posture_kinematics). No fabricated parallax: the action DEFINES the observation
schedule + extrinsics; the perception readout is the gated SN-15 follow-up."""
import math

import pytest

from dart import meerkat_observation as MO
from dart import posture_select as ps
from stewie.physics import posture_kinematics as pk
from stewie.specs import posture_machine as pm


def test_meerkat_observation_yields_multi_height_plan_from_transit():
    """[REQ:SN-11] From TRANSIT the action is feasible and yields a MULTI-height observation of ONE
    feature: strictly increasing camera heights low->high, target = MEERKAT, and the vertical parallax
    baseline equals the canonical MEERKAT chassis lift (posture_kinematics), not a fabricated number."""
    obs = MO.meerkat_observation(feature_id="rock_7", target_xy=(8.0, 1.0), rover_xy=(0.0, 0.0),
                                 n_heights=4)
    assert obs.feasible and obs.reason == "ok"
    assert obs.to_state == pm.MEERKAT and obs.from_state == pm.TRANSIT
    assert obs.n_heights == 4
    heights = obs.heights_m
    assert all(b > a for a, b in zip(heights, heights[1:], strict=False))   # strictly rising, low -> high
    # baseline is a pure kinematic property of the maneuver == MEERKAT lift - TRANSIT lift (0)
    expected = ps._lift(ps.MEERKAT_PITCH_RAD) - ps._lift(0.0)
    assert obs.parallax_baseline_m == pytest.approx(expected, abs=1e-9)
    assert obs.parallax_baseline_m == pytest.approx(0.1743, abs=1e-3)
    # lowest sample is the TRANSIT floor, highest reaches the MEERKAT lift
    assert heights[0] == pytest.approx(MO.BASE_CAM_HEIGHT_M, abs=1e-9)
    assert heights[-1] == pytest.approx(MO.BASE_CAM_HEIGHT_M + expected, abs=1e-9)


def test_every_height_is_associated_to_the_same_feature():
    """[REQ:SN-11] (feeds SN-15) Every sampled extrinsic observes the SAME world feature -- fixed
    standstill (x,y), only the height changes, and each pose's look-at points at the shared target."""
    tgt = (6.0, -2.0)
    obs = MO.meerkat_observation(feature_id="shadow_tip_3", target_xy=tgt, rover_xy=(1.0, 0.5),
                                 n_heights=3, target_z_m=0.0)
    assert obs.target_xyz == (6.0, -2.0, 0.0)
    for s in obs.samples:
        assert (s.camera_xyz[0], s.camera_xyz[1]) == (1.0, 0.5)      # standstill: x,y fixed
        # the look-at unit vector actually points from the camera toward the shared feature
        dx, dy, dz = tgt[0] - s.camera_xyz[0], tgt[1] - s.camera_xyz[1], 0.0 - s.camera_xyz[2]
        n = math.sqrt(dx * dx + dy * dy + dz * dz)
        assert s.look_at_unit == pytest.approx((dx / n, dy / n, dz / n), abs=1e-9)


def test_illegal_from_state_refuses_without_fabricating_an_observation():
    """[REQ:SN-11] MEERKAT is not directly reachable from DIG (posture_machine legality); the action is
    refused with the machine's reason and yields NO samples -- it never forces an unsafe/illegal maneuver."""
    assert pm.MEERKAT not in pm.legal_transitions(pm.DIG)           # premise: DIG->MEERKAT is illegal
    obs = MO.meerkat_observation(feature_id="rock_1", target_xy=(5.0, 0.0), rover_xy=(0.0, 0.0),
                                 from_state=pm.DIG)
    assert not obs.feasible
    assert obs.samples == () and obs.parallax_baseline_m == 0.0
    assert "illegal" in obs.reason.lower()


def test_inadequate_stability_margin_refuses_under_unbalanced_load():
    """[REQ:SN-11] A heavy unbalanced drum load drops the load-aware MEERKAT margin below the guard, so
    the AM-02/AM-03 gate refuses -- the guard is real, not decorative. front=25 kg, rear=0 gives a
    MEERKAT margin (~0.042 m) under the default 0.05 m threshold (verified against posture_select)."""
    margin = ps._stability_margin_m(ps.MEERKAT_PITCH_RAD, 25.0, 0.0)
    assert margin < 0.05                                            # premise from real posture_select geometry
    obs = MO.meerkat_observation(feature_id="rock_9", target_xy=(4.0, 0.0), rover_xy=(0.0, 0.0),
                                 fill_front_kg=25.0, fill_rear_kg=0.0)
    assert not obs.feasible
    assert obs.samples == ()
    assert "stability margin" in obs.reason
    assert obs.meerkat_margin_m == pytest.approx(margin, abs=1e-9)


def test_a_balanced_load_that_clears_the_guard_still_plans():
    """[REQ:SN-11] A load whose MEERKAT margin clears the guard stays feasible -- the refusal is
    margin-driven, not a blanket 'any load refuses'. Balanced 10 kg per drum keeps margin > 0.05."""
    assert ps._stability_margin_m(ps.MEERKAT_PITCH_RAD, 10.0, 10.0) > 0.05
    obs = MO.meerkat_observation(feature_id="rock_5", target_xy=(4.0, 0.0), rover_xy=(0.0, 0.0),
                                 fill_front_kg=10.0, fill_rear_kg=10.0)
    assert obs.feasible and obs.n_heights >= 2


def test_pitch_for_lift_inverts_the_canonical_kinematics():
    """[REQ:SN-11] The commanded arm pitch for each height round-trips through the canonical forward
    kinematics: chassis_lift_m(_pitch_for_lift(l)) == l -- the extrinsic heights are real posture geometry,
    and the deepest (MEERKAT) sample is the least stable (binding) one."""
    obs = MO.meerkat_observation(feature_id="rock_2", target_xy=(7.0, 0.0), rover_xy=(0.0, 0.0),
                                 n_heights=4)
    for s in obs.samples:
        assert pk.chassis_lift_m(s.arm_pitch_rad, s.arm_pitch_rad) == pytest.approx(s.chassis_lift_m, abs=1e-9)
    # the highest camera (MEERKAT) has the smallest stability margin of the sweep
    margins = [s.stability_margin_m for s in obs.samples]
    assert margins[-1] == min(margins)
    assert obs.samples[-1].arm_pitch_rad == pytest.approx(ps.MEERKAT_PITCH_RAD, abs=1e-6)


def test_rejects_a_single_height_or_arms_up_target():
    """[REQ:SN-11] A parallax sweep needs >= 2 heights, and a MEERKAT raise is arms-DOWN (pitch <= 0)."""
    with pytest.raises(ValueError):
        MO.meerkat_observation(feature_id="x", target_xy=(1.0, 0.0), rover_xy=(0.0, 0.0), n_heights=1)
    with pytest.raises(ValueError):
        MO.meerkat_observation(feature_id="x", target_xy=(1.0, 0.0), rover_xy=(0.0, 0.0),
                               target_pitch_rad=0.5)