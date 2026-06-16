"""SN-07 (#91): LED-budget selection policy -- choose the camera subset + per-LED intensity that best
illuminates the hard shadows, within the active-camera count and the power budget.

Near the pole, hard self-/terrain shadows leave regions too dark for stereo. Each camera carries an LED
that lights the scene in its facing direction (the LAC-twin 8-cam rig azimuths, dart.camera_select). A
hard shadow is a (body-azimuth, need) target -- `need` in (0, 1] is how much fill light it wants. An LED
at intensity I (watts = I * led_max_w) delivers I * max(0, cos(separation)) of light to a target (full
dead-ahead, nothing past 90 deg). Two budgets bind: at most `active_cam_limit` cameras on at once, and at
most `power_budget_w` total LED watts. This greedily turns on the camera covering the most still-needed
light per watt until a budget or full coverage is hit. Pure + deterministic; the LED HARDWARE is gated
(SN-07 Q=G), this is the selection POLICY -- geometric, no fabricated photometry.
"""
from __future__ import annotations

import math

from dart.camera_select import CAMERA_RIG

LED_MAX_W = 10.0            # [ASSUMPTION] per-camera LED at full intensity (cf. comparison.shadownav_led_w ~20 W for 2)


def _sep_rad(a_deg: float, b_deg: float) -> float:
    """Minimal angular separation [rad] between two body azimuths."""
    return math.radians(abs((a_deg - b_deg + 180.0) % 360.0 - 180.0))


def _alignment(cam_az_deg: float, shadow_az_deg: float) -> float:
    """Fraction of an LED's light a camera facing cam_az delivers to a shadow at shadow_az: max(0, cos)."""
    return max(0.0, math.cos(_sep_rad(cam_az_deg, shadow_az_deg)))


def select_led_budget(shadow_targets, *, active_cam_limit: int = 2, power_budget_w: float = 20.0,
                      led_max_w: float = LED_MAX_W, rig=CAMERA_RIG) -> dict:
    """Greedily pick camera+LED activations to illuminate the hard-shadow targets within both budgets.

    ``shadow_targets`` = [(body_azimuth_deg, need), ...] with need in (0, 1]. Each iteration turns on the
    still-off camera that reduces the most remaining need (per its facing alignment), at an LED intensity
    scaled to the watts still available (capped by led_max_w), until ``active_cam_limit`` cameras are on,
    the ``power_budget_w`` is spent, or all need is met. Returns the selected cameras + their LED watts/
    intensity, the power used, and the illuminated vs uncovered need."""
    if active_cam_limit < 0 or power_budget_w < 0 or led_max_w <= 0:
        raise ValueError("active_cam_limit/power_budget_w must be >= 0 and led_max_w > 0")
    azs = [float(t[0]) for t in shadow_targets]
    remaining = {i: max(0.0, float(t[1])) for i, t in enumerate(shadow_targets)}
    total_need = sum(remaining.values())
    selected: list = []
    chosen: set = set()
    budget_left = float(power_budget_w)
    while (len(selected) < active_cam_limit and budget_left > 1e-9
           and sum(remaining.values()) > 1e-9):
        best = None                                        # (camera, marginal_cover, cam_az)
        for cam, (cam_az, _pair) in rig.items():
            if cam in chosen:
                continue
            cover = sum(remaining[i] * _alignment(cam_az, azs[i]) for i in remaining)
            if cover > 1e-9 and (best is None or cover > best[1]):
                best = (cam, cover, cam_az)
        if best is None:
            break                                          # no camera can reach any remaining shadow
        cam, _cover, cam_az = best
        led_w = min(led_max_w, budget_left)                # intensity scaled to the watts still available
        intensity = led_w / led_max_w
        selected.append({"camera": cam, "led_w": round(led_w, 2), "intensity": round(intensity, 3)})
        chosen.add(cam)
        budget_left -= led_w
        for i in list(remaining):                          # this LED reduces the need it can reach
            remaining[i] = max(0.0, remaining[i] - intensity * _alignment(cam_az, azs[i]))
    uncovered = sum(remaining.values())
    return {
        "selected": selected,
        "n_cameras": len(selected),
        "power_used_w": round(power_budget_w - budget_left, 2),
        "illuminated_need": round(total_need - uncovered, 3),
        "uncovered_need": round(uncovered, 3),
    }
