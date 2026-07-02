"""#183/#79 shadow-nav landmarks -> typed Navigation heading factors ([REQ:AS-08]).

A cast shadow under the grazing lunar sun points along the ANTI-SOLAR azimuth -- a known WORLD
direction the ephemeris provides (anti_solar = sun_azimuth + 180). Detected on the 8-camera panorama
(``scripts/ros2_bridge/shadow_landmarks.py``), each shadow landmark also carries a BODY-frame bearing
of that anti-solar ray: the rover's fixed camera-rig mount heading plus the within-tile column offset,
a rig quantity independent of the unknown world yaw. The pair fixes the rover heading via
``dart.pose_graph_se2.yaw_from_shadow``: yaw = anti_solar_az - observed_body_bearing.

This is the MEASUREMENT leg of the Navigation shadow loop: it turns accepted shadow landmarks into the
gated ``shadow_yaw`` factors a ``PoseGraphSE2`` consumes (SN-03). Each factor is a TYPED
``dart.factors.MeasurementFactor`` (factor_type SHADOW_YAW, WORLD frame, scalar heading covariance
sigma_rad^2, evidence MEASURED, source ``dart.shadow_factors``) so the type, covariance, and evidence
class cannot be lost before the estimator fuses it -- the same typed contract dart.factors.factor_lookup
keys the integrated SLAM shadow-yaw path on. A landmark whose shadow contrast is below the gate is a
weak/ambiguous match and is REFUSED (accepted False, carrying a refusal_reason) -- it never enters the
graph (false-factor rejection, the NavFactor residual-gate semantics). The estimator does the work.

Frame note (honest): all cast shadows are parallel (they share the single anti-solar world direction),
so every landmark is an independent noisy measurement of the SAME body-frame bearing (anti_solar - yaw)
-- which is exactly what makes them fuse into one heading estimate. The body-frame bearing comes from
the rig's body mount layout; deriving it from the served panorama's world-ordered columns (which use
the render's ground-truth camera world headings) is the remaining real-render hookup.
"""
from __future__ import annotations

import math

import numpy as np

from dart import pose_graph_se2 as PG
from dart.factors import EvidenceClass, FactorType, Frame, MeasurementFactor

# Observability envelope (design threshold): a shadow-heading 1-sigma beyond this is too azimuthally
# fuzzy to observe heading -- near high sun the anti-solar ray shortens and its azimuth is ill-defined,
# so the factor carries negligible yaw information (a 2-sigma band spanning ~100 deg is effectively a
# uniform azimuth prior). MIN_HEADING_INFORMATION is the matching inverse-variance floor the graph
# gate enforces. Not fabricated data -- a labeled operating limit; the shadow-sigma envelope (sun
# elevation -> shadow sharpness) supplies the per-factor sigma this floor is compared against.
MAX_HEADING_SIGMA_DEG = 25.0
MIN_HEADING_INFORMATION = 1.0 / math.radians(MAX_HEADING_SIGMA_DEG) ** 2


def anti_solar_az_deg(sun_az_deg: float) -> float:
    """The anti-solar azimuth (the world direction a cast shadow points) for a sun azimuth, in
    [0, 360). The ephemeris (/ephemeris) supplies the sun azimuth; the shadow ray is opposite it."""
    return (float(sun_az_deg) + 180.0) % 360.0


def shadow_yaw_factors(landmarks, body_bearings_deg, *, anti_solar_az_deg: float,
                       sigma_deg: float = 8.0, min_contrast: float = 20.0,
                       keyframe: int = 0) -> list[MeasurementFactor]:
    """Build typed gated shadow-yaw heading measurements from shadow landmarks + their body-frame bearings.

    ``landmarks`` -- shadow_landmarks output dicts ({contrast, ...}); ``body_bearings_deg`` -- the
    body-frame bearing (deg) of the anti-solar ray observed for each landmark (same length).
    ``anti_solar_az_deg`` -- the ephemeris anti-solar world azimuth. ``sigma_deg`` -- the heading 1-sigma
    from the shadow operating envelope (sharp low-sun shadow -> small; fuzzy high-sun -> large).
    ``min_contrast`` -- the acceptance gate. ``keyframe`` -- the pose-graph node the factor constrains
    (default 0; set it so dart.factors.factor_lookup binds the factor to the right integrated-SLAM node).

    Returns a list of TYPED ``dart.factors.MeasurementFactor`` records (factor_type SHADOW_YAW, WORLD
    frame, evidence MEASURED, source ``dart.shadow_factors``): the shadow-implied yaw (via yaw_from_shadow)
    as the scalar ``value`` and the heading VARIANCE sigma_rad^2 as the 1x1 ``covariance`` -- so the graph
    fuses it with the correct information 1/sigma_rad^2 (non-negative by construction, the NavFactor
    invariant). A landmark whose contrast is below ``min_contrast`` is a weak/ambiguous match: the factor
    is REFUSED (``accepted`` False, carrying a ``refusal_reason``) so it never enters the graph. Only
    accepted factors that also clear the observability gate in ``add_shadow_yaw_factors`` are graph-ready;
    the refused ones are still returned for the audit trail. The shadow contrast and body bearing are
    recorded in ``metadata``."""
    sig = math.radians(float(sigma_deg))
    cov = [[sig * sig]]                                   # 1x1 heading covariance -> information = 1/sigma^2
    asol = math.radians(float(anti_solar_az_deg))
    out: list[MeasurementFactor] = []
    for lm, bb in zip(landmarks, body_bearings_deg):
        contrast = float(lm.get("contrast", 0.0))
        accepted = contrast >= float(min_contrast)
        refusal = None if accepted else (
            f"shadow contrast {contrast:.1f} < gate {float(min_contrast):.1f} (ambiguous match)")
        out.append(MeasurementFactor(
            factor_type=FactorType.SHADOW_YAW, keyframe=int(keyframe),
            value=PG.yaw_from_shadow(asol, math.radians(float(bb))), covariance=cov,
            frame=Frame.WORLD, source="dart.shadow_factors", evidence_class=EvidenceClass.MEASURED,
            accepted=accepted, refusal_reason=refusal,
            metadata={"bearing_deg": float(bb), "contrast": contrast}))
    return out


def _factor_fields(f) -> tuple[bool, float, float, float]:
    """(accepted, yaw_rad, sigma_rad, information) from a typed MeasurementFactor or a legacy dict."""
    if isinstance(f, MeasurementFactor):
        sig = f.scalar_sigma()
        yaw = float(np.asarray(f.value, float).reshape(-1)[0])
        return bool(f.accepted), yaw, sig, 1.0 / (sig * sig)
    sig = float(f["sigma_rad"])
    return bool(f.get("accepted")), float(f["yaw_rad"]), sig, float(f.get("information", 1.0 / (sig * sig)))


def add_shadow_yaw_factors(graph, node_id: int, factors, *,
                           min_information: float = MIN_HEADING_INFORMATION) -> int:
    """Add the graph-ready shadow-yaw factors to ``node_id`` of a PoseGraphSE2 through TWO gates, and
    return the count added (gated factors are skipped, never entering the graph). ``factors`` are the
    typed ``MeasurementFactor`` records from ``shadow_yaw_factors`` (legacy dicts are still accepted). A
    factor is admitted only if it clears BOTH: the residual/match gate (``accepted`` -- a below-contrast
    shadow is an ambiguous match) AND the observability gate (information ``1/sigma_rad^2 >=
    min_information`` -- a fuzzy high-sun shadow whose heading 1-sigma exceeds MAX_HEADING_SIGMA_DEG
    carries too little yaw information to observe heading). The graph still needs a translation anchor
    (prior/absolute) for a full pose -- this contributes only the covariance-weighted heading
    constraint."""
    n = 0
    for f in factors:
        accepted, yaw_rad, sigma_rad, information = _factor_fields(f)
        if accepted and information >= float(min_information):
            graph.add_shadow_yaw(int(node_id), yaw_rad, sigma_rad)
            n += 1
    return n
