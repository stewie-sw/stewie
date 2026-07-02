"""PO-12 — the Solar work-area route. Serves the ONE solar authority (stewie.specs.solar_view) that
composes the sun vector, the illumination/shadow layers, the active cameras + LEDs, the arm posture,
and the SN-02 accepted/rejected shadow evidence into a single payload the cockpit's Solar view reads.

Public read (illumination geometry + the camera/posture rig are not operator-secret, like the globe
base map and /ephemeris). #301: a `site` param resolves the sun geometry to THAT site's lat/lon, the
same source /ephemeris and the layer/plan sun routes use. Delegates to the authority; no app-module
import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/solar", response_model=None)   # returns dict on success or a JSONResponse 400 on a bad posture
def solar(mission_t_s: float = Query(0.0),
          lat_deg: float = Query(-87.45, ge=-90.0, le=90.0),
          lon_deg: float = Query(0.0, ge=-360.0, le=360.0),
          posture: str = Query("TRANSIT", max_length=64),
          leds_on: bool = Query(False),
          site: str | None = Query(None, max_length=64)) -> dict | JSONResponse:
    """PO-12: resolve the integrated Solar view for (mission_t_s, site, posture, LED state) and return
    the one authority payload -- sun vector, illumination/shadow layers, active cameras/LEDs, arm
    posture, and the SN-02 accepted/rejected shadow evidence. An unknown posture is a clean 400 (the
    posture authority raises KeyError), never a 500."""
    from stewie.specs.solar_view import solar_view

    if site:
        from stewie.specs.sites import site_latlon
        lat_deg, lon_deg = site_latlon(site)
    try:
        view = solar_view(mission_t_s=mission_t_s, lat_deg=lat_deg, lon_deg=lon_deg,
                          posture_name=posture, leds_on=leds_on)
    except KeyError as e:                                  # unknown posture name -> honest 400
        return JSONResponse(status_code=400, content={"ok": False, "error": f"unknown posture: {e}"})
    return {"ok": True, "solar": view}
