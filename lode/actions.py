"""#57: perception-gated action types -- planning and perception intertwined (Aaron 2026-06-10).

An action type declares its PERCEPTION PRECONDITIONS, and the planner validates them against the
world model at the action's time and place (PLANNING_REVISION §2). The first gated action is
DockWithLander: a precision approach that needs the lander's AprilTag VISIBLE -- tag-lock needs
light, and acquisition has a range ceiling. The illumination check is the same horizon-clip
authority the shadow layer renders; nothing here invents a second truth.

Phases (the executive runs them as gated steps, stop-on-anomaly as everywhere):
    goto_coarse -> acquire_tag -> visual_servo -> dock
"""
from __future__ import annotations

import math

#: the range [m] beyond which the 0.1524 m tag cannot be acquired by the flight camera --
#: STEREO-class resolvability; conservative, derived from the calibrated rig's tag work
#: (the g2cal series resolved the tag to ~12.7 mm pose error inside ~3 m; acquisition is
#: modeled an order of magnitude beyond that working envelope).
TAG_ACQUIRE_RANGE_M = 30.0

DOCK_PHASES = ("goto_coarse", "acquire_tag", "visual_servo", "dock")


def validate_dock(site_xy, *, dem_pair, sun_az: float, sun_el: float,
                  approach_from_xy=None) -> dict:
    """Validate a DockWithLander at ``site_xy`` (site-frame meters) against the perception
    preconditions: the dock cell must be ILLUMINATED at the given sun (tag-lock needs light),
    and -- advisory -- the approach start should sit inside tag-acquisition range."""
    import numpy as np

    from dart.illumination import horizon_clip
    dem, cell_m = dem_pair
    Z = np.asarray(dem, dtype=float)
    lit = horizon_clip(Z, float(cell_m), float(sun_az), float(sun_el))
    c = min(max(int(round(site_xy[0] / cell_m)), 0), Z.shape[1] - 1)
    r = min(max(int(round(site_xy[1] / cell_m)), 0), Z.shape[0] - 1)
    illuminated = bool(lit[r, c])
    warnings: list = []
    if approach_from_xy is not None:
        d = math.hypot(approach_from_xy[0] - site_xy[0], approach_from_xy[1] - site_xy[1])
        if d > TAG_ACQUIRE_RANGE_M:
            warnings.append(f"approach start {d:.0f} m out -- beyond tag acquisition "
                            f"({TAG_ACQUIRE_RANGE_M:.0f} m); the goto_coarse leg must close to "
                            "range before acquire_tag can gate")
    if not illuminated:
        return {"ok": False, "illuminated": False, "phases": list(DOCK_PHASES),
                "reason": f"dock site ({site_xy[0]:.0f}, {site_xy[1]:.0f}) m is in SHADOW at "
                          f"sun az {sun_az:.0f}° el {sun_el:.1f}° -- the AprilTag cannot be "
                          "acquired; replan the dock into a lit window (the shadow layer shows "
                          "when)", "warnings": warnings}
    return {"ok": True, "illuminated": True, "phases": list(DOCK_PHASES), "warnings": warnings}
