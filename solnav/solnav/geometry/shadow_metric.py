"""Cast-shadow metric geometry (Algorithm P5, spec sec 16): recover a feature's HEIGHT from the
ground-plane length of its cast shadow, H = L * tan(e).

This module is the GEOMETRY (pinhole ray -> ground-plane intersection -> length -> height, plus the
first-order uncertainty), with an orthographic top-down helper. Validated two ways: (1) geometric
identity (project known ground points through a perspective camera, recover them exactly); (2) a
controlled rendered-sensor fixture in `render/p5proj/`. The latter supplies camera scale, Sun
elevation, and caster base from scene configuration, extracts the shadow tip from pixels, and
recovers H = 0.95 m (~5% error).
"""
from __future__ import annotations

import numpy as np


def _camera_parameters(W, H, fov_deg):
    width = float(W)
    height = float(H)
    fov = float(fov_deg)
    if not np.isfinite([width, height, fov]).all() or width <= 0 or height <= 0:
        raise ValueError("image dimensions must be finite and positive")
    if not 0.0 < fov < 180.0:
        raise ValueError("vertical FOV must be in (0, 180) deg")
    tan_v = np.tan(np.radians(fov) / 2.0)
    return width, height, tan_v, tan_v * (width / height)


def look_at_basis(eye, target, up=(0.0, 1.0, 0.0)):
    """Godot-style camera basis (the camera looks along -Z = view/forward). Returns
    (right, true_up, forward) world unit vectors."""
    eye = np.asarray(eye, float); target = np.asarray(target, float); up = np.asarray(up, float)
    if eye.shape != (3,) or target.shape != (3,) or up.shape != (3,):
        raise ValueError("eye, target, and up must be 3-vectors")
    if not np.isfinite(eye).all() or not np.isfinite(target).all() or not np.isfinite(up).all():
        raise ValueError("camera vectors must contain only finite values")
    forward = target - eye
    forward_norm = np.linalg.norm(forward)
    if forward_norm <= np.finfo(float).eps:
        raise ValueError("eye and target must be distinct")
    forward /= forward_norm
    right = np.cross(forward, up)
    right_norm = np.linalg.norm(right)
    if right_norm <= np.finfo(float).eps:
        raise ValueError("up vector must not be parallel to the viewing direction")
    right /= right_norm
    true_up = np.cross(right, forward)
    return right, true_up, forward


def project(p, eye, basis, W, H, fov_deg):
    """Forward pinhole projection: world point -> pixel (u, v). fov is VERTICAL (Godot default)."""
    width, height, tan_v, tan_h = _camera_parameters(W, H, fov_deg)
    right, true_up, forward = (np.asarray(axis, float) for axis in basis)
    rel = np.asarray(p, float) - np.asarray(eye, float)
    if rel.shape != (3,) or any(axis.shape != (3,) for axis in (right, true_up, forward)):
        raise ValueError("point, eye, and basis axes must be 3-vectors")
    if not np.isfinite(np.concatenate((rel, right, true_up, forward))).all():
        raise ValueError("projection inputs must contain only finite values")
    cz = float(rel @ forward)
    if cz <= 1e-9:
        raise ValueError("point behind camera")
    cx = float(rel @ right); cy = float(rel @ true_up)
    u = width * ((cx / (cz * tan_h)) + 1.0) / 2.0 - 0.5
    v = height * (1.0 - (cy / (cz * tan_v))) / 2.0 - 0.5
    return np.array([u, v])


def pixel_to_ground(u, v, eye, basis, W, H, fov_deg, ground_y=0.0):
    """Back-project a pixel to its intersection with the ground plane y = ground_y (Godot Y-up).
    Raises if the ray does not descend to the plane (the spec's ground-intersection gate)."""
    width, height, tan_v, tan_h = _camera_parameters(W, H, fov_deg)
    if not np.isfinite([u, v, ground_y]).all():
        raise ValueError("pixel and ground coordinates must be finite")
    right, true_up, forward = (np.asarray(axis, float) for axis in basis)
    nx = (2.0 * (u + 0.5) / width - 1.0) * tan_h
    ny = (1.0 - 2.0 * (v + 0.5) / height) * tan_v
    ray = nx * right + ny * true_up + forward
    ray = ray / np.linalg.norm(ray)
    eye = np.asarray(eye, float)
    if abs(ray[1]) <= 1e-9:
        raise ValueError("ray is parallel to the ground plane")
    t = (ground_y - eye[1]) / ray[1]
    if t < 0.0:
        raise ValueError("ground-plane intersection is behind the camera")
    return eye + t * ray


def shadow_height_from_pixels(base_uv, tip_uv, eye, basis, W, H, fov_deg,
                              sun_elev_deg, ground_y=0.0):
    """H = L * tan(e), where L is the ground distance between the shadow base and tip pixels
    back-projected onto the ground plane. Returns (H_m, L_m)."""
    if not np.isfinite(sun_elev_deg) or not 0.0 < sun_elev_deg < 90.0:
        raise ValueError("Sun elevation must be finite and in (0, 90) deg")
    pb = pixel_to_ground(base_uv[0], base_uv[1], eye, basis, W, H, fov_deg, ground_y)
    pt = pixel_to_ground(tip_uv[0], tip_uv[1], eye, basis, W, H, fov_deg, ground_y)
    L = float(np.linalg.norm((pt - pb)[[0, 2]]))      # horizontal (ground) separation
    return float(L * np.tan(np.radians(sun_elev_deg))), L


def shadow_height_sigma(L_m, sun_elev_deg, sigma_L_m, sigma_e_deg):
    """First-order height uncertainty (spec sec 16, the two measurement terms):
        sigma_H^2 = tan(e)^2 sigma_L^2 + L^2 sec(e)^4 sigma_e^2.
    (The plane-normal and extrinsic Jacobian terms require their covariances and are additive.)"""
    values = np.asarray([L_m, sun_elev_deg, sigma_L_m, sigma_e_deg], float)
    if not np.isfinite(values).all():
        raise ValueError("shadow uncertainty inputs must be finite")
    if L_m < 0.0 or sigma_L_m < 0.0 or sigma_e_deg < 0.0:
        raise ValueError("length and standard deviations must be nonnegative")
    if not 0.0 < sun_elev_deg < 90.0:
        raise ValueError("Sun elevation must be in (0, 90) deg")
    e = np.radians(sun_elev_deg); se = np.radians(sigma_e_deg)
    var = np.tan(e) ** 2 * sigma_L_m ** 2 + L_m ** 2 * (1.0 / np.cos(e)) ** 4 * se ** 2
    return float(np.sqrt(var))


def shadow_height_ortho(base_px, tip_px, m_per_px, sun_elev_deg):
    """P5 for a TOP-DOWN ORTHOGRAPHIC frame: image distance maps directly to ground distance, so
    L = |tip - base| * m_per_px and H = L * tan(e). Returns (H_m, L_m)."""
    base = np.asarray(base_px, float)
    tip = np.asarray(tip_px, float)
    if base.shape != (2,) or tip.shape != (2,):
        raise ValueError("base_px and tip_px must be 2-vectors")
    if not np.isfinite(np.concatenate((base, tip, [m_per_px, sun_elev_deg]))).all():
        raise ValueError("orthographic shadow inputs must be finite")
    if m_per_px <= 0:
        raise ValueError("m_per_px must be finite and positive")
    if not 0.0 < sun_elev_deg < 90.0:
        raise ValueError("Sun elevation must be in (0, 90) deg")
    L = float(np.linalg.norm(tip - base) * m_per_px)
    return float(L * np.tan(np.radians(sun_elev_deg))), L
