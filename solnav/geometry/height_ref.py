"""Reference the rover's camera height against the DEM and visual landmarks.

Two independent height anchors that cross-check the kinematic camera height (which
itself depends on [CONFIRM] limb dims and on Bekker sinkage):

  1. Landmark referencing. A visual landmark whose elevation is known from the DEM,
     seen at a measured depression angle delta and horizontal distance d, fixes the
     camera elevation:  z_cam = z_landmark + d * tan(delta).
     (Depression positive = looking down.)

  2. DEM referencing. The camera height above the local surface is z_cam minus the
     DEM elevation under the rover.

The residual between the kinematic height and the landmark/DEM-referenced height is a
real observability check on the posture model and the sinkage estimate. Real trig.
"""
from __future__ import annotations

import numpy as np


def camera_elev_from_landmark(landmark_elev_m: float, depression_deg: float,
                              horizontal_dist_m: float) -> float:
    """z_cam = z_landmark + d * tan(depression). Looking DOWN -> depression > 0."""
    return landmark_elev_m + horizontal_dist_m * np.tan(np.radians(depression_deg))


def depression_to_landmark(camera_elev_m: float, landmark_elev_m: float,
                           horizontal_dist_m: float) -> float:
    """Predicted depression angle (deg) to a landmark, given heights and range."""
    return float(np.degrees(np.arctan2(camera_elev_m - landmark_elev_m, horizontal_dist_m)))


def height_above_dem(camera_world_z_m: float, local_dem_z_m: float) -> float:
    """Camera height above the local DEM surface."""
    return camera_world_z_m - local_dem_z_m


def height_residual_m(kinematic_height_m: float, referenced_height_m: float) -> float:
    """Observability check: kinematic (model) height minus DEM/landmark-referenced height.
    A large residual flags a wrong limb dimension or an unmodeled sinkage."""
    return kinematic_height_m - referenced_height_m


def triangulate_landmark_height(cam_h1_m: float, depression1_deg: float,
                                cam_h2_m: float, depression2_deg: float):
    """Vertical-parallax triangulation of a landmark from two camera HEIGHTS (two postures)
    at the same ground station. tan(delta_i) = (cam_h_i - H_lm) / D, so:
        D = (h1 - h2) / (tan d1 - tan d2);  H_lm = h1 - D*tan(d1).
    Returns (landmark_height_m, horizontal_distance_m). Raising the camera (meerkat) widens
    the height baseline (h1 - h2) and tightens the estimate."""
    t1, t2 = np.tan(np.radians(depression1_deg)), np.tan(np.radians(depression2_deg))
    if abs(t1 - t2) < 1e-9:
        raise ValueError("equal depressions (no vertical parallax); cannot triangulate")
    D = (cam_h1_m - cam_h2_m) / (t1 - t2)
    H = cam_h1_m - D * t1
    return float(H), float(D)


def triangulation_height_sigma_m(cam_h1_m: float, cam_h2_m: float,
                                 depression1_deg: float, depression2_deg: float,
                                 sigma_deg: float) -> float:
    """1-sigma on the triangulated landmark height, propagated through the ACTUAL two-angle
    solution `triangulate_landmark_height` by central finite differences:
        sigma_H^2 = (dH/dd1)^2 sigma^2 + (dH/dd2)^2 sigma^2.
    Near-parallel geometry (|tan d1 - tan d2| small) is an angular degeneracy with heavy
    tails -> returns +inf (reject; use sampling/quantiles there). Corrects the earlier
    closed-form `D^2/b sec^2` estimate, which was ~40x too large for the demo geometry."""
    t1, t2 = np.tan(np.radians(depression1_deg)), np.tan(np.radians(depression2_deg))
    if abs(t1 - t2) < 1e-3:
        return float("inf")
    eps = 1e-4
    def H(d1, d2):
        return triangulate_landmark_height(cam_h1_m, d1, cam_h2_m, d2)[0]
    # finite differences are per-degree, so multiply by the per-view sigma in degrees
    dH_d1 = (H(depression1_deg + eps, depression2_deg) - H(depression1_deg - eps, depression2_deg)) / (2 * eps)
    dH_d2 = (H(depression1_deg, depression2_deg + eps) - H(depression1_deg, depression2_deg - eps)) / (2 * eps)
    return float(np.hypot(dH_d1, dH_d2) * sigma_deg)
