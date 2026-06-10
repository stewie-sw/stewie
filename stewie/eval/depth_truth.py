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


def _lander_hits(pos, d_w, lander: dict, t_max: float):
    """Nearest ray hit on the procedural tag-stand lander (sensors_emit.build_lander recipe):
    body box size (0.55, 0.6, 0.9) centred at local (-0.295, 0.15, 0) behind the tag plane,
    plus the tag quad (0.15 m * 10/8 quiet ring) at local x=0 facing +X. Legs (r<=4 cm) are
    omitted -- below the comparison stride. Lander frame: origin = tag centre, +X toward rover."""
    Lp = np.array(lander["position_m"], float)
    R_l = _quat_to_R(lander["quaternion_xyzw"])
    o = (pos - Lp) @ R_l                       # ray origin in lander frame (R_l columns = axes)
    d = d_w @ R_l
    # slab test on the body box
    lo = np.array([-0.295 - 0.275, 0.15 - 0.30, -0.45])
    hi = np.array([-0.295 + 0.275, 0.15 + 0.30, 0.45])
    t0 = np.full(d.shape[:2], 1e-9); t1 = np.full(d.shape[:2], t_max)
    for ax in range(3):
        da = d[..., ax]; oa = o[ax]
        with np.errstate(divide="ignore", invalid="ignore"):
            ta = (lo[ax] - oa) / da; tb = (hi[ax] - oa) / da
        tmin = np.fmin(ta, tb); tmax_ = np.fmax(ta, tb)
        par = np.abs(da) < 1e-12               # parallel ray: inside slab or miss
        inside = (oa >= lo[ax]) & (oa <= hi[ax])
        t0 = np.where(par, np.where(inside, t0, np.inf), np.fmax(t0, tmin))
        t1 = np.where(par, np.where(inside, t1, -np.inf), np.fmin(t1, tmax_))
    t_box = np.where((t1 >= t0) & (t0 < t_max), t0, np.nan)
    # tag quad at x=0: size FROM THE SCENE'S OWN TRUTH (size_m; the pinned g2cal corpus says
    # 0.150, new scenes carry the test-site 0.1524 -- TRL5 review T3.5: never assume, always read)
    tag_size = float(lander.get("apriltag", {}).get("size_m", 0.150))
    half = tag_size * (10.0 / 8.0) / 2.0
    with np.errstate(divide="ignore", invalid="ignore"):
        t_q = -o[0] / d[..., 0]
    py = o[1] + d[..., 1] * t_q; pz = o[2] + d[..., 2] * t_q
    qhit = (t_q > 0) & (np.abs(py) <= half) & (np.abs(pz) <= half)
    t_quad = np.where(qhit, t_q, np.nan)
    return np.fmin(t_box, t_quad)


def ray_cast_depth(camera: dict, scene_dir: str, *, stride: int = 4,
                   t_max: float = 12.0, dt: float = 0.01, lander: dict | None = None) -> dict:
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
        if np.any(crossed):
            # bisection refine the crossing to ~dt/256 (mm-level): the raw step quantises the
            # near field by dt, which is tens of disparity px at z ~ 0.1 m
            lo = np.where(crossed, t - dt, 0.0); hi = np.where(crossed, t, 0.0)
            for _ in range(8):
                mid = 0.5 * (lo + hi)
                pm = pos[None, None, :] + d_w * mid[..., None]
                hm = _terrain_height(geo, pm[..., 0], pm[..., 2])
                below = pm[..., 1] <= hm
                hi = np.where(crossed & below, mid, hi)
                lo = np.where(crossed & ~below, mid, lo)
            t_hit = np.where(crossed & np.isnan(t_hit), 0.5 * (lo + hi), t_hit)
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
    if lander is not None:
        t_hit = np.fmin(t_hit, _lander_hits(pos, d_w, lander, t_max))
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


def comparison_keep_mask(camera: dict, truth: dict, scene_dir: str,
                         rover_pose: dict | None = None, *,
                         clast_dilate: float = 1.6, rover_radius_m: float = 0.55,
                         rover_reach_m: float = 1.2) -> np.ndarray:
    """Pixels where the geometric truth is EXACT and unobstructed -- the honest comparison domain.

    Excludes (1) clast projections (the render uses faceted meshes; the metadata spheres are only
    approximate -- dilated by ``clast_dilate``), and (2) the rover's own body (the front cameras image
    the drums/wheels at 0.2-0.4 m; modeled conservatively as a sphere of ``rover_radius_m`` around the
    base position, masking any ray whose closest approach within ``rover_reach_m`` enters it).
    The 0.55 m default envelope comes from VEHICLE GEOMETRY (gauge 0.57 m, wheelbase 0.40 m, drum
    arms ~0.45 m forward), not from tuning toward agreement.
    """
    pos = np.array(camera["pose_in_world"]["position_m"], float)
    R = _quat_to_R(camera["pose_in_world"]["quaternion_xyzw"])
    fx = float(camera["intrinsics"]["fx"]); cx = float(camera["intrinsics"]["cx"])
    fy = float(camera["intrinsics"].get("fy", fx)); cy = float(camera["intrinsics"]["cy"])
    cols, rows = truth["cols"], truth["rows"]
    uu, vv = np.meshgrid(cols, rows)
    d_opt = np.stack([(uu - cx) / fx, (vv - cy) / fy, np.ones_like(uu, float)], axis=-1)
    d_opt /= np.linalg.norm(d_opt, axis=-1, keepdims=True)
    d_cam = np.stack([d_opt[..., 0], -d_opt[..., 1], -d_opt[..., 2]], axis=-1)
    d_w = d_cam @ R.T
    keep = np.ones(uu.shape, bool)
    geo = load_scene_geometry(scene_dir)
    for c, r_s in geo["clasts"]:
        oc = pos - c
        b = np.sum(d_w * oc[None, None, :], axis=-1)
        disc = b * b - (oc @ oc - (clast_dilate * r_s) ** 2)
        keep &= ~((disc > 0) & (-b > 0))               # ray passes through the dilated sphere
    if rover_pose is not None:
        # self-view is NOT maskable by an analytic envelope (the camera is mounted INSIDE any
        # honest body volume -- a sphere/box test masks the whole image). Use static_self_view_mask
        # (cross-pose depth-constancy) instead; rover_pose is accepted for signature stability.
        pass
    return keep


def static_self_view_mask(depth_stack: np.ndarray, *, min_seen: int = 6,
                          max_std_m: float = 0.01, max_depth_m: float = 0.8) -> np.ndarray:
    """Per-camera STATIC self-view mask from cross-pose depth constancy.

    The rover is rigidly mounted, so its own body images at IDENTICAL depth in every pose while
    terrain depth varies. A pixel is self-view iff it is measured in >= ``min_seen`` poses with
    cross-pose std < ``max_std_m`` at depth < ``max_depth_m``. Returns True where the pixel is
    SELF-VIEW (to be excluded). Input: (n_poses, h, w) stereo depth with NaN where invalid.
    Honest by construction: uses only the measured stereo across poses, never the truth.
    """
    seen = np.isfinite(depth_stack).sum(axis=0)
    med = np.nanmedian(depth_stack, axis=0)
    std = np.nanstd(depth_stack, axis=0)
    return (seen >= min_seen) & (std < max_std_m) & (med < max_depth_m)
