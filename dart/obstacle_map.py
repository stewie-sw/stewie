"""Size-gated obstacle detection + avoidance (P1/P2 perception research track).

Composes the pieces into "obstacle avoidance based on size":
  - DETECT rocks            -> rock_detect.detect_rocks  (appearance; NOT a feature matcher)
  - SIZE each metrically    -> stereo depth from SuperPoint/DISK+LightGlue or ORB matches
                               (stereo_vo.triangulate_stereo): metric radius = r_px * Z / fx
  - GATE by size            -> IPEx step-over clearance OBSTACLE_HEIGHT_M = 7.5 cm [SCHULER24];
                               diameter > clearance => obstacle to AVOID; <= clearance => traversable
  - AVOID                   -> emit the obstacles as keep-outs the planner (route_leg) routes around

LightGlue/SuperPoint are MATCHERS (they supply the stereo depth -> metric size, and VO -> map
placement), not object recognizers -- recognition is rock_detect; avoidance is the size gate + keep-out
routing. Online obstacle discovery is OUT of the intern DEM_KNOWN_POSE product and NOT wired into G1.
Clast TRUTH (positions/sizes) enters only the eval/scoring path (I3); detection takes images only.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/perception/obstacle_map.py, 2026-06-09 (M2)
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from dart import rock_detect, stereo_vo

try:                                                    # the size gate is the producer's sourced spec
        from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M as IPEX_CLEARANCE_M
except Exception:                                       # noqa: BLE001 -- dustgym absent
    IPEX_CLEARANCE_M = 0.075                             # [SCHULER24] IPEx clears 7.5 cm obstacles

# OPERATIONAL avoid line = 7 cm (0.5 cm margin under the physical 7.5 cm clearance), matching
# rock_taxonomy.AVOID_THRESHOLD_M -- the raw clearance as the default gate had ZERO margin and
# desynchronized the two avoid decisions (audit L60). NOTE (audit L59): the gate compares the blob
# DIAMETER against a HEIGHT clearance -- CONSERVATIVE for typical half-buried boulders (h ~ 0.6 d,
# so diameter > height): it flags more, never less.
AVOID_GATE_M = 0.07


@dataclass(frozen=True)
class SizedObstacle:
    u: float
    v: float
    radius_px: float
    depth_m: float
    diameter_m: float
    traversable: bool                                   # True => rover drives over it (<= clearance)
    provenance: str = "RUNTIME_DERIVED"


def _depth_at(cloud, u: float, v: float, radius_px: float):
    """(median positive depth [m], stereo-support count) of points within radius_px of (u, v); the
    support count is how many matched 3D points fall ON the blob -- 0 means no 3D evidence it is a real
    protruding object (likely a flat lit-terrain false positive). Falls back to the nearest point's depth
    (support 0) so a size can still be reported, but the support gate can then reject it."""
    if cloud.points_3d.shape[0] == 0:
        return None, 0
    kp = cloud.keypoints_px
    d2 = (kp[:, 0] - u) ** 2 + (kp[:, 1] - v) ** 2
    sel = d2 <= max(radius_px, 4.0) ** 2
    if sel.any():
        z = cloud.points_3d[sel, 2]
        z = z[z > 0]
        return (float(np.median(z)), int(z.size)) if z.size else (None, 0)
    i = int(np.argmin(d2))
    zn = float(cloud.points_3d[i, 2])
    return (zn, 0) if zn > 0 else (None, 0)


def size_obstacles(detections, cloud, fx_px: float, *, clearance_m: float = AVOID_GATE_M,
                   min_stereo_support: int = 0) -> list:
    """Per-detection metric size (diameter = 2 * r_px * Z / fx) + the traversability gate. With
    min_stereo_support > 0, drop detections without that many matched 3D points on them (cuts flat
    lit-terrain false positives that have no stereo protrusion)."""
    out = []
    for d in detections:
        z, support = _depth_at(cloud, d.u, d.v, d.radius_px)
        if z is None or z <= 0 or support < min_stereo_support:
            continue
        diameter = 2.0 * d.radius_px * z / fx_px
        out.append(SizedObstacle(u=d.u, v=d.v, radius_px=d.radius_px, depth_m=z,
                                 diameter_m=diameter, traversable=(diameter <= clearance_m)))
    return out


def classify(image_left: np.ndarray, image_right: np.ndarray, *, hfov_deg: float = 73.99,
             baseline_m: float = 0.07, clearance_m: float = AVOID_GATE_M,
             min_stereo_support: int = 0) -> list:
    """Detect -> stereo-size -> size-gate, on a REAL stereo pair. Returns [SizedObstacle]. Set
    min_stereo_support > 0 to require stereo evidence (cuts flat false positives)."""
    h, w = image_left.shape[:2]
    k = stereo_vo.intrinsics_from_fov(width_px=w, height_px=h, hfov_deg=hfov_deg)
    cfg = stereo_vo.StereoVOConfig(fx_px=k.fx, fy_px=k.fy, cx_px=k.cx, cy_px=k.cy, baseline_m=baseline_m)
    cloud = stereo_vo.triangulate_stereo(image_left, image_right, cfg)
    dets = rock_detect.detect_rocks(image_left)
    return size_obstacles(dets, cloud, k.fx, clearance_m=clearance_m, min_stereo_support=min_stereo_support)


def obstacle_keepouts(obstacles: list, *, hfov_deg: float, width_px: int, height_px: int,
                      margin_m: float = 0.25) -> list:
    """Keep-outs {x, y, r} (camera-relative ground: x lateral, y forward range) for the NON-traversable
    obstacles -> the planner's route_leg bends around them. The caller composes the KNOWN rover pose
    (DEM_KNOWN_POSE mode) to map these into the local/world frame before planning."""
    k = stereo_vo.intrinsics_from_fov(width_px=width_px, height_px=height_px, hfov_deg=hfov_deg)
    kos = []
    for o in obstacles:
        if o.traversable:
            continue
        lateral = (o.u - k.cx) * o.depth_m / k.fx       # +x right of the optical axis
        kos.append({"x": float(lateral), "y": float(o.depth_m), "r": float(o.diameter_m / 2.0 + margin_m)})
    return kos


def discovered_keepouts_world(camera_keepouts: list, rover_pose) -> list:
    """Map camera-relative obstacle keep-outs (x = lateral, y = forward range) into the local/world frame
    using the KNOWN rover pose (rx, ry, yaw_rad). DEM_KNOWN_POSE: the rover knows its pose, so a discovered
    obstacle ahead is placed at its real world position -> the planner's route_leg routes around it. This
    closes the detect -> size -> avoid -> REPLAN loop (the caller feeds these to mission_planner as keepouts)."""
    rx, ry, yaw = float(rover_pose[0]), float(rover_pose[1]), float(rover_pose[2])
    c, s = math.cos(yaw), math.sin(yaw)
    out = []
    for k in camera_keepouts:
        lateral, forward = float(k["x"]), float(k["y"])
        out.append({"x": rx + forward * c + lateral * s,        # forward along heading, lateral to the right
                    "y": ry + forward * s - lateral * c, "r": float(k["r"])})
    return out
