"""Dual illuminated / PSR localization-mode supervisor.

At the poles the Sun grazes the horizon and Permanently Shadowed Regions (PSRs) get NO direct sun, so
shadow and appearance cues fail inside them. The supervisor selects the localization MODE by whether the
Sun is above the LOCAL terrain horizon at the rover's pose:

  ILLUMINATED -> visual SLAM + DEM match + horizon match + shadow factors
  PSR         -> stereo + lidar/ToF + thermal + DEM match; shadow factors DISABLED

This keeps the estimator from trusting shadow/appearance cues that do not exist inside a PSR, while
retaining the geometric DEM/horizon/range cues that still work. Real DEM only.
"""
from __future__ import annotations

import math
from enum import Enum

from . import horizon


class Mode(str, Enum):
    ILLUMINATED = "illuminated"
    PSR = "psr"


ACTIVE_FACTORS = {
    Mode.ILLUMINATED: ("visual", "dem", "horizon", "shadow"),
    Mode.PSR: ("stereo", "lidar", "thermal", "dem"),
}


def sun_above_local_horizon(dem, dem_origin, observer_xy, sun_az_deg: float, sun_el_deg: float,
                            **kw) -> bool:
    """Is the Sun above the terrain crest in its azimuth at this pose? Uses the horizon profile -- inside
    a deep PSR the crater wall crest is high, so the Sun (grazing) is occluded. AZIMUTH DATUM: math
    convention, CCW from +x/world-East -- identical to horizon_profile's marching convention (verified
    consistent, audit 2026-06-09). Convert compass azimuth (CW from North) before calling."""
    if sun_el_deg <= 0:
        return False
    prof = horizon.horizon_profile(dem, dem_origin, observer_xy[0], observer_xy[1], **kw)
    n = len(prof)
    ai = int(round((math.radians(sun_az_deg) % (2 * math.pi)) / (2 * math.pi) * n)) % n
    return math.degrees(prof[ai]) < sun_el_deg


def select_mode(dem, dem_origin, observer_xy, sun_az_deg: float, sun_el_deg: float, **kw) -> Mode:
    """ILLUMINATED if the Sun clears the local horizon, else PSR (shadows disabled)."""
    return (Mode.ILLUMINATED if sun_above_local_horizon(dem, dem_origin, observer_xy, sun_az_deg,
                                                         sun_el_deg, **kw) else Mode.PSR)


def factors_for(mode) -> tuple:
    """The localization factors the estimator should run in this mode."""
    return ACTIVE_FACTORS[Mode(mode)]


def shadows_enabled(mode) -> bool:
    return Mode(mode) == Mode.ILLUMINATED
