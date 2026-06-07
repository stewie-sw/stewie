"""Cast-shadow geometry (algorithm A2): height-from-shadow and shadow-azimuth heading.

At Sun elevation e, a vertical feature of height H casts a ground shadow of length
L with H = L * tan(e). The shadow points away from the Sun, so the shadow azimuth
is the Sun azimuth + 180 deg; reading the shadow azimuth therefore yields an
absolute heading cue. All real trigonometry, no fabricated values.
"""
from __future__ import annotations

import numpy as np


def height_from_shadow(shadow_length_m: float, sun_elevation_deg: float) -> float:
    """H = L * tan(e). Requires e in (0, 90); returns meters."""
    if not (0.0 < sun_elevation_deg < 90.0):
        raise ValueError("sun elevation must be in (0, 90) deg for a finite shadow")
    return shadow_length_m * np.tan(np.radians(sun_elevation_deg))


def shadow_length_from_height(height_m: float, sun_elevation_deg: float) -> float:
    """L = H / tan(e). Lower Sun -> longer shadow -> more signal."""
    if not (0.0 < sun_elevation_deg < 90.0):
        raise ValueError("sun elevation must be in (0, 90) deg for a finite shadow")
    return height_m / np.tan(np.radians(sun_elevation_deg))


def shadow_azimuth_deg(sun_azimuth_deg: float) -> float:
    """Azimuth the shadow points toward = Sun azimuth + 180 deg (mod 360)."""
    return (sun_azimuth_deg + 180.0) % 360.0


def heading_from_shadow(shadow_azimuth_in_body_deg: float,
                        known_sun_azimuth_deg: float) -> float:
    """Recover body yaw (deg from North, clockwise) from ONE shadow observation.

    The shadow's true world azimuth is sun_azimuth + 180. If that shadow is observed
    at `shadow_azimuth_in_body_deg` in the body/camera frame, the body yaw is
    yaw = (sun_azimuth + 180) - shadow_azimuth_in_body  (mod 360).
    Single unambiguous measurement (the earlier redundant arg was a bug: it was never
    read, so two different inputs gave the same answer)."""
    true_world = shadow_azimuth_deg(known_sun_azimuth_deg)
    return (true_world - shadow_azimuth_in_body_deg) % 360.0


def height_uncertainty_m(shadow_length_m: float, sun_elevation_deg: float,
                         sigma_L_m: float, sigma_e_deg: float) -> float:
    """First-order propagation of H = L tan(e): combine length and elevation error.

    dH/dL = tan(e);  dH/de = L * sec^2(e).  Returns 1-sigma meters."""
    e = np.radians(sun_elevation_deg)
    dH_dL = np.tan(e)
    dH_de = shadow_length_m / (np.cos(e) ** 2)
    return float(np.hypot(dH_dL * sigma_L_m, dH_de * np.radians(sigma_e_deg)))
