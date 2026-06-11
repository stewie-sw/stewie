"""Lunar solar geometry: sub-solar point, local Sun elevation/azimuth, day length.

Real spherical astronomy, no fabricated values. The model takes a site
(selenographic latitude/longitude) and the sub-solar point (the Sun's
selenographic latitude delta_s and longitude lambda_s) and returns the local Sun
elevation and azimuth via an unambiguous ENU vector construction. The sub-solar
point comes from a lunar ephemeris; for a self-contained analytic model the
sub-solar longitude advances 360 deg per synodic month and delta_s is bounded by
the Moon's small obliquity, which is exactly why the south pole sees a persistent
grazing Sun.

Constants (published, real):
  SYNODIC_MONTH_DAYS          29.530589   mean synodic month (new Moon to new Moon)
  MOON_OBLIQUITY_ECLIPTIC_DEG 1.54        Moon equator to ecliptic; bounds |delta_s|
  MOON_RADIUS_KM              1737.4       volumetric mean radius

Azimuth convention: degrees from North, increasing clockwise (N=0, E=90, S=180,
W=270), consistent with the IPEx "positive angular = clockwise" convention.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

import numpy as np

SYNODIC_MONTH_DAYS = 29.530589
SYNODIC_MONTH_S = SYNODIC_MONTH_DAYS * 86400.0
MOON_OBLIQUITY_ECLIPTIC_DEG = 1.54
MOON_RADIUS_KM = 1737.4


def _unit_from_latlon(lat_deg: float, lon_deg: float) -> np.ndarray:
    lat, lon = np.radians(lat_deg), np.radians(lon_deg)
    return np.array([np.cos(lat) * np.cos(lon),
                     np.cos(lat) * np.sin(lon),
                     np.sin(lat)])


def site_enu_basis(phi_deg: float, lam_deg: float):
    """Return (up, east, north) unit vectors of the local ENU frame at a site."""
    phi, lam = np.radians(phi_deg), np.radians(lam_deg)
    up = _unit_from_latlon(phi_deg, lam_deg)
    east = np.array([-np.sin(lam), np.cos(lam), 0.0])
    north = np.array([-np.sin(phi) * np.cos(lam),
                      -np.sin(phi) * np.sin(lam),
                      np.cos(phi)])
    return up, east, north


def sun_elevation_azimuth(phi_deg: float, lam_deg: float,
                          delta_s_deg: float, lam_s_deg: float):
    """Local Sun elevation and azimuth (deg) at site (phi, lam) for sub-solar
    point (delta_s, lam_s). Azimuth from North, clockwise. Elevation < 0 = below
    the horizon (night)."""
    s = _unit_from_latlon(delta_s_deg, lam_s_deg)      # Sun direction, selenographic
    up, east, north = site_enu_basis(phi_deg, lam_deg)
    u = float(np.dot(s, up))                            # = sin(elevation)
    e = float(np.dot(s, east))
    n = float(np.dot(s, north))
    elev = np.degrees(np.arcsin(np.clip(u, -1.0, 1.0)))
    az = np.degrees(np.arctan2(e, n)) % 360.0
    return elev, az


def subsolar_longitude_deg(t_s: float, lam0_deg: float = 0.0, t0_s: float = 0.0) -> float:
    """Sub-solar selenographic longitude at time t_s (seconds). The sub-solar
    point sweeps westward (longitude decreases) at 360 deg per synodic month;
    lam0 is the sub-solar longitude at t0. Returns degrees in [-180, 180)."""
    frac = (t_s - t0_s) / SYNODIC_MONTH_S
    lon = lam0_deg - 360.0 * frac
    return (lon + 180.0) % 360.0 - 180.0


def synodic_day_length_s() -> float:
    """Length of a lunar solar day (sunrise to sunrise), seconds = one synodic month."""
    return SYNODIC_MONTH_S


def daylight_fraction(phi_deg: float, delta_s_deg: float) -> float:
    """Fraction of a synodic day the Sun is above the horizon at latitude phi for
    a fixed sub-solar latitude delta_s. Uses the sunset hour-angle H0 with
    cos(H0) = -tan(phi) tan(delta_s); returns 1.0 (polar day) or 0.0 (polar night)
    in the degenerate polar cases."""
    phi, d = np.radians(phi_deg), np.radians(delta_s_deg)
    x = -np.tan(phi) * np.tan(d)
    if x <= -1.0:
        return 1.0
    if x >= 1.0:
        return 0.0
    h0 = np.degrees(np.arccos(x))
    return h0 / 180.0


def is_lit(phi_deg: float, lam_deg: float, delta_s_deg: float, lam_s_deg: float) -> bool:
    """True if the Sun is above the local horizon."""
    elev, _ = sun_elevation_azimuth(phi_deg, lam_deg, delta_s_deg, lam_s_deg)
    return elev > 0.0
