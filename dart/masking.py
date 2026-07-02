"""Semantic-mask overlays and feature filtering (perception front-end helper).

The lunar SLAM stack uses semantic masks (ground, rock, lander, fiducial, sky, and
shadow) to keep only features on stable surfaces: rock and ground features are
useful, while sky, lander, fiducial, and shadow features must be removed (they are
either non-static, off-board, or not real surface). When semantic masks are
unavailable (evaluation mode), a self-supervised intensity-threshold shadow
detector provides a usable shadow mask, and ``segment_eval_mode`` produces a full
truth-free per-pixel labelling (sky/rock/shadow/ground closeable from grayscale here;
lander/fiducial declared GATED on a learned model, never fabricated). Real array/CV
operations, no fabricated data; tests run on a known mask fixture and a real stewie render.
"""
# PROVENANCE: STEWIE DART subsystem (A. Storey)
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from dart.rock_detect import ProjectedClast, RockDetection, detect_rocks

# LAC semantic classes (the simulator differentiates these); shadow added for A2.
CLASSES = {"ground": 0, "rock": 1, "lander": 2, "fiducial": 3, "sky": 4, "shadow": 5}
# Features are kept only on these classes (stable, on-surface):
KEEP_CLASSES = (CLASSES["ground"], CLASSES["rock"])
# Lander and fiducial are NOT closeable from grayscale appearance alone in eval mode: a
# lander/off-board-hardware or an AprilTag-marker segmenter that is reliable from grayscale
# needs a learned model on GPU (see segment_eval_mode). They are declared GATED, not faked.
GATED_ON_LEARNED_MODEL = ("lander", "fiducial")


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

    Marks pixels darker than rel_threshold * (robust bright reference) as shadow. The bright reference
    is the mean of the top-0.1% intensity tail: it resists isolated hot pixels AND stays anchored on the
    sunlit pixels even when sunlit coverage is <1% (the grazing-sun polar regime this detector exists
    for) -- the previous 99th-percentile reference sat on a SHADOW pixel there and inverted the mask
    (audit 2026-06-09). Regime limit: below ~0.1% sunlit coverage the reference is dark again.
    Returns a boolean (H,W) mask. Real CV; threshold is a documented parameter."""
    g = gray_image.astype(np.float32)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)   # drop alpha if present
    bright = float(g[g >= np.percentile(g, 99.9)].mean())
    if bright <= 0:
        return np.zeros(g.shape, dtype=bool)
    return g < (rel_threshold * bright)


def detect_sky_mask(gray_image: np.ndarray, dark_rel_threshold: float = 0.15) -> np.ndarray:
    """Self-supervised sky mask for eval mode (no semantic labels).

    On an airless body the sky reads BLACK (no atmosphere to scatter light), so it cannot be
    told from a cast shadow by brightness alone. What separates them is topology: in a rover
    forward camera the sky is up and unbounded, so it is the near-black region CONNECTED TO
    THE TOP IMAGE BORDER. We threshold to near-black (``dark_rel_threshold`` of the robust
    bright reference, the top-0.1% intensity tail as in ``detect_shadow_mask``), label the
    dark connected components, and keep only those touching the top row. Enclosed dark regions
    (crater interiors, foreground cast shadows) are therefore NOT sky. Returns a boolean (H,W)
    mask. Real CV; the threshold is a documented parameter."""
    g = gray_image.astype(np.float32)
    if g.ndim == 3:
        g = g[..., :3].mean(axis=2)   # drop alpha if present
    bright = float(g[g >= np.percentile(g, 99.9)].mean())
    if bright <= 0:
        return np.zeros(g.shape, dtype=bool)
    dark = (g < dark_rel_threshold * bright).astype(np.uint8)
    if not dark[0].any():
        return np.zeros(g.shape, dtype=bool)   # nothing black at the top -> no visible sky
    _, labels = cv2.connectedComponents(dark, connectivity=8)
    top_labels = np.unique(labels[0][dark[0] > 0])   # component ids present in the top row
    return np.isin(labels, top_labels)


@dataclass(frozen=True)
class EvalSegmentation:
    """A truth-free per-pixel semantic labelling of a grayscale frame (perception output).

    ``labels`` maps each class name to a boolean (H,W) mask; the closeable classes
    (sky/rock/shadow/ground) partition the frame and ``gated_classes`` (lander/fiducial) are
    present as declared-empty masks. ``rock_detections`` are the underlying truth-free boulder
    detections (so an EVAL path can score the rock label). No truth of any kind enters here."""

    labels: dict[str, np.ndarray]
    rock_detections: list[RockDetection]
    gated_classes: tuple[str, ...] = GATED_ON_LEARNED_MODEL
    provenance: str = "RUNTIME_DERIVED"


def segment_eval_mode(image: np.ndarray, *, sky_dark_rel_threshold: float = 0.15,
                      shadow_rel_threshold: float = 0.35,
                      rock_kwargs: dict | None = None) -> EvalSegmentation:
    """Eval-mode semantic segmentation of a grayscale render WITHOUT any truth mask (I3).

    Input is the rendered image ONLY. Produces a per-pixel partition into the truth-free
    closeable classes and declares the classes that are NOT closeable from grayscale here:

      * ``sky``    -- airless lunar sky is BLACK; the near-black region flood-filled from the
        TOP image border (``detect_sky_mask``). Enclosed dark regions (crater interiors, cast
        shadows) stay OFF the sky label.
      * ``rock``   -- sunlit boulder caps (``detect_rocks`` blobs rasterised to pixels), minus sky.
      * ``shadow`` -- on-surface dark pixels (``detect_shadow_mask``) that are not sky or rock.
      * ``ground`` -- lit regolith: every remaining on-surface pixel.

    ``lander`` and ``fiducial`` are GATED (``GATED_ON_LEARNED_MODEL``): a reliable segmenter
    for off-board hardware or an AprilTag marker from grayscale appearance needs a learned
    model on GPU, and no AprilTag is present in this render. They are returned as
    declared-empty masks -- never fabricated. The signature accepts an image and tuning knobs
    only (no truth), keeping the perception path truth-free."""
    g = np.asarray(image)
    gray = g[..., :3].astype(np.float32).mean(axis=2) if g.ndim == 3 else g.astype(np.float32)
    sky = detect_sky_mask(g, dark_rel_threshold=sky_dark_rel_threshold)
    detections = detect_rocks(g, **(rock_kwargs or {}))
    rock_u8 = np.zeros(gray.shape, dtype=np.uint8)
    for d in detections:
        cv2.circle(rock_u8, (int(round(d.u)), int(round(d.v))),
                   max(int(round(d.radius_px)), 2), 1, thickness=-1)
    rock = (rock_u8 > 0) & ~sky
    shadow = detect_shadow_mask(g, rel_threshold=shadow_rel_threshold) & ~sky & ~rock
    ground = ~sky & ~shadow & ~rock
    empty = np.zeros(gray.shape, dtype=bool)
    labels = {
        "sky": sky, "rock": rock, "shadow": shadow, "ground": ground,
        "lander": empty.copy(), "fiducial": empty.copy(),   # GATED_ON_LEARNED_MODEL
    }
    return EvalSegmentation(labels=labels, rock_detections=detections)


@dataclass(frozen=True)
class RockSegEval:
    """Recall of the rock LABEL against held-out projected clast truth (EVAL only)."""

    n_truth_visible: int
    n_on_rock_label: int
    recall: float
    tolerance_px: int
    provenance: str = "GROUND_TRUTH_EVAL"


def score_rock_labels(rock_mask: np.ndarray, projected: list[ProjectedClast], *,
                      min_radius_px: float = 4.0, tolerance_px: int = 2) -> RockSegEval:
    """EVAL-ONLY: recall of the rock LABEL against held-out projected clast TRUTH.

    ``projected`` are ``ProjectedClast`` truth centres (GROUND_TRUTH_EVAL). Truth enters ONLY
    here; the segmenter that produced ``rock_mask`` never saw it (invariant I3). Returns the
    fraction of visible (``radius_px >= min_radius_px``) truth caps whose projected centre
    lands within ``tolerance_px`` of a rock-labelled pixel (the projected centre and the
    detected cap centre can differ by a pixel or two). Tagged GROUND_TRUTH_EVAL so the report
    is never mistaken for an estimator input."""
    h, w = rock_mask.shape[:2]
    visible = [p for p in projected if p.radius_px >= float(min_radius_px)]
    if not visible:
        raise ValueError("no visible truth clasts to score against")
    tol = int(tolerance_px)
    hit = 0
    for p in visible:
        u, v = int(round(p.u)), int(round(p.v))
        y0, y1 = max(0, v - tol), min(h, v + tol + 1)
        x0, x1 = max(0, u - tol), min(w, u + tol + 1)
        if y1 > y0 and x1 > x0 and bool(rock_mask[y0:y1, x0:x1].any()):
            hit += 1
    return RockSegEval(n_truth_visible=len(visible), n_on_rock_label=hit,
                       recall=hit / len(visible), tolerance_px=tol)


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
