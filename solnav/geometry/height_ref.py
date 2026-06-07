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
