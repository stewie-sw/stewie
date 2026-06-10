"""Independent per-pixel depth truth for rendered stereo captures (G2 blocker 1).

Geometric ray-cast of the AUTHORITY scene (heightfield + analytic clast spheres) from the
EVALUATION-channel camera pose. Independent of the stereo matcher by construction: no image
pixels are consumed -- only the conserved scene geometry and the truth pose (I3: this module
lives on the evaluation side and must never feed the runtime).

Conventions: Godot world is Y-up; the camera optical frame is +Z forward / +X right / +Y down
(pinhole, zero distortion in the committed rig). Output is per-pixel DEPTH (optical-frame Z),
matching ``dart.stereo_depth`` (fx * baseline / disparity).
"""
from __future__ import annotations

import json
import os

import numpy as np


def _quat_to_R(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def load_scene_geometry(scene_dir: str) -> dict:
    """Heightfield + clast spheres + world bounds from a committed authority scene."""
    meta = json.load(open(os.path.join(scene_dir, "metadata.json")))
    g = meta["grid"]
    H = np.fromfile(os.path.join(scene_dir, "heightmap.rf32"), dtype="<f4").reshape(
        g["height"], g["width"]).astype(np.float64)
    wb = meta["world_bounds_m"]                      # authority frame: x = col, y(row) -> world Z
    xb, zb = (wb["x0"], wb["x1"]), (wb["y0"], wb["y1"])
    clasts = [(np.array(c["center_m"], float), float(c["radius_m"]))
              for c in meta.get("clasts", []) if c.get("shape") == "sphere"]
    return {"H": H, "cell": float(g["cell_m"]), "x0": float(xb[0]), "z0": float(zb[0]),
            "nx": g["width"], "nz": g["height"], "clasts": clasts}


def _terrain_height(geo, x, z):
    """Bilinear heightfield sample at world (x, z); NaN outside the patch."""
    c = (x - geo["x0"]) / geo["cell"]
    r = (z - geo["z0"]) / geo["cell"]
    ok = (c >= 0) & (c <= geo["nx"] - 1) & (r >= 0) & (r <= geo["nz"] - 1)
    c0 = np.clip(np.floor(c).astype(int), 0, geo["nx"] - 2)
    r0 = np.clip(np.floor(r).astype(int), 0, geo["nz"] - 2)
    fc, fr = c - c0, r - r0
    Hm = geo["H"]
    h = (Hm[r0, c0] * (1 - fr) * (1 - fc) + Hm[r0, c0 + 1] * (1 - fr) * fc
         + Hm[r0 + 1, c0] * fr * (1 - fc) + Hm[r0 + 1, c0 + 1] * fr * fc)
    return np.where(ok, h, np.nan)


def ray_cast_depth(camera: dict, scene_dir: str, *, stride: int = 4,
                   t_max: float = 12.0, dt: float = 0.01) -> dict:
    """Per-pixel truth depth for one camera (strided pixel grid).

    camera: an evaluation_truth camera entry merged with the runtime intrinsics --
    needs pose_in_world {position_m, quaternion_xyzw} + intrinsics {fx, cx, cy} + width/height.
    Returns {"depth_m": (h', w') array, "rows", "cols"} with NaN where no scene hit.
    """
    pos = np.array(camera["pose_in_world"]["position_m"], float)
    R = _quat_to_R(camera["pose_in_world"]["quaternion_xyzw"])
    fx = float(camera["intrinsics"]["fx"]); cx = float(camera["intrinsics"]["cx"])
    fy = float(camera["intrinsics"].get("fy", fx)); cy = float(camera["intrinsics"]["cy"])
    W, Hpx = int(camera["width"]), int(camera["height"])
    geo = load_scene_geometry(scene_dir)

    cols = np.arange(0, W, stride); rows = np.arange(0, Hpx, stride)
    uu, vv = np.meshgrid(cols, rows)
    # optical-frame ray directions (+Z forward, +Y down)
    d_opt = np.stack([(uu - cx) / fx, (vv - cy) / fy, np.ones_like(uu, float)], axis=-1)
    d_opt /= np.linalg.norm(d_opt, axis=-1, keepdims=True)
    # the stored pose is the GODOT camera node (looks along -Z, +Y up); optical (+Z fwd, +Y down)
    # maps into it as (x, -y, -z)
    d_cam = np.stack([d_opt[..., 0], -d_opt[..., 1], -d_opt[..., 2]], axis=-1)
    d_w = d_cam @ R.T                                            # world-frame directions

    sh = uu.shape
    t_hit = np.full(sh, np.nan)
    # heightfield: fixed-step march, first crossing below terrain (Y-up -> height is y)
    t = np.full(sh, dt)
    alive = np.ones(sh, bool)
    prev_above = np.ones(sh, bool)
    while np.any(alive) and t.max() <= t_max:
        p = pos[None, None, :] + d_w * t[..., None]
        h = _terrain_height(geo, p[..., 0], p[..., 2])
        above = (p[..., 1] > h) | np.isnan(h)
        crossed = alive & prev_above & ~above & ~np.isnan(h)
        t_hit = np.where(crossed & np.isnan(t_hit), t, t_hit)
        alive &= ~crossed
        prev_above = above
        t = t + dt
    # clast spheres: exact intersection, keep the nearest hit overall
    oc_all = None
    for c, r_s in geo["clasts"]:
        oc = pos - c
        b = np.sum(d_w * oc[None, None, :], axis=-1)
        disc = b * b - (oc @ oc - r_s * r_s)
        t_s = -b - np.sqrt(np.maximum(disc, 0.0))
        hit = (disc > 0) & (t_s > 0) & (t_s < t_max)
        t_s = np.where(hit, t_s, np.nan)
        oc_all = t_s if oc_all is None else np.fmin(oc_all, t_s)
    if oc_all is not None:
        t_hit = np.fmin(t_hit, oc_all)
    # range along the ray -> optical-frame DEPTH (Z component)
    depth = t_hit * d_opt[..., 2]
    return {"depth_m": depth, "rows": rows, "cols": cols}


def compare_with_stereo(truth: dict, stereo_depth_m: np.ndarray,
                        valid_mask: np.ndarray) -> dict:
    """Residual statistics of stereo depth vs geometric truth on LR-consistent pixels."""
    r, c = np.meshgrid(truth["rows"], truth["cols"], indexing="ij")
    sd = stereo_depth_m[r, c]
    vm = valid_mask[r, c] & np.isfinite(truth["depth_m"]) & np.isfinite(sd)
    res = (sd - truth["depth_m"])[vm]
    if res.size == 0:
        raise RuntimeError("no overlapping valid pixels between stereo and truth")
    return {"n": int(res.size),
            "median_abs_err_m": float(np.median(np.abs(res))),
            "bias_m": float(np.median(res)),
            "p95_abs_err_m": float(np.percentile(np.abs(res), 95))}
