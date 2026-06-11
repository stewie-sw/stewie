"""Topographic teach-and-repeat for dock RETURN -- the SECOND docking method.

Redundant with the AprilTag posture-tracked dock (`dock_pose`). On the outbound 'teach' pass the planner
RECORDS a breadcrumb trail of keyframes: the 8-camera stills + the rover pose + a TOPOGRAPHY signature
derived from stereo. To return, REVERSE the sequence -- match the live topography to the recorded
keyframes and steer toward the next-earlier keyframe -- retracing to the dock vicinity, where dock_pose
takes over for the mm-precision final mate.

Why topography, not raw pixels: at the poles the Sun grazes and shadows shift, so a recorded RGB still
won't match later. The stereo-derived local terrain shape (binned point cloud) is illumination-invariant,
so the reverse match still works even though the lighting changed since the teach pass. No truth, no
synthetic data -- the signature comes from the rover's own stereo.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from dart import stereo_vo
from dart import dock_pose


def terrain_signature(image_left, image_right, *, hfov_deg: float = 73.99, baseline_m: float = 0.07,
                      grid=(12, 12), fwd_max_m: float = 8.0, lat_max_m: float = 4.0) -> np.ndarray:
    """Illumination-invariant local-topography descriptor: triangulate the stereo pair and bin the 3-D
    points into a (forward x lateral) grid of mean height -> a small normalized patch that encodes the
    terrain SHAPE the rover sees, independent of lighting. Empty cells -> 0; the patch is zero-mean
    unit-norm so it matches by direction (robust to scale/illumination)."""
    h, w = image_left.shape[:2]
    k = stereo_vo.intrinsics_from_fov(width_px=w, height_px=h, hfov_deg=hfov_deg)
    cfg = stereo_vo.StereoVOConfig(fx_px=k.fx, fy_px=k.fy, cx_px=k.cx, cy_px=k.cy, baseline_m=baseline_m)
    cloud = stereo_vo.triangulate_stereo(image_left, image_right, cfg)
    nf, nl = grid
    sig = np.zeros((nf, nl), dtype=float)
    cnt = np.zeros((nf, nl), dtype=float)
    for x, ydown, z in cloud.points_3d:                       # camera frame: x right, y down, z forward
        if 0 < z <= fwd_max_m and -lat_max_m <= x <= lat_max_m:
            fi = min(nf - 1, int(z / fwd_max_m * nf))
            li = min(nl - 1, int((x + lat_max_m) / (2 * lat_max_m) * nl))
            sig[fi, li] += -ydown                              # -y = height up
            cnt[fi, li] += 1
    sig = np.where(cnt > 0, sig / np.maximum(cnt, 1), 0.0).ravel()
    sig = sig - sig.mean()
    n = np.linalg.norm(sig)
    return sig / n if n > 1e-9 else sig


def _similarity(a, b) -> float:
    """Cosine similarity of two normalized (zero-mean) signatures -> 1 = identical topography view."""
    return float(np.dot(a, b))


@dataclass
class Keyframe:
    index: int
    pose: dock_pose.Pose2
    t_s: float
    stills: dict                      # camera_name -> still path/id (all 8 cameras)
    topo_sig: np.ndarray              # illumination-invariant topography descriptor


@dataclass
class BreadcrumbTrail:
    """The recorded teach pass. index 0 = the DOCK; index grows outbound. Reverse = retrace to the dock."""
    keyframes: list = field(default_factory=list)

    def record(self, pose, stills: dict, topo_sig) -> Keyframe:
        kf = Keyframe(len(self.keyframes), pose, getattr(pose, "t_s", 0.0), dict(stills),
                      np.asarray(topo_sig, dtype=float))
        self.keyframes.append(kf)
        return kf

    def match(self, live_sig):
        """Best-matching recorded keyframe for a live topography signature -> (index, similarity)."""
        if not self.keyframes:
            return None, 0.0
        sims = [_similarity(live_sig, kf.topo_sig) for kf in self.keyframes]
        i = int(np.argmax(sims))
        return i, float(sims[i])

    def reverse_dock_step(self, live_sig, *, dock_index: int = 0, min_similarity: float = 0.2):
        """Reverse-traverse toward the dock: localize on the trail (match), then target the NEXT-EARLIER
        keyframe (one step back toward index 0). Returns (target_keyframe, current_index, similarity).
        A match below ``min_similarity`` (e.g. a degenerate all-zero signature, or off-trail terrain)
        returns (None, None, sim) -- the caller must STOP/search, not steer toward an arbitrary keyframe
        (audit 2026-06-09). The caller steers the rover toward target.pose; when current_index reaches
        dock_index, hand off to the AprilTag posture-tracked dock for the final mate."""
        cur, sim = self.match(live_sig)
        if cur is None or sim < min_similarity:
            return None, None, float(sim)
        target = self.keyframes[max(dock_index, cur - 1)]
        return target, cur, sim

    def at_dock(self, live_sig, *, dock_index: int = 0, min_similarity: float = 0.5) -> bool:
        cur, sim = self.match(live_sig)
        return cur == dock_index and sim >= min_similarity
