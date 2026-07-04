"""[REQ:SN-15] Low/high posture observations must be ASSOCIATED to the same world feature through the
current arm/camera transforms. A Meerkat sweep (SN-11) buys a vertical baseline only if its low-vantage
and high-vantage looks are provably tied to ONE feature; SN-15 is that association + its invariants
(share the feature, span >= 2 distinct vantage heights). Composes dart.meerkat_observation (SN-11) +
stewie.specs.camera_extrinsics (VT-10). Geometry is real (sourced posture/rig constants), never fabricated.
"""
import math

import pytest

from dart import feature_association as FA
from dart import meerkat_observation as MO
from stewie.specs import posture_machine as pm
from stewie.specs.arm_state import ArmState
from stewie.specs.camera_extrinsics import CameraExtrinsic, camera_extrinsics


def test_sn15_associates_meerkat_multiheight_to_one_feature():
    """[REQ:SN-15] A feasible Meerkat observation of ONE feature associates all its heights to that
    feature: every observation shares the feature id, the set spans >= 2 distinct vantage heights, and
    the association's parallax span equals SN-11's own kinematic baseline (not a fabricated number)."""
    obs = MO.meerkat_observation(feature_id="rock_7", target_xy=(8.0, 1.0), rover_xy=(0.0, 0.0),
                                 n_heights=4)
    assert obs.feasible                                          # premise: SN-11 captured the sweep
    fset = FA.from_meerkat_observation(obs)
    assert fset.feature_id == "rock_7"
    assert fset.n_observations == 4
    assert all(o.feature_id == "rock_7" for o in fset.observations)   # share-the-feature holds
    assert fset.n_distinct_heights == 4                          # four distinct ground vantages
    assert fset.spans_multiple_postures                          # low (TRANSIT) .. high (MEERKAT)
    # the association's vertical baseline is SN-11's own kinematic baseline, attached to one feature
    assert fset.parallax_span_m == obs.parallax_baseline_m
    assert fset.parallax_span_m > 0.0


def test_sn15_each_observation_carries_the_vt10_pose_at_its_posture():
    """[REQ:SN-15] Each association observation carries a REAL VT-10 camera pose derived at that sample's
    arm posture -- for an arm-mounted camera the pose TRACKS the arm (low vs high vantage differ), and it
    matches an independently recomputed camera_extrinsics at the same posture (composed, not fabricated)."""
    obs = MO.meerkat_observation(feature_id="rock_2", target_xy=(7.0, 0.0), rover_xy=(0.0, 0.0),
                                 n_heights=3)
    fset = FA.from_meerkat_observation(obs, camera="drum_front_cam")
    for sample, o in zip(obs.samples, fset.observations):
        assert isinstance(o.camera_pose, CameraExtrinsic) and o.camera == "drum_front_cam"
        arm = ArmState(front_deg=math.degrees(sample.arm_pitch_rad),
                       back_deg=math.degrees(sample.arm_pitch_rad))
        assert o.camera_pose.position_m == camera_extrinsics("drum_front_cam", arm).position_m
    # the arm camera's body-frame pose genuinely MOVED between the low and the high vantage
    assert fset.observations[0].camera_pose.position_m != fset.observations[-1].camera_pose.position_m


def test_sn15_endpoints_are_the_transit_floor_and_the_meerkat_top():
    """[REQ:SN-15] The two-height association ties the low-vantage TRANSIT-floor look and the high-vantage
    MEERKAT look to one feature: distinct posture ids, distinct ground heights (BASE and BASE+baseline)."""
    obs = MO.meerkat_observation(feature_id="shadow_tip_3", target_xy=(6.0, -2.0), rover_xy=(1.0, 0.5),
                                 n_heights=2)
    fset = FA.from_meerkat_observation(obs)
    assert fset.postures == (pm.TRANSIT, pm.MEERKAT)             # low vantage .. high vantage
    lo, hi = fset.observations
    assert lo.posture_id == pm.TRANSIT and hi.posture_id == pm.MEERKAT
    assert lo.vantage_height_m == pytest.approx(MO.BASE_CAM_HEIGHT_M, abs=1e-9)
    assert hi.vantage_height_m == pytest.approx(MO.BASE_CAM_HEIGHT_M + obs.parallax_baseline_m, abs=1e-9)


def test_sn15_chassis_camera_still_spans_distinct_ground_heights():
    """[REQ:SN-15] A CHASSIS camera's VT-10 pose does NOT move with the arm, yet the association is still
    valid: the ground vantage rises with the chassis lift across the sweep, so the >= 2-distinct-heights
    invariant keys on the real ground-relative height, not the (constant) body-frame pose."""
    obs = MO.meerkat_observation(feature_id="rock_5", target_xy=(4.0, 0.0), rover_xy=(0.0, 0.0),
                                 n_heights=3)
    fset = FA.from_meerkat_observation(obs, camera="front_left")
    poses = {o.camera_pose.position_m for o in fset.observations}
    assert len(poses) == 1                                       # chassis pose is rigid to the body
    assert fset.n_distinct_heights == 3                          # ground vantage still rises with lift
    assert fset.parallax_span_m > 0.0


def test_sn15_refuses_to_fuse_observations_of_different_features():
    """[REQ:SN-15] The share-the-feature invariant is REAL, not vacuous: associating an observation of a
    foreign feature into another feature's set raises rather than silently fusing cross-feature evidence."""
    obs = MO.meerkat_observation(feature_id="rock_a", target_xy=(5.0, 0.0), rover_xy=(0.0, 0.0),
                                 n_heights=2)
    good = FA.from_meerkat_observation(obs).observations
    foreign = FA.PostureTaggedObservation(
        feature_id="rock_b", posture_id=pm.MEERKAT, camera=good[0].camera,
        camera_pose=good[0].camera_pose, vantage_height_m=good[0].vantage_height_m + 0.1)
    with pytest.raises(FA.FeatureAssociationError):
        FA.associate("rock_a", (good[0], foreign))


def test_sn15_requires_two_distinct_vantage_heights():
    """[REQ:SN-15] The parallax invariant is REAL: a single observation, or two observations at the SAME
    vantage height, cannot form an association (zero vertical baseline -> nothing to associate across)."""
    obs = MO.meerkat_observation(feature_id="rock_1", target_xy=(5.0, 0.0), rover_xy=(0.0, 0.0),
                                 n_heights=2)
    one = FA.from_meerkat_observation(obs).observations[0]
    with pytest.raises(FA.FeatureAssociationError):             # a single vantage is not an association
        FA.associate("rock_1", (one,))
    same_height = FA.PostureTaggedObservation(
        feature_id="rock_1", posture_id=pm.MEERKAT, camera=one.camera,
        camera_pose=one.camera_pose, vantage_height_m=one.vantage_height_m)   # identical height
    with pytest.raises(FA.FeatureAssociationError):             # two looks at one height -> no baseline
        FA.associate("rock_1", (one, same_height))


def test_sn15_does_not_associate_an_infeasible_meerkat_maneuver():
    """[REQ:SN-15] Honesty firewall: a Meerkat maneuver the posture machine REFUSED (illegal/unstable)
    captured no samples, so no association is fabricated from it -- from_meerkat_observation raises."""
    obs = MO.meerkat_observation(feature_id="rock_9", target_xy=(4.0, 0.0), rover_xy=(0.0, 0.0),
                                 from_state=pm.DIG)              # DIG -> MEERKAT is illegal (SN-11)
    assert not obs.feasible and obs.samples == ()               # premise: refused, no samples
    with pytest.raises(FA.FeatureAssociationError):
        FA.from_meerkat_observation(obs)