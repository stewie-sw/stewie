"""Cast-shadow geometry (algorithm A2): height-from-shadow and shadow-azimuth heading.

At Sun elevation e, a vertical feature of height H casts a ground shadow of length
L with H = L * tan(e). The shadow points away from the Sun, so the shadow azimuth
is the Sun azimuth + 180 deg; reading the shadow azimuth therefore yields an
absolute heading cue. All real trigonometry, no fabricated values.
"""
from __future__ import annotations

import numpy as np


def _finite_nonnegative(name: str, value: float) -> float:
    value = float(value)
    if not np.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def _valid_elevation(sun_elevation_deg: float) -> float:
    elevation = float(sun_elevation_deg)
    if not np.isfinite(elevation) or not (0.0 < elevation < 90.0):
        raise ValueError("sun elevation must be finite and in (0, 90) deg")
    return elevation


def height_from_shadow(shadow_length_m: float, sun_elevation_deg: float) -> float:
    """H = L * tan(e). Requires e in (0, 90); returns meters."""
    length = _finite_nonnegative("shadow length", shadow_length_m)
    elevation = _valid_elevation(sun_elevation_deg)
    return float(length * np.tan(np.radians(elevation)))


def shadow_length_from_height(height_m: float, sun_elevation_deg: float) -> float:
    """L = H / tan(e). Lower Sun -> longer shadow -> more signal."""
    height = _finite_nonnegative("height", height_m)
    elevation = _valid_elevation(sun_elevation_deg)
    return float(height / np.tan(np.radians(elevation)))


def shadow_azimuth_deg(sun_azimuth_deg: float) -> float:
    """Azimuth the shadow points toward = Sun azimuth + 180 deg (mod 360)."""
    azimuth = float(sun_azimuth_deg)
    if not np.isfinite(azimuth):
        raise ValueError("sun azimuth must be finite")
    return (azimuth + 180.0) % 360.0


def heading_from_shadow(shadow_azimuth_in_body_deg: float,
                        known_sun_azimuth_deg: float) -> float:
    """Recover body yaw (deg from North, clockwise) from ONE shadow observation.

    The shadow's true world azimuth is sun_azimuth + 180. If that shadow is observed
    at `shadow_azimuth_in_body_deg` in the body/camera frame, the body yaw is
    yaw = (sun_azimuth + 180) - shadow_azimuth_in_body  (mod 360).
    Single unambiguous measurement (the earlier redundant arg was a bug: it was never
    read, so two different inputs gave the same answer)."""
    body_azimuth = float(shadow_azimuth_in_body_deg)
    if not np.isfinite(body_azimuth):
        raise ValueError("body-frame shadow azimuth must be finite")
    true_world = shadow_azimuth_deg(known_sun_azimuth_deg)
    return (true_world - body_azimuth) % 360.0


def height_uncertainty_m(shadow_length_m: float, sun_elevation_deg: float,
                         sigma_L_m: float, sigma_e_deg: float) -> float:
    """First-order propagation of H = L tan(e): combine length and elevation error.

    dH/dL = tan(e);  dH/de = L * sec^2(e).  Returns 1-sigma meters."""
    length = _finite_nonnegative("shadow length", shadow_length_m)
    sigma_length = _finite_nonnegative("shadow-length sigma", sigma_L_m)
    sigma_elevation = _finite_nonnegative("Sun-elevation sigma", sigma_e_deg)
    e = np.radians(_valid_elevation(sun_elevation_deg))
    dH_dL = np.tan(e)
    dH_de = length / (np.cos(e) ** 2)
    return float(np.hypot(dH_dL * sigma_length, dH_de * np.radians(sigma_elevation)))
