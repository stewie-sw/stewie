"""Ephemeris / azimuth authority route (FS-06 / §25.3, §25 Phase 1). The SINGLE backend service that
resolves the sun geometry for a mission time + site and returns the typed EphemerisObservation contract
with the azimuth convention EXPLICIT -- every shadow / illumination / navigation-risk / camera-policy /
Navigation consumer reads this, so no consumer may assume a private convention. Public read (illumination
geometry is not operator-secret, like the globe base map). Delegates to the solar authority; no
app-module import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from stewie.contracts import EphemerisObservation
from stewie.specs.solar import sun_az_el

router = APIRouter()

#: stewie.specs.solar.sun_az_el computes azimuth FROM LOCAL NORTH, measured EASTWARD (north=0deg,
#: east=+90deg). This is the one convention shared by every consumer (§25.3); it is surfaced verbatim
#: in the EphemerisObservation contract so the cockpit can display it and tests can pin it.
AZIMUTH_CONVENTION = "from_north_eastward"


@router.get("/ephemeris")
def ephemeris(mission_t_s: float = Query(0.0),
              lat_deg: float = Query(-87.45, ge=-90.0, le=90.0),
              lon_deg: float = Query(0.0, ge=-360.0, le=360.0)) -> dict:
    """FS-06: resolve the sun azimuth/elevation for (mission_t_s, site) via the solar authority and
    return the typed EphemerisObservation -- the sun vector, the EXPLICIT azimuth convention, the body
    frame, and provenance. Lat/lon are domain-checked at the route boundary (422 on out-of-domain)."""
    az, el = sun_az_el(lat_deg, mission_t_s, site_lon_deg=lon_deg)
    obs = EphemerisObservation(
        mission_t_s=mission_t_s, site_lat_deg=lat_deg, site_lon_deg=lon_deg,
        sun_az_deg=az % 360.0, sun_el_deg=max(-90.0, min(90.0, el)),
        azimuth_convention=AZIMUTH_CONVENTION, source="analytic")
    return {"ok": True, "ephemeris": obs.model_dump()}
