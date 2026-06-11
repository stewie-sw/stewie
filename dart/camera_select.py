"""SN-06: camera direction + exposure selection to avoid low-sun washout while keeping stereo.

The LAC-twin 8-camera rig has FRONT and BACK stereo pairs (0.07 m baseline) 180 deg apart, plus
side + drum-arm monos. Near the pole the sun grazes the horizon, so a camera looking TOWARD a
low sun washes out (saturates). This policy scores each camera's washout risk from its body
azimuth vs the sun, then picks the stereo pair that best avoids the sun (and a shorter exposure
when bright) -- preserving a usable stereo pair where a fixed front-only baseline would wash out.
Geometric, real rig azimuths + the real sun vector; no fabricated imagery.
"""
from __future__ import annotations

import math

#: 8-camera rig: name -> (body azimuth [deg], stereo-pair tag). Front/back pairs 180 deg apart.
CAMERA_RIG = {
    "front_left": (0.0, "front"), "front_right": (0.0, "front"),
    "back_left": (180.0, "back"), "back_right": (180.0, "back"),
    "side_left": (90.0, None), "side_right": (270.0, None),
    "arm_front": (0.0, None), "arm_back": (180.0, None),
}
STEREO_PAIRS = ("front", "back")
GRAZING_EL_DEG = 15.0          # below this the sun is low enough to wash out a camera facing it


def washout_risk(cam_az_deg: float, sun_az_body_deg: float, sun_el_deg: float) -> float:
    """[0,1] saturation risk: high when the camera looks TOWARD the sun (small azimuth separation)
    AND the sun is low (grazing). 0 when the sun is high or behind the camera."""
    if sun_el_deg >= GRAZING_EL_DEG:
        return 0.0
    sep = math.radians(abs((cam_az_deg - sun_az_body_deg + 180.0) % 360.0 - 180.0))
    facing = max(0.0, math.cos(sep))                       # 1 looking at the sun, 0 perpendicular/away
    low = (GRAZING_EL_DEG - sun_el_deg) / GRAZING_EL_DEG    # 0 at grazing edge -> 1 at horizon
    return float(facing * low)


def select_view(sun_az_body_deg: float, sun_el_deg: float, *, washout_thresh: float = 0.5) -> dict:
    """Pick the stereo pair with the lowest worst-camera washout + an exposure hint. Returns
    {pair, max_washout, usable, exposure}."""
    best: tuple[str, float] = (STEREO_PAIRS[0], 1e9)     # always overwritten on the first pair
    for pair in STEREO_PAIRS:
        cams = [az for az, p in CAMERA_RIG.values() if p == pair]
        worst = max(washout_risk(az, sun_az_body_deg, sun_el_deg) for az in cams)
        if worst < best[1]:
            best = (pair, worst)
    pair, worst = best
    # exposure: shorten when any usable view is bright-ish (washout proxy); a coarse 2-level hint
    exposure = "short" if worst > 0.2 else "nominal"
    return {"pair": pair, "max_washout": round(worst, 3),
            "usable": worst < washout_thresh, "exposure": exposure}


def usable_fraction(policy, sun_el_deg: float, *, n_az: int = 72) -> float:
    """Fraction of body-sun azimuths (a full rotation) for which ``policy`` yields a usable pair."""
    ok = 0
    for k in range(n_az):
        az = 360.0 * k / n_az
        if policy(az, sun_el_deg)["usable"]:
            ok += 1
    return ok / n_az
