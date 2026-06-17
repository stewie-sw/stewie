"""#183/#79 shadow-nav landmarks -> ARGUS heading factors.

A cast shadow under the grazing lunar sun points along the ANTI-SOLAR azimuth -- a known WORLD
direction the ephemeris provides (anti_solar = sun_azimuth + 180). Detected on the 8-camera panorama
(``scripts/ros2_bridge/shadow_landmarks.py``), each shadow landmark also carries a BODY-frame bearing
of that anti-solar ray: the rover's fixed camera-rig mount heading plus the within-tile column offset,
a rig quantity independent of the unknown world yaw. The pair fixes the rover heading via
``dart.pose_graph_se2.yaw_from_shadow``: yaw = anti_solar_az - observed_body_bearing.

This is the MEASUREMENT leg of the ARGUS shadow loop: it turns accepted shadow landmarks into the
gated ``shadow_yaw`` factors a ``PoseGraphSE2`` consumes (SN-03). A landmark whose shadow contrast is
below the gate is a weak/ambiguous match and is rejected -- it never enters the graph (the ARGUSFactor
``accepted`` residual-gate semantics). Pure numpy-free math; the estimator does the work.

Frame note (honest): all cast shadows are parallel (they share the single anti-solar world direction),
so every landmark is an independent noisy measurement of the SAME body-frame bearing (anti_solar - yaw)
-- which is exactly what makes them fuse into one heading estimate. The body-frame bearing comes from
the rig's body mount layout; deriving it from the served panorama's world-ordered columns (which use
the render's ground-truth camera world headings) is the remaining real-render hookup.
"""
from __future__ import annotations

import math

from dart import pose_graph_se2 as PG


def anti_solar_az_deg(sun_az_deg: float) -> float:
    """The anti-solar azimuth (the world direction a cast shadow points) for a sun azimuth, in
    [0, 360). The ephemeris (/ephemeris) supplies the sun azimuth; the shadow ray is opposite it."""
    return (float(sun_az_deg) + 180.0) % 360.0


def shadow_yaw_factors(landmarks, body_bearings_deg, *, anti_solar_az_deg: float,
                       sigma_deg: float = 8.0, min_contrast: float = 20.0):
    """Build gated shadow-yaw heading measurements from shadow landmarks + their body-frame bearings.

    ``landmarks`` -- shadow_landmarks output dicts ({contrast, ...}); ``body_bearings_deg`` -- the
    body-frame bearing (deg) of the anti-solar ray observed for each landmark (same length).
    ``anti_solar_az_deg`` -- the ephemeris anti-solar world azimuth. ``sigma_deg`` -- the heading 1-sigma
    from the shadow operating envelope (sharp low-sun shadow -> small; fuzzy high-sun -> large).
    ``min_contrast`` -- the acceptance gate.

    Returns [{yaw_rad, sigma_rad, accepted, bearing_deg, contrast}] (yaw via yaw_from_shadow). Only
    ``accepted`` entries are graph-ready; the rest are reported for the audit trail."""
    sig = math.radians(float(sigma_deg))
    asol = math.radians(float(anti_solar_az_deg))
    out = []
    for lm, bb in zip(landmarks, body_bearings_deg):
        contrast = float(lm.get("contrast", 0.0))
        out.append({
            "yaw_rad": PG.yaw_from_shadow(asol, math.radians(float(bb))),
            "sigma_rad": sig,
            "accepted": contrast >= float(min_contrast),
            "bearing_deg": float(bb),
            "contrast": contrast,
        })
    return out


def add_shadow_yaw_factors(graph, node_id: int, factors) -> int:
    """Add the ACCEPTED shadow-yaw factors to ``node_id`` of a PoseGraphSE2. Returns the count added
    (rejected factors are skipped). The graph still needs a translation anchor (prior/absolute) for a
    full pose -- this contributes only the heading constraint."""
    n = 0
    for f in factors:
        if f.get("accepted"):
            graph.add_shadow_yaw(int(node_id), float(f["yaw_rad"]), float(f["sigma_rad"]))
            n += 1
    return n
