"""SN-10 Godot tie-in: render-at-posture capture -> shadow-tip pixel measurement -> estimator.

This is the SENSOR-side wiring of the articulation-parallax instrument (SN-09/SN-10), so the pixel
shift the estimator consumes is a RENDERED measurement, not only analytic. The render-at-posture
seam already exists in the Godot sidecar (--chassis-lift / --sun-elev / --sun-azim, used by
posture_camera_gif.py); this module:

  parallax_capture_plan(...)  -> the two render commands (posture A + posture B) a GPU host runs to
                                 capture the standstill parallax pair (distinct chassis-lift, same
                                 sun + scene, the 8-camera rig).
  shadow_tip_px(frame, ...)   -> the shadow-tip pixel position in a rendered grayscale frame
                                 (wraps dart.shadow_height.measure_shadow_length_px).
  localize_from_frames(...)   -> measures the shadow-tip pixel SHIFT between the two posture frames
                                 and injects the fix into the live PoseGraphSE2 (articulation_localize).

The GPU photometric render (Hapke/Lommel-Seeliger BRDF, dust, lens) is the gated layer; the seam +
the pixel measurement + the estimator hand-off are real and tested here.

NOTE (cross-module): this bridge uses posture_kinematics (the SAME module the Godot render uses), so
the commanded dh is render-consistent. That module's render-side lift DIFFERS from the dart.posture_a3
lift the SN-08/09/10 math used (e.g. IRON_CROSS ~0.20 m in posture_a3 but ~0.00 m in
posture_kinematics; the render's max-lift posture is MEERKAT ~0.174 m, used by posture_camera_gif.py).
Both are ~0.2 m so the feasibility conclusions hold, but the two posture models should be reconciled.
"""
from __future__ import annotations

import math
import os


from dart import articulated_parallax as AP
from dart.shadow_height import anti_solar_dir, measure_shadow_length_px
from stewie.physics import posture_kinematics as pk
from stewie.physics.postures import get_posture

_RENDER = os.path.join(os.path.dirname(__file__), "render_layers.sh")


def chassis_lift_for(posture_name: str) -> float:
    """The commanded camera lift [m] for a named posture (forward kinematics, posture_kinematics)."""
    p = get_posture(posture_name)
    return float(pk.chassis_lift_m(p.arm_front_pitch_rad, p.arm_back_pitch_rad))


def parallax_capture_plan(scene: str, *, sun_az_deg: float, sun_el_deg: float,
                          posture_from: str = "TRANSIT", posture_to: str = "MEERKAT",
                          rover_rc: str = "1000,1000", size: str = "1024x768") -> dict:
    """The two-posture standstill capture: render commands for posture A and B (same scene + sun, the
    8-camera rig, distinct chassis-lift). dh = lift_B - lift_A is the known parallax baseline."""
    lift_a, lift_b = chassis_lift_for(posture_from), chassis_lift_for(posture_to)
    def argv(lift):
        return [_RENDER, "--", "--scene", scene, "--cameras", "--rover-rc", rover_rc,
                "--chassis-lift", f"{lift:.4f}", "--sun-elev", f"{sun_el_deg}",
                "--sun-azim", f"{sun_az_deg}", "--size", size]
    return {"dh_m": float(lift_b - lift_a),
            "frames": [{"posture": posture_from, "chassis_lift_m": lift_a, "argv": argv(lift_a)},
                       {"posture": posture_to, "chassis_lift_m": lift_b, "argv": argv(lift_b)}]}


def shadow_tip_px(frame_gray, anchor_uv, sun_az_deg: float, **kw):
    """The shadow-tip pixel position (u, v) in a rendered grayscale frame: walk the anti-solar ray
    from the feature anchor and return the tip at anchor + length * anti_solar_dir."""
    L = measure_shadow_length_px(frame_gray, anchor_uv[0], anchor_uv[1], sun_az_deg, **kw)
    dx, dy = anti_solar_dir(sun_az_deg)
    return (anchor_uv[0] + L * dx, anchor_uv[1] + L * dy)


def localize_from_frames(graph, node_id, landmarks_xy, frame_pairs, anchors_uv, *,
                         dh_m: float, fx_px: float, sun_az_deg: float, sigma_px: float = 0.3):
    """Measure each landmark's shadow-tip pixel SHIFT between its (posture-A, posture-B) frame pair,
    then inject the standstill fix into the live pose graph (articulation_localize). frame_pairs[i] =
    (frame_a, frame_b); anchors_uv[i] = the feature base pixel in frame A."""
    shifts = []
    for (fa, fb), anchor in zip(frame_pairs, anchors_uv):
        ta = shadow_tip_px(fa, anchor, sun_az_deg)
        tb = shadow_tip_px(fb, anchor, sun_az_deg)
        shifts.append(math.hypot(tb[0] - ta[0], tb[1] - ta[1]))
    return AP.articulation_localize(graph, node_id, landmarks_xy, shifts,
                                    dh_m=dh_m, fx_px=fx_px, sigma_px=sigma_px)
