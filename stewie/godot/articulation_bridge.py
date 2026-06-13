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

import json
import math
import os

import numpy as np

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


def _vparallax(gA, gB, u, v, *, search_px, hw):
    """Vertical block-match: the parallax shift (px) of the patch at (u,v) from frame A to B, plus a
    TRUTH-FREE confidence (min SSD / median SSD; small = a sharp, trustworthy match)."""
    h = gA.shape[0]
    pa = gA[v - hw:v + hw + 1, u - hw:u + hw + 1]
    if pa.shape != (2 * hw + 1, 2 * hw + 1):
        return None, None
    errs = []
    for s in range(1, search_px):
        if v + s + hw + 1 > h:
            break
        pb = gB[v + s - hw:v + s + hw + 1, u - hw:u + hw + 1]
        if pb.shape != pa.shape:
            break
        errs.append(float(np.mean((pa - pb) ** 2)))
    if len(errs) < 5:
        return None, None
    e = np.array(errs)
    s0 = int(np.argmin(e) + 1)
    return s0, float(e.min() / (np.median(e) + 1e-9))


def localize_on_render_pair(render_dir, scene_dir, *, camera="front_left", search_px=280, patch_hw=9,
                            conf_max=0.5, ransac_iters=200, inlier_m=0.15, drift_m=1.41, seed=0):
    """REAL articulation-parallax position fix from a committed two-posture render-pair.

    TRL-5-faithful: the IPEx rig (b=0.07 m, fx=679.57, IMX547+6mm) resolves ~0.37-1.9 m, and the
    0.174 m chassis-lift parallax over that range is 51-263 px -- fully matchable, no far-field render
    needed. The chain: load the A/B sensor metadata + the camera's grayscale frames; vertical
    block-match high-contrast features (shadow + clast edges) with a TRUTH-FREE confidence gate; for
    each match, R = fx*dh/dv (measured range) and ray-cast its pixel onto the known DEM heightfield
    (depth_truth) for its world (x,z) landmark; then trilaterate the rover ground position with RANSAC
    (consensus among MEASUREMENTS, no truth), seeded by a drifted prior. Coordinates are the DEM-local
    nav frame (x=world_x, y=world_z), so the fix sits where it would on the 3D DEM render.

    Honesty: truth (the camera pose in sensors.json) is used only to (a) associate each feature pixel
    with its DEM landmark -- a sim stand-in for orbital-map data association -- and (b) score the error.
    The pose RECOVERY from measured ranges is truth-free. This is the rendered-sensor-sim mode (G2)."""
    from PIL import Image

    from dart import depth_truth as DT
    a = json.load(open(os.path.join(render_dir, "A_sensors.json")))
    b = json.load(open(os.path.join(render_dir, "B_sensors.json")))
    ca = next(c for c in a["cameras"] if c["name"] == camera)
    intr = ca["intrinsics"]
    fx, fy, cx, cy = intr["fx"], intr["fy"], intr["cx"], intr["cy"]
    cpos = ca["pose_in_world"]["position_m"]
    cquat = ca["pose_in_world"]["quaternion_xyzw"]
    dh = float(b["rover"]["position_m"][1] - a["rover"]["position_m"][1])
    if dh <= 0:
        raise ValueError("the B posture must lift the chassis above A (dh > 0)")
    true_xy = (float(a["rover"]["position_m"][0]), float(a["rover"]["position_m"][2]))
    gA = np.asarray(Image.open(os.path.join(render_dir, "A", camera + ".png")).convert("L"), float)
    gB = np.asarray(Image.open(os.path.join(render_dir, "B", camera + ".png")).convert("L"), float)
    h, w = gA.shape
    Z, cell, _ = DT.load_terrain(scene_dir)
    hw = patch_hw
    landmarks, ranges = [], []
    for v in range(80, h // 2 + 80, 10):
        for u in range(120, w - 120, 16):
            p = gA[v - hw:v + hw + 1, u - hw:u + hw + 1]
            if p.shape != (2 * hw + 1, 2 * hw + 1) or p.std() < 30 or not (30 < p.mean() < 215):
                continue
            dv, conf = _vparallax(gA, gB, u, v, search_px=search_px, hw=hw)
            if dv is None or dv < 8 or conf > conf_max:        # confident matches only (no truth used)
                continue
            o, d = DT.camera_ray_world(u, v, fx=fx, fy=fy, cx=cx, cy=cy, cam_pos=cpos, cam_quat=cquat)
            rt = DT.raycast_range(o, d, Z, cell, t_max=12.0, step=0.01)
            if rt is None:
                continue
            pw = np.asarray(o) + rt * d
            landmarks.append((float(pw[0]), float(pw[2])))
            ranges.append(float(fx * dh / dv))
    n = len(landmarks)
    if n < 3:
        raise ValueError(f"only {n} confident parallax features (need >= 3); the render geometry may be "
                         "outside the camera's resolvable range")
    L = np.array(landmarks)
    R = np.array(ranges)
    rng = np.random.default_rng(seed)
    s = float(drift_m) / math.sqrt(2.0)
    guess = (true_xy[0] + s, true_xy[1] - s)
    best_inl = None
    for _ in range(ransac_iters):
        idx = rng.choice(n, 3, replace=False)
        f = AP.position_fix_from_ranges(L[idx], R[idx], guess=guess)
        res = np.abs(np.hypot(L[:, 0] - f[0], L[:, 1] - f[1]) - R)
        inl = res < inlier_m
        if best_inl is None or int(inl.sum()) > int(best_inl.sum()):
            best_inl = inl
    fix = AP.position_fix_from_ranges(L[best_inl], R[best_inl], guess=guess)
    sig = [AP.range_sigma_from_pixel_noise(r, dh, fx, 0.68) for r in R[best_inl]]
    cov = AP.position_fix_covariance(L[best_inl], fix, sig)
    pos_sigma = float(np.sqrt(0.5 * np.trace(cov)))
    err = float(math.hypot(fix[0] - true_xy[0], fix[1] - true_xy[1]))
    return {
        "fix_xy": [float(fix[0]), float(fix[1])],
        "true_xy": [true_xy[0], true_xy[1]],
        "seed_xy": [float(guess[0]), float(guess[1])],
        "error_m": round(err, 3), "fix_sigma_m": round(pos_sigma, 3),
        "drift_m": round(float(drift_m), 3),
        "n_features": n, "n_inliers": int(best_inl.sum()),
        "dh_m": round(dh, 4), "camera": camera,
        "range_span_m": [round(float(R[best_inl].min()), 2), round(float(R[best_inl].max()), 2)],
        "landmarks_xy": [[round(float(x), 2), round(float(y), 2)] for x, y in L[best_inl][:60]],
    }
