"""Depth pass (truth): ray-cast the known terrain height field from the known camera pose.

The Godot sidecar emits no per-camera depth, and the rig stereo block-match is unreliable on
low-texture shadowed scenes, so per-feature photometric TRUTH is recovered geometrically: a STEWIE
scene carries an exact heightmap (metadata.json: cell_m, world bounds) and the Field->Godot mapping
is x=col*cell, y=height, z=row*cell (Y-up, origin at the min corner). Given a camera pose + intrinsics
(sensors.json), each pixel's ray is marched against the height field to its first intersection; the
distance from the camera is the true range. This turns the photometric render-pair into a
measured-vs-truth check. Exact geometry; no fabricated depth.
"""
from __future__ import annotations

import json
import os

import numpy as np


def load_terrain(scene_dir: str):
    """Load (heightmap[H,W] m, cell_m, (x0,y0,x1,y1)) from a STEWIE scene dir."""
    meta = json.load(open(os.path.join(scene_dir, "metadata.json")))
    g = meta["grid"]; w, h, cell = int(g["width"]), int(g["height"]), float(g["cell_m"])
    Z = np.fromfile(os.path.join(scene_dir, "heightmap.rf32"), dtype="<f4").reshape(h, w)
    b = meta["world_bounds_m"]
    return Z, cell, (b["x0"], b["y0"], b["x1"], b["y1"])


def _quat_rotate(q, v):
    """Rotate vector v by quaternion q = (x,y,z,w)."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v); v' = v + w*t + cross(q.xyz, t)
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    return np.array([vx + w * tx + (y * tz - z * ty),
                     vy + w * ty + (z * tx - x * tz),
                     vz + w * tz + (x * ty - y * tx)])


def camera_ray_world(u, v, *, fx, fy, cx, cy, cam_pos, cam_quat):
    """World-frame ray (origin, unit dir) for image pixel (u,v). Godot camera looks down local -Z,
    +X right, +Y up; image y is down."""
    d_cam = np.array([(u - cx) / fx, -(v - cy) / fy, -1.0])
    d_world = _quat_rotate(cam_quat, d_cam)
    n = np.linalg.norm(d_world)
    return np.asarray(cam_pos, float), (d_world / n if n > 0 else d_world)


def _height_at(Z, cell, x, z):
    """Bilinear terrain height (world y) at world (x,z); None if outside the patch."""
    h, w = Z.shape
    c, r = x / cell, z / cell
    if c < 0 or r < 0 or c >= w - 1 or r >= h - 1:
        return None
    c0, r0 = int(c), int(r); fc, fr = c - c0, r - r0
    return float((1 - fr) * ((1 - fc) * Z[r0, c0] + fc * Z[r0, c0 + 1])
                 + fr * ((1 - fc) * Z[r0 + 1, c0] + fc * Z[r0 + 1, c0 + 1]))


def raycast_range(origin, direction, Z, cell, *, t_max=12.0, step=0.01):
    """March the ray until it dips below the terrain; return the range [m] at the crossing (None if
    it never hits within t_max)."""
    prev_above = None; prev_t = 0.0
    t = step
    while t <= t_max:
        p = origin + t * direction
        gh = _height_at(Z, cell, p[0], p[2])
        if gh is not None:
            above = p[1] > gh
            if prev_above is False and above is False:
                pass
            if prev_above is not None and above != prev_above:
                return float(0.5 * (t + prev_t))           # bracketed the surface crossing
            prev_above = above; prev_t = t
        t += step
    return None


def pixel_truth_range(u, v, *, scene_dir, cam_pos, cam_quat, fx, fy, cx, cy, **kw):
    Z, cell, _ = load_terrain(scene_dir)
    o, d = camera_ray_world(u, v, fx=fx, fy=fy, cx=cx, cy=cy, cam_pos=cam_pos, cam_quat=cam_quat)
    return raycast_range(o, d, Z, cell, **kw)
