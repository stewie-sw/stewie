"""PO-12 — the ONE solar authority behind the cockpit's integrated Solar work area.

The Solar view has to show five things that were previously scattered across the cockpit -- the sun
vector (Ephemeris), the illumination/shadow layers (/layers), the active cameras + LEDs, the arm
posture, and which shadow evidence localization ACCEPTED vs REJECTED. This module composes those five
elements from their REAL existing authorities into one payload so the pane reads a single source:

  * sun vector          -> stewie.specs.solar.sun_az_el (the FS-06 ephemeris authority), plus the
                           anti-solar azimuth (sun_az + 180) the shadow-nav loop keys on.
  * illumination/shadow -> the real gis_layers.RASTER_DEFS "sun" group (illumination / incidence / psr).
  * active cameras/LEDs -> posture_kinematics.CAMERA_MOUNTS (the 8 LAC cameras, sourced from the Godot
                           camera rig) with each camera's FK-computed world height for the posture;
                           the LED (illuminator) state, because it decides whether a shadow is solar.
  * arm posture         -> stewie.physics.postures.get_posture (the reconfigurable-morphology authority).
  * accepted/rejected   -> dart.shadow_vectors.detect_shadow_vector (the SN-02 accept/reject gate): a
    shadow evidence         crisp anti-solar shadow is ACCEPTED as a yaw factor; LEDs-on, self-cast,
                            saturated, or ambiguous-penumbra shadows are REJECTED, each with the real
                            reason. This is the "evidence accepted vs rejected by localization" element.

No fabricated values: every number traces to one of those authorities. The shadow-evidence element
runs the real SN-02 gate over a supplied cast-shadow mask; without a mask it reports the gate is idle
(no evidence to classify) rather than inventing a detection.
"""
from __future__ import annotations

import numpy as np

from stewie.physics import posture_kinematics as pk
from stewie.physics.postures import get_posture, load_postures
from stewie.specs.solar import sun_az_el

#: the illumination/shadow raster layers that belong to the Solar view (the real "sun" group).
_SUN_LAYER_KEYS = ("illumination", "incidence", "psr")


def _sun_layers() -> list[dict]:
    """The real sun-group raster layers (illumination / incidence / psr), read from RASTER_DEFS so the
    Solar view and the map layer picker cannot drift. Each carries its route so the pane can request it."""
    from stewie.server.gis_layers import RASTER_DEFS

    out = []
    for d in RASTER_DEFS:
        if d.get("group") == "sun" and d["key"] in _SUN_LAYER_KEYS:
            out.append({"key": d["key"], "name": d["name"],
                        "raster_route": f"/layers/raster/{d['key']}.png"})
    return out


def _cameras(posture) -> list[dict]:
    """The 8 LAC cameras with each camera's FK-computed world height for this posture (level ground).
    The mount set is the real camera rig; the height comes from posture_kinematics, not a constant."""
    heights = pk.camera_heights_m(posture.arm_front_pitch_rad, posture.arm_back_pitch_rad)
    order = list(pk.CAMERA_MOUNTS)
    return [{"name": name, "world_height_m": round(float(heights[name]), 4), "active": True}
            for name in order]


def _shadow_evidence(*, cast_shadow_mask, cell_m: float, sun_az_deg: float, sun_el_deg: float,
                     leds_on: bool, rover_rc, rover_radius_cells: float,
                     saturated_mask) -> dict:
    """Run the SN-02 accept/reject gate over a supplied cast-shadow mask, or report it idle when there
    is no mask to classify. Returns the accepted/rejected verdict + the real reason from the gate."""
    if cast_shadow_mask is None:
        return {"has_evidence": False, "accepted": None,
                "reason": "no cast-shadow mask supplied: the SN-02 shadow-vector gate is idle "
                          "(no evidence to accept or reject)"}
    from dart.shadow_vectors import detect_shadow_vector

    verdict = detect_shadow_vector(
        np.asarray(cast_shadow_mask, dtype=bool), cell_m=cell_m,
        sun_az_deg=sun_az_deg, sun_el_deg=sun_el_deg, leds_on=leds_on,
        rover_rc=rover_rc, rover_radius_cells=rover_radius_cells, saturated_mask=saturated_mask)
    return {
        "has_evidence": True,
        "accepted": bool(verdict["accepted"]),
        "azimuth_deg": verdict.get("azimuth_deg"),
        "sigma_m": verdict.get("sigma_m"),
        "edge_sharpness": verdict.get("edge_sharpness"),
        "reason": verdict["reason"],
    }


def solar_view(*, mission_t_s: float = 0.0, lat_deg: float = -87.45, lon_deg: float = 0.0,
               posture_name: str = "TRANSIT", leds_on: bool = False,
               cast_shadow_mask=None, cell_m: float = 0.05,
               rover_rc=None, rover_radius_cells: float = 0.0,
               saturated_mask=None) -> dict:
    """Compose the ONE solar-authority payload for the Solar work area.

    All five view elements come from their real authorities (see module docstring). `leds_on` drives
    BOTH the LED status element AND the SN-02 shadow-evidence gate (LEDs on -> a shadow is illuminator-
    cast, so localization REJECTS it), which is exactly why the two live in one authority.
    """
    az, el = sun_az_el(lat_deg, mission_t_s, site_lon_deg=lon_deg)
    az %= 360.0
    el = max(-90.0, min(90.0, el))
    anti_solar_az = (az + 180.0) % 360.0
    posture = get_posture(posture_name)

    return {
        "sun_vector": {
            "sun_az_deg": round(az, 4), "sun_el_deg": round(el, 4),
            "anti_solar_az_deg": round(anti_solar_az, 4),
            "azimuth_convention": "from_north_eastward",
            "mission_t_s": float(mission_t_s),
            "site_lat_deg": float(lat_deg), "site_lon_deg": float(lon_deg),
            "lit": el > 0.0,   # the sun is above the horizon
        },
        "illumination_layers": _sun_layers(),
        "cameras": _cameras(posture),
        "leds": {"on": bool(leds_on),
                 "note": ("illuminators on: shadows are illuminator-cast, not solar" if leds_on
                          else "illuminators off: cast shadows are solar (usable as yaw evidence)")},
        "arm_posture": {
            "name": posture.name,
            "arm_front_pitch_rad": round(posture.arm_front_pitch_rad, 6),
            "arm_back_pitch_rad": round(posture.arm_back_pitch_rad, 6),
            "chassis_lift_m": round(posture.chassis_lift_m, 4),
            "stability": posture.stability,
            "provenance": posture.provenance,
            "available": sorted(load_postures()),   # the posture authority's known names (the pane's picker)
        },
        "shadow_evidence": _shadow_evidence(
            cast_shadow_mask=cast_shadow_mask, cell_m=cell_m,
            sun_az_deg=az, sun_el_deg=el, leds_on=leds_on,
            rover_rc=rover_rc, rover_radius_cells=rover_radius_cells,
            saturated_mask=saturated_mask),
        "authority": "stewie.specs.solar_view (ephemeris + gis sun layers + camera rig + posture + SN-02 gate)",
    }
