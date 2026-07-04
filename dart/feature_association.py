"""SN-15: associate LOW/HIGH posture observations of ONE world feature through the arm/camera transforms.

A single-vantage look at a feature has ZERO vertical parallax and one self-shadow geometry. The SN-11
Meerkat maneuver buys a real vertical baseline by capturing the SAME feature from a SET of camera heights
on the way up; SN-10 turns that articulation baseline into a range; SN-09 turns the self-shadow length
change into sun-elevation/slope. All of that reasoning is only sound if the low-vantage look and the
high-vantage look are ASSOCIATED to the same world feature -- otherwise multi-height parallax/shadow
evidence is being fused across DIFFERENT features. SN-15 is that association contract.

This module DEFINES the feature-observation association and NOTHING MORE. It fabricates no perception:
each observation carries a REAL camera pose derived by VT-10 (``stewie.specs.camera_extrinsics``, the
posture-dependent extrinsic in ``base_link``) and a REAL ground-relative vantage height (from the SN-11
Meerkat sweep's proprioceptive schedule); ``associate`` only links them to one world-feature id and
ENFORCES the invariant -- every associated observation shares the feature, and the set spans >= 2
distinct vantage heights (a low and a high vantage, the parallax SN-11 needs). It composes, it does not
re-derive: the camera pose is VT-10's output at the observation's arm posture, and the multi-height
schedule is SN-11's :class:`dart.meerkat_observation.MeerkatObservation`.

Two views of "height" are both real and both used, and they are NOT the same quantity:
  * ``camera_pose.position_m`` (VT-10) is the camera origin in the BODY frame -- for an arm-mounted
    camera it moves with the arm (a Meerkat raise pitches the drum camera), for a chassis camera it is
    rigid to the body and does NOT move with the arm.
  * ``vantage_height_m`` is the GROUND-relative camera height (terrain + base height + chassis lift) --
    it rises across the sweep even for a chassis camera, because the whole chassis is lifted off the
    floor. The >= 2-distinct-heights invariant keys on this ground-relative vantage, so the association
    is faithful for either camera mount.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from dart.meerkat_observation import MeerkatObservation
from stewie.specs.arm_state import ArmState
from stewie.specs.camera_extrinsics import CameraExtrinsic, camera_extrinsics
from stewie.specs.vehicles import DEFAULT_VEHICLE

#: two vantage heights closer than this [m] are the SAME height -- proprioception is not infinitely
#: precise, and a sub-micron difference is not a real parallax baseline.
HEIGHT_EPS_M = 1e-6

#: the default rig camera the SN-11 -> SN-15 helper derives poses for: an ARM-mounted camera, whose
#: VT-10 pose genuinely tracks the arm posture (best exhibits the low-vs-high vantage change). Any of
#: the eight rig cameras is valid; a chassis camera still spans distinct GROUND vantages via the lift.
DEFAULT_CAMERA = "drum_front_cam"


class FeatureAssociationError(ValueError):
    """A set of posture-tagged observations cannot form a valid SN-15 association: too few
    observations, an observation of a DIFFERENT feature, or fewer than two distinct vantage heights."""


def _distinct_count(values: tuple[float, ...], eps: float) -> int:
    """The number of values that differ by more than ``eps`` (tolerance-aware distinct count): sort,
    then count each value that clears the last kept representative by more than ``eps``."""
    if not values:
        return 0
    ordered = sorted(values)
    count = 1
    rep = ordered[0]
    for v in ordered[1:]:
        if v - rep > eps:
            count += 1
            rep = v
    return count


@dataclass(frozen=True)
class PostureTaggedObservation:
    """ONE observation of a world feature, tagged with the posture it was taken at.

    ``feature_id`` is the world feature this look observes; ``posture_id`` is the posture it was taken
    at (a ``posture_machine`` state such as ``TRANSIT``/``MEERKAT`` at the sweep endpoints, or an
    en-route label for an intermediate height); ``camera`` is which rig camera produced the pose;
    ``camera_pose`` is the VT-10 extrinsic (position + orientation in ``base_link``) at that posture;
    ``vantage_height_m`` is the GROUND-relative camera height that gives the association its parallax.
    Frozen -- an observation snapshot is immutable."""
    feature_id: str
    posture_id: str
    camera: str
    camera_pose: CameraExtrinsic
    vantage_height_m: float


@dataclass(frozen=True)
class FeatureObservationSet:
    """The SN-15 association: posture-tagged observations, ALL of one ``feature_id``, spanning >= 2
    distinct ground vantage heights. The invariant is enforced at construction (``__post_init__``), so a
    constructed set is ALWAYS valid -- multi-height parallax/shadow evidence provably accrues to ONE
    feature, ready for SN-10 range / SN-09 sun-elevation / SN-12-style reasoning. Prefer :func:`associate`
    (friendlier signature) to build one; direct construction is validated identically."""
    feature_id: str
    observations: tuple[PostureTaggedObservation, ...]

    def __post_init__(self) -> None:
        if len(self.observations) < 2:
            raise FeatureAssociationError(
                f"SN-15 needs >= 2 observations to associate multi-height evidence to feature "
                f"{self.feature_id!r}; got {len(self.observations)}")
        foreign = sorted({o.feature_id for o in self.observations if o.feature_id != self.feature_id})
        if foreign:
            raise FeatureAssociationError(
                f"every observation must SHARE feature {self.feature_id!r}; found foreign "
                f"feature ids {foreign} -- refusing to fuse evidence across different features")
        if self.n_distinct_heights < 2:
            raise FeatureAssociationError(
                f"SN-15 needs >= 2 distinct vantage heights (a low and a high vantage) for feature "
                f"{self.feature_id!r}; the {len(self.observations)} observations span only "
                f"{self.n_distinct_heights} distinct height(s): {self.heights_m}")

    @property
    def n_observations(self) -> int:
        return len(self.observations)

    @property
    def heights_m(self) -> tuple[float, ...]:
        """The ground-relative vantage heights the association spans, in observation order."""
        return tuple(o.vantage_height_m for o in self.observations)

    @property
    def n_distinct_heights(self) -> int:
        """How many distinct vantage heights (within ``HEIGHT_EPS_M``) the observations span."""
        return _distinct_count(self.heights_m, HEIGHT_EPS_M)

    @property
    def postures(self) -> tuple[str, ...]:
        """The distinct posture ids in the association, in first-seen order."""
        seen: list[str] = []
        for o in self.observations:
            if o.posture_id not in seen:
                seen.append(o.posture_id)
        return tuple(seen)

    @property
    def spans_multiple_postures(self) -> bool:
        return len(self.postures) >= 2

    @property
    def parallax_span_m(self) -> float:
        """The vertical baseline the association spans (highest minus lowest vantage) -- the SN-11
        parallax the multi-height set buys, now attached to ONE feature."""
        hs = self.heights_m
        return max(hs) - min(hs)


def associate(feature_id: str, observations: Iterable[PostureTaggedObservation], *,
              min_distinct_heights: int = 2) -> FeatureObservationSet:
    """Link ``observations`` (each a VT-10 camera pose + posture id + ground vantage height) to one
    ``feature_id`` and return the validated :class:`FeatureObservationSet`.

    Raises :class:`FeatureAssociationError` unless every observation shares ``feature_id`` and the set
    spans at least ``min_distinct_heights`` (>= 2) distinct vantage heights -- so a low-vantage and a
    high-vantage look are provably associated to the SAME feature before any parallax/shadow reasoning
    consumes them. Nothing is fabricated: the poses and heights are the caller's real observations
    (see :func:`from_meerkat_observation` for the SN-11 composition)."""
    if min_distinct_heights < 2:
        raise FeatureAssociationError(
            f"SN-15 requires >= 2 distinct vantage heights; min_distinct_heights={min_distinct_heights}")
    obs = tuple(observations)
    result = FeatureObservationSet(feature_id=feature_id, observations=obs)   # invariant enforced here
    if result.n_distinct_heights < min_distinct_heights:
        raise FeatureAssociationError(
            f"feature {feature_id!r} spans {result.n_distinct_heights} distinct vantage height(s), "
            f"below the requested min_distinct_heights={min_distinct_heights}")
    return result


def _sample_posture_id(observation: MeerkatObservation, i: int, n: int) -> str:
    """The posture tag for the ``i``-th Meerkat sample of ``n``: the lowest is the ``from_state`` floor
    (e.g. TRANSIT), the highest is the ``to_state`` top (MEERKAT), and intermediate samples are the
    en-route raise between them -- honest labels, not fabricated FSM states."""
    if i == 0:
        return observation.from_state
    if i == n - 1:
        return observation.to_state
    return f"{observation.from_state}->{observation.to_state}[{i}]"


def from_meerkat_observation(observation: MeerkatObservation, *, camera: str = DEFAULT_CAMERA,
                             vehicle: object = DEFAULT_VEHICLE) -> FeatureObservationSet:
    """Compose SN-11 -> SN-15: turn a FEASIBLE Meerkat observation (SN-11) into the SN-15 association of
    its multi-height samples to the one feature it observed.

    For each Meerkat sample (a distinct arm pitch / chassis lift), the VT-10 camera pose is DERIVED at
    that arm posture (``camera_extrinsics`` of ``camera`` at ``ArmState(front=back=sample pitch)``) and
    paired with the sample's real ground-relative ``camera_height_m`` as the vantage and an honest
    posture tag. An INFEASIBLE Meerkat observation (an illegal or unstable posture the maneuver refused)
    is NOT associated -- the honesty firewall: no association is fabricated for observations that were
    never captured."""
    if not observation.feasible:
        raise FeatureAssociationError(
            f"cannot associate an INFEASIBLE Meerkat observation of feature "
            f"{observation.feature_id!r}: {observation.reason} (no samples were captured)")
    n = observation.n_heights
    tagged: list[PostureTaggedObservation] = []
    for i, s in enumerate(observation.samples):
        arm = ArmState(front_deg=math.degrees(s.arm_pitch_rad), back_deg=math.degrees(s.arm_pitch_rad))
        pose = camera_extrinsics(camera, arm, vehicle)
        tagged.append(PostureTaggedObservation(
            feature_id=observation.feature_id, posture_id=_sample_posture_id(observation, i, n),
            camera=camera, camera_pose=pose, vantage_height_m=s.camera_height_m))
    return associate(observation.feature_id, tagged)