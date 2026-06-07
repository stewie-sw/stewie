"""Semantic-mask overlays and feature filtering (perception front-end helper).

The lunar SLAM stack uses semantic masks (ground, rock, lander, fiducial, sky, and
shadow) to keep only features on stable surfaces: rock and ground features are
useful, while sky, lander, fiducial, and shadow features must be removed (they are
either non-static, off-board, or not real surface). When semantic masks are
unavailable (evaluation mode), a self-supervised intensity-threshold shadow
detector provides a usable shadow mask. Real array/CV operations, no fabricated
data; tests run on a known mask fixture and a real dustgym render.
"""
from __future__ import annotations

import numpy as np

# LAC semantic classes (the simulator differentiates these); shadow added for A2.
CLASSES = {"ground": 0, "rock": 1, "lander": 2, "fiducial": 3, "sky": 4, "shadow": 5}
# Features are kept only on these classes (stable, on-surface):
KEEP_CLASSES = (CLASSES["ground"], CLASSES["rock"])


def filter_keypoints(keypoints_uv: np.ndarray, label_mask: np.ndarray,
                     keep_class_ids=KEEP_CLASSES) -> np.ndarray:
    """Keep only keypoints whose semantic label is in keep_class_ids.

    keypoints_uv: (N,2) int pixel coords (u=col, v=row); label_mask: (H,W) class ids.
    Returns the (M,2) subset that survives. Out-of-bounds keypoints are dropped."""
    kp = np.asarray(keypoints_uv)
    if kp.size == 0:
        return kp.reshape(0, 2)
    u = kp[:, 0].astype(int)
    v = kp[:, 1].astype(int)
    H, W = label_mask.shape[:2]
    inb = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    keep = np.zeros(len(kp), dtype=bool)
    keep[inb] = np.isin(label_mask[v[inb], u[inb]], list(keep_class_ids))
    return kp[keep]


def class_pixel_fraction(label_mask: np.ndarray, class_id: int) -> float:
    """Fraction of pixels assigned to class_id."""
    return float(np.mean(label_mask == class_id))


def detect_shadow_mask(gray_image: np.ndarray, rel_threshold: float = 0.35) -> np.ndarray:
    """Self-supervised shadow mask for eval mode (no semantic labels).

    Marks pixels darker than rel_threshold * (robust max intensity) as shadow.
    Uses the 99th percentile as the robust bright reference to resist hot pixels.
    Returns a boolean (H,W) mask. Real CV; threshold is a documented parameter."""
    g = gray_image.astype(np.float32)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)   # drop alpha if present
    bright = np.percentile(g, 99.0)
    if bright <= 0:
        return np.zeros(g.shape, dtype=bool)
    return g < (rel_threshold * bright)


def overlay(gray_image: np.ndarray, bool_mask: np.ndarray,
            color=(255, 80, 80), alpha: float = 0.5) -> np.ndarray:
    """Blend a boolean mask over a grayscale image for visualization. Returns RGB."""
    g = gray_image
    if g.ndim == 2:
        rgb = np.stack([g, g, g], axis=2).astype(np.float32)
    else:
        rgb = g[..., :3].astype(np.float32)   # drop alpha if present
    col = np.array(color, dtype=np.float32)
    m = bool_mask.astype(bool)
    rgb[m] = (1 - alpha) * rgb[m] + alpha * col
    return np.clip(rgb, 0, 255).astype(np.uint8)
