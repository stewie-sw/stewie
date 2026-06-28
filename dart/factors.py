"""Typed navigation measurement factors for the ARGUS/STEWIE estimator seam.

The estimator can still consume legacy ``measured_fixes`` tuples, but new producers should emit
``MeasurementFactor`` records so factor type, covariance, source, frame, and evidence class cannot be
lost before a result is written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np


class FactorType:
    ODOMETRY_BETWEEN = "odometry_between"
    IMU_YAW = "imu_yaw"
    SHADOW_YAW = "shadow_yaw"
    PARALLAX_XY = "parallax_xy"
    DEM_XY = "dem_xy"
    DEM_HEIGHT_NORMAL = "dem_height_normal"
    SHADOW_BOUNDARY_REGISTRATION = "shadow_boundary_registration"
    SHADOW_LENGTH = "shadow_length"
    LOOP_CLOSURE = "loop_closure"
    RELAY_PNT = "relay_pnt"
    # A stereo-VO between-step whose forward translation is subject to a latent per-traverse
    # VO-scale-bias multiplier estimated by the pose graph (dart.pose_graph_se2). Distinct from
    # ODOMETRY_BETWEEN (wheel odometry, unscaled): a VO_SCALE_BETWEEN's forward component is z = s * dx_vo
    # where s is the shared scale state, so a systematic VO forward-scale error can be absorbed when an
    # independent absolute scale reference makes s observable (de-oracle invariant I3: s reads VO, never truth).
    VO_SCALE_BETWEEN = "vo_scale_between"

    ALL: ClassVar[set[str]] = {
        ODOMETRY_BETWEEN,
        IMU_YAW,
        SHADOW_YAW,
        PARALLAX_XY,
        DEM_XY,
        DEM_HEIGHT_NORMAL,
        SHADOW_BOUNDARY_REGISTRATION,
        SHADOW_LENGTH,
        LOOP_CLOSURE,
        RELAY_PNT,
        VO_SCALE_BETWEEN,
    }


class EvidenceClass:
    MEASURED = "measured"
    RENDERED_SENSOR_SIM = "rendered_sensor_sim"
    COMPUTED = "computed"
    MODELED_SIGMA = "modeled_sigma"
    PROPOSED = "proposed"

    ALL: ClassVar[set[str]] = {MEASURED, RENDERED_SENSOR_SIM, COMPUTED, MODELED_SIGMA, PROPOSED}


class Frame:
    BODY = "body"
    CAMERA = "camera"
    LOCAL_MAP = "local_map"
    WORLD = "world"
    DEM = "dem"

    ALL: ClassVar[set[str]] = {BODY, CAMERA, LOCAL_MAP, WORLD, DEM}


_CURRENT_METRIC_SHADOW_BLOCKED = {
    FactorType.SHADOW_BOUNDARY_REGISTRATION,
    FactorType.SHADOW_LENGTH,
}


@dataclass(frozen=True)
class MeasurementFactor:
    factor_type: str
    keyframe: int
    value: Any
    covariance: Any
    frame: str
    source: str
    evidence_class: str
    accepted: bool = True
    refusal_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.factor_type not in FactorType.ALL:
            raise ValueError(f"unknown factor_type {self.factor_type!r}")
        if self.evidence_class not in EvidenceClass.ALL:
            raise ValueError(f"unknown evidence_class {self.evidence_class!r}")
        if self.frame not in Frame.ALL:
            raise ValueError(f"unknown frame {self.frame!r}")
        if not isinstance(self.keyframe, int) or self.keyframe < 0:
            raise ValueError("keyframe must be a non-negative int")
        if not self.accepted and not self.refusal_reason:
            raise ValueError("refused factors must carry refusal_reason")
        cov = np.asarray(self.covariance, float)
        if cov.size == 0 or not np.all(np.isfinite(cov)):
            raise ValueError("covariance must be finite and non-empty")
        if self.accepted:
            assert_current_claim_allowed(self.factor_type, self.evidence_class)

    def covariance_array(self) -> np.ndarray:
        return np.asarray(self.covariance, float)

    def scalar_sigma(self) -> float:
        cov = self.covariance_array()
        if cov.shape == ():
            var = float(cov)
        elif cov.shape == (1, 1):
            var = float(cov[0, 0])
        else:
            raise ValueError(f"{self.factor_type} needs scalar covariance, got shape {cov.shape}")
        if var <= 0.0:
            raise ValueError("variance must be > 0")
        return float(np.sqrt(var))

    def xy_covariance(self) -> np.ndarray:
        cov = self.covariance_array()
        if cov.shape == (2, 2):
            return cov
        if cov.shape == ():
            var = float(cov)
            if var <= 0.0:
                raise ValueError("variance must be > 0")
            return np.eye(2) * var
        raise ValueError(f"{self.factor_type} needs 2x2 or scalar covariance, got shape {cov.shape}")

    def to_json(self) -> dict[str, Any]:
        return {
            "factor_type": self.factor_type,
            "keyframe": self.keyframe,
            "value": np.asarray(self.value).tolist(),
            "covariance": self.covariance_array().tolist(),
            "frame": self.frame,
            "source": self.source,
            "evidence_class": self.evidence_class,
            "accepted": self.accepted,
            "refusal_reason": self.refusal_reason,
            "metadata": dict(self.metadata),
        }


def assert_current_claim_allowed(factor_type: str, evidence_class: str) -> None:
    """Current ARGUS evidence guardrail.

    The 2026-06-24 two-split shadow residual attempt is negative/blocked. Until a later artifact replaces
    that status, metric shadow length and boundary-registration factors must remain proposed or modeled.
    """
    if factor_type in _CURRENT_METRIC_SHADOW_BLOCKED and evidence_class in {
        EvidenceClass.MEASURED,
        EvidenceClass.RENDERED_SENSOR_SIM,
        EvidenceClass.COMPUTED,
    }:
        raise ValueError(
            f"{factor_type} cannot be labeled {evidence_class}: "
            "sigma_n_two_split_2026-06-24.json is negative/blocked"
        )


def factor_lookup(factors: list[MeasurementFactor] | tuple[MeasurementFactor, ...]) -> dict[str, dict[int, MeasurementFactor]]:
    out: dict[str, dict[int, MeasurementFactor]] = {}
    for f in factors:
        if not isinstance(f, MeasurementFactor):
            raise TypeError("typed measured_fixes must contain MeasurementFactor objects")
        if not f.accepted:
            continue
        out.setdefault(f.factor_type, {})[f.keyframe] = f
    return out
