"""Cast-shadow metric geometry (Algorithm P5, spec sec 16): recover a feature's HEIGHT from the
ground-plane length of its cast shadow, H = L * tan(e).

This module is the GEOMETRY (pinhole ray -> ground-plane intersection -> length -> height, plus the
first-order uncertainty). It is validated by geometric identity (project known ground points through
the camera, recover them exactly). NOTE (honest): a real-IMAGE P5 number is currently BLOCKED on the
available read-only dustgym assets -- the cube render has no ground cast shadow (directional shadows
off) and the crater_boulders clasts are 2-30 cm (sub-pixel-to-noise shadows at 512 px). A clean
real-image validation needs a meter-scale feature with a fully-visible cast shadow at a moderate Sun,
i.e. a new render scene (an edit to John's read-only godot_sidecar) -- not produced here.
"""
from __future__ import annotations

import numpy as np


def look_at_basis(eye, target, up=(0.0, 1.0, 0.0)):
    """Godot-style camera basis (the camera looks along -Z = view/forward). Returns
    (right, true_up, forward) world unit vectors."""
    eye = np.asarray(eye, float); target = np.asarray(target, float); up = np.asarray(up, float)
    forward = target - eye; forward /= np.linalg.norm(forward)
    right = np.cross(forward, up); right /= np.linalg.norm(right)
    true_up = np.cross(right, forward)
    return right, true_up, forward


def project(p, eye, basis, W, H, fov_deg):
    """Forward pinhole projection: world point -> pixel (u, v). fov is VERTICAL (Godot default)."""
    right, true_up, forward = basis
    rel = np.asarray(p, float) - np.asarray(eye, float)
    cz = float(rel @ forward)
    if cz <= 1e-9:
        raise ValueError("point behind camera")
    cx = float(rel @ right); cy = float(rel @ true_up)
    tan_v = np.tan(np.radians(fov_deg) / 2.0); tan_h = tan_v * (W / H)
    u = W * ((cx / (cz * tan_h)) + 1.0) / 2.0 - 0.5
    v = H * (1.0 - (cy / (cz * tan_v))) / 2.0 - 0.5
    return np.array([u, v])


def pixel_to_ground(u, v, eye, basis, W, H, fov_deg, ground_y=0.0):
    """Back-project a pixel to its intersection with the ground plane y = ground_y (Godot Y-up).
    Raises if the ray does not descend to the plane (the spec's ground-intersection gate)."""
    right, true_up, forward = basis
    tan_v = np.tan(np.radians(fov_deg) / 2.0); tan_h = tan_v * (W / H)
    nx = (2.0 * (u + 0.5) / W - 1.0) * tan_h
    ny = (1.0 - 2.0 * (v + 0.5) / H) * tan_v
    ray = nx * right + ny * true_up + forward
    ray = ray / np.linalg.norm(ray)
    eye = np.asarray(eye, float)
    if ray[1] >= -1e-9:                       # not pointing down toward the plane
        raise ValueError("ray does not intersect the ground plane below the camera")
    t = (ground_y - eye[1]) / ray[1]
    return eye + t * ray


def shadow_height_from_pixels(base_uv, tip_uv, eye, basis, W, H, fov_deg,
                              sun_elev_deg, ground_y=0.0):
    """H = L * tan(e), where L is the ground distance between the shadow base and tip pixels
    back-projected onto the ground plane. Returns (H_m, L_m)."""
    pb = pixel_to_ground(base_uv[0], base_uv[1], eye, basis, W, H, fov_deg, ground_y)
    pt = pixel_to_ground(tip_uv[0], tip_uv[1], eye, basis, W, H, fov_deg, ground_y)
    L = float(np.linalg.norm((pt - pb)[[0, 2]]))      # horizontal (ground) separation
    return float(L * np.tan(np.radians(sun_elev_deg))), L


def shadow_height_sigma(L_m, sun_elev_deg, sigma_L_m, sigma_e_deg):
    """First-order height uncertainty (spec sec 16, the two measurement terms):
        sigma_H^2 = tan(e)^2 sigma_L^2 + L^2 sec(e)^4 sigma_e^2.
    (The plane-normal and extrinsic Jacobian terms require their covariances and are additive.)"""
    e = np.radians(sun_elev_deg); se = np.radians(sigma_e_deg)
    var = np.tan(e) ** 2 * sigma_L_m ** 2 + L_m ** 2 * (1.0 / np.cos(e)) ** 4 * se ** 2
    return float(np.sqrt(var))
