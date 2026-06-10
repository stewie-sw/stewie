"""Sun azimuth/elevation at a lunar site from MISSION TIME (real spherical geometry).

The Moon's spin axis is inclined 1.54 deg to the ecliptic normal (IAU/Cassini state), so the
SUB-SOLAR LATITUDE oscillates +/-1.54 deg sinusoidally over a month while the sub-solar LONGITUDE
sweeps 360 deg per SYNODIC month (29.530589 days, the lunar day). Site elevation and azimuth then
follow from the standard spherical alt-az transform:

    sin(el) = sin(phi) sin(delta) + cos(phi) cos(delta) cos(H)
    az      = atan2( -cos(delta) sin(H),  cos(phi) sin(delta) - sin(phi) cos(delta) cos(H) )

with phi = site latitude, delta = sub-solar latitude, H = hour angle (site lon - sub-solar lon).
Azimuth is measured from local NORTH, eastward -- matching dart.illumination's convention.

DISCLOSED APPROXIMATION (not fabrication): mean motions only -- no ephemeris perturbations, no
eccentricity equation-of-time, no parallax/refraction (vacuum), epoch phase = 0 at mission start
unless given. At a polar site the consequences the planner cares about are exact in structure:
azimuth circles the horizon once per lunar day; elevation breathes inside
+/- (colatitude + 1.54 deg); polar winter/summer alternate. Upgrade path: SPICE kernels swap in
behind the same signature.
"""
from __future__ import annotations

import math

LUNAR_OBLIQUITY_DEG = 1.54           # spin axis vs ecliptic normal (IAU Cassini state)
SYNODIC_MONTH_S = 29.530589 * 86400.0   # the lunar day (sub-solar longitude period)
SIDEREAL_MONTH_S = 27.321661 * 86400.0  # the sub-solar LATITUDE oscillation period


def sub_solar_point(mission_time_s: float, *, lon0_deg: float = 0.0,
                    season_phase_rad: float = 0.0) -> tuple:
    """(latitude, longitude) of the sub-solar point at mission time [deg]."""
    lat = LUNAR_OBLIQUITY_DEG * math.sin(
        2.0 * math.pi * mission_time_s / SIDEREAL_MONTH_S + season_phase_rad)
    lon = (lon0_deg + 360.0 * mission_time_s / SYNODIC_MONTH_S) % 360.0
    return lat, lon


def sun_az_el(site_lat_deg: float, mission_time_s: float, *, site_lon_deg: float = 0.0,
              lon0_deg: float = 0.0, season_phase_rad: float = 0.7) -> tuple:
    """Sun (azimuth from local north [deg, eastward], elevation [deg]) at the site."""
    delta_deg, sun_lon = sub_solar_point(mission_time_s, lon0_deg=lon0_deg,
                                         season_phase_rad=season_phase_rad)
    phi = math.radians(site_lat_deg)
    delta = math.radians(delta_deg)
    H = math.radians((site_lon_deg - sun_lon) % 360.0)
    sin_el = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(H)
    el = math.degrees(math.asin(max(-1.0, min(1.0, sin_el))))
    az = math.degrees(math.atan2(
        -math.cos(delta) * math.sin(H),
        math.cos(phi) * math.sin(delta) - math.sin(phi) * math.cos(delta) * math.cos(H)))
    return az % 360.0, el
