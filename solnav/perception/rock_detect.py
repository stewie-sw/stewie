"""Boulder/rock detection on a real rendered lunar image, with an EVAL-only scorer.

Two strictly separated paths (invariant I3 -- truth firewall):

* PERCEPTION (``detect_rocks``): input is ONLY the rendered image. On the lunar surface a
  boulder reads as a sunlit cap (locally bright relative to the surrounding regolith) sitting
  next to a hard cast shadow. The detector segments those bright caps by local-contrast
  thresholding, groups them with connected components, and keeps round, compact blobs. No
  ground truth, camera pose, or clast metadata may enter this path; the signature accepts an
  image and tuning thresholds only.

* EVALUATION (``project_clast_truth`` / ``score_detections`` / ``save_detection_overlay``):
  the crater_boulders clast TRUTH (metadata ``clasts``) and the true camera pose enter here
  and ONLY here. Truth is projected into the image with the dustgym sidecar camera model
  (a pinhole with vertical FOV, matching ``godot_sidecar/sidecar.gd`` ``_setup_camera``: fov
  55 deg, Godot default KEEP_HEIGHT, look-at), restricted to camera-visible boulders, then
  greedily matched to the detections to compute precision/recall. The report is tagged
  ``GROUND_TRUTH_EVAL`` so it is never mistaken for an estimator input.

The camera geometry is validated independently: projecting the two largest in-frame clasts
lands their caps on the sunlit pixels of the real render (``test_rock_detect.py``), and the
count of camera-visible truth boulders is a fixed integer recovered from the real metadata.
Real CV/array operations only; no synthetic data, no stubs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import cv2
import numpy as np

from ..geometry import shadow_metric

# Sidecar single-frame camera (godot_sidecar/sidecar.gd::_setup_camera): vertical FOV, near/far.
# fov is the VERTICAL field of view because the Camera3D uses Godot's default KEEP_HEIGHT.
SIDECAR_FOV_DEG = 55.0
# A6 traverse stereo rig (validation/a6_stereo_traverse.py): camera height, baseline, look-ahead.
CAM_HEIGHT_M = 0.8
STEREO_BASELINE_M = 0.07
LOOKAHEAD_M = 1.0
CAM_PITCH_DROP_M = 0.4  # look-at target sits this far below the eye height


@dataclass(frozen=True)
class RockDetection:
    """One image-plane boulder candidate (perception output; no truth)."""

    u: float
    v: float
    radius_px: float
    score: float
    coordinate_frame: str = "IMAGE_X_RIGHT_Y_DOWN"
    provenance: str = "RUNTIME_DERIVED"


@dataclass(frozen=True)
class CameraPose:
    """True camera pose for the projection path (EVAL only)."""

    eye_m: np.ndarray
    target_m: np.ndarray
    fov_deg: float
    camera: str
    provenance: str = "GROUND_TRUTH_EVAL"


@dataclass(frozen=True)
class ProjectedClast:
    """A clast truth center projected to image pixels (EVAL only)."""

    clast_id: int
    u: float
    v: float
    radius_px: float
    radius_m: float
    distance_m: float
    provenance: str = "GROUND_TRUTH_EVAL"


@dataclass(frozen=True)
class DetectionReport:
    """Precision/recall of detections vs projected truth (EVAL only)."""

    true_positives: int
    false_positives: int
    false_negatives: int
    n_detections: int
    n_truth_scorable: int
    precision: float
    recall: float
    match_radius_px: float
    matched_pairs: tuple[tuple[int, int], ...]  # (detection_index, clast_id)
    provenance: str = "GROUND_TRUTH_EVAL"


def _to_gray(image: np.ndarray) -> np.ndarray:
    g = np.asarray(image)
    if g.ndim == 3:
        g = cv2.cvtColor(g[..., :3].astype(np.uint8), cv2.COLOR_RGB2GRAY)
    return g.astype(np.float32)


# --------------------------------------------------------------------------- perception

def detect_rocks(
    image: np.ndarray,
    *,
    min_area_px: int = 9,
    local_window: int = 31,
    contrast_offset: float = 12.0,
    min_circularity: float = 0.35,
    max_axis_ratio: float = 4.0,
) -> list[RockDetection]:
    """Detect boulders as sunlit caps in a rendered lunar image (appearance only, no truth).

    A boulder cap is locally brighter than the regolith around it. We threshold each pixel
    against an adaptive local mean (a large-kernel box blur) plus ``contrast_offset``, which
    isolates the bright caps and rejects the slowly-varying global illumination gradient and
    the large flat lit ridge. Connected components are then filtered to round, compact blobs
    (circularity and major/minor axis ratio) so elongated streaks and lit slopes are dropped.
    Each surviving blob yields a centre, an equivalent-area radius, and a brightness-contrast
    score. A flat or contrast-free frame yields no detections (no fabricated boulders).
    """
    gray = _to_gray(image)
    h, w = gray.shape
    if h < 3 or w < 3:
        return []
    win = int(local_window) | 1  # odd kernel
    local_mean = cv2.boxFilter(gray, ddepth=cv2.CV_32F, ksize=(win, win))
    bright = ((gray - local_mean) > float(contrast_offset)).astype(np.uint8)
    if bright.sum() == 0:
        return []
    opened = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(opened, connectivity=8)
    contrast_ref = float(np.percentile(gray, 99.0)) - float(np.percentile(gray, 50.0)) + 1e-6
    dets: list[RockDetection] = []
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area < int(min_area_px):
            continue
        ys, xs = np.where(labels == k)
        pts = np.stack([xs, ys], axis=1).astype(np.float64)
        c = pts.mean(axis=0)
        cov = (pts - c).T @ (pts - c) / max(len(pts), 1)
        eig = np.linalg.eigvalsh(cov)
        eig = np.clip(eig, 1e-9, None)
        axis_ratio = float(np.sqrt(eig.max() / eig.min()))
        bw = int(stats[k, cv2.CC_STAT_WIDTH]); bh = int(stats[k, cv2.CC_STAT_HEIGHT])
        circularity = area / (np.pi * (0.5 * max(bw, bh)) ** 2 + 1e-9)
        if axis_ratio > float(max_axis_ratio) or circularity < float(min_circularity):
            continue
        radius_px = float(np.sqrt(area / np.pi))
        cap = gray[ys, xs].mean() - local_mean[ys, xs].mean()
        score = float(np.clip(cap / contrast_ref, 0.0, 1.0))
        dets.append(RockDetection(u=float(centroids[k, 0]), v=float(centroids[k, 1]),
                                  radius_px=radius_px, score=score))
    dets.sort(key=lambda d: -d.score)
    return dets


# ------------------------------------------------------------------ truth projection (EVAL)

def load_frame_pose(sequence_path: str, truth_path: str, frame: int, camera: str) -> CameraPose:
    """Build the true camera pose for one traverse frame (EVAL only).

    Reads the true (x, z) ground pose from the GROUND_TRUTH_EVAL truth file and the stereo
    rig geometry, reproducing the eye/target the A6 traverse renderer used. This is EVAL-side:
    it loads ground truth and must never be called from a perception/estimator path.
    """
    seq = json.loads(open(sequence_path).read())
    poses = json.loads(open(truth_path).read())["poses"]
    pose = next((p for p in poses if int(p["seq"]) == int(frame)), None)
    if pose is None:
        raise ValueError(f"no truth pose for frame {frame}")
    cams = seq["frames"][int(frame)]["cameras"]
    if camera not in cams:
        raise ValueError(f"camera {camera!r} absent from frame {frame}")
    lateral = +STEREO_BASELINE_M / 2.0 if camera == "front_left" else -STEREO_BASELINE_M / 2.0
    gx = float(pose["x"]); gz = float(pose["z"])
    eye = np.array([gx, CAM_HEIGHT_M, gz + lateral], dtype=float)
    target = np.array([gx + LOOKAHEAD_M, CAM_HEIGHT_M - CAM_PITCH_DROP_M, gz + lateral], dtype=float)
    return CameraPose(eye_m=eye, target_m=target, fov_deg=SIDECAR_FOV_DEG, camera=camera)


def project_clast_truth(clasts: list[dict], pose: CameraPose, width: int, height: int
                        ) -> list[ProjectedClast]:
    """Project clast TRUTH centres (exposed cap tops) into image pixels (EVAL only).

    Each clast is a partially buried sphere; the visible cap top is at
    ``center_y + radius * (1 - buried_frac)``. Clasts behind the camera or outside the frame
    are dropped. The pixel radius follows the pinhole magnification
    ``r_px = radius_m / distance * (height/2) / tan(fov_v/2)`` (vertical-FOV camera).
    """
    basis = shadow_metric.look_at_basis(pose.eye_m, pose.target_m)
    tan_v = np.tan(np.radians(pose.fov_deg) / 2.0)
    out: list[ProjectedClast] = []
    for c in clasts:
        center = np.asarray(c["center_m"], dtype=float)
        cap = center.copy()
        cap[1] = center[1] + float(c["radius_m"]) * (1.0 - float(c["buried_frac"]))
        try:
            uv = shadow_metric.project(cap, pose.eye_m, basis, width, height, pose.fov_deg)
        except ValueError:
            continue  # behind the camera
        u, v = float(uv[0]), float(uv[1])
        if not (0.0 <= u < width and 0.0 <= v < height):
            continue
        distance = float(np.linalg.norm(cap - pose.eye_m))
        radius_px = float(c["radius_m"]) / distance * (height / 2.0) / tan_v
        out.append(ProjectedClast(clast_id=int(c["id"]), u=u, v=v, radius_px=radius_px,
                                  radius_m=float(c["radius_m"]), distance_m=distance))
    return out


# ------------------------------------------------------------------------ scoring (EVAL)

def score_detections(detections: list[RockDetection], projected: list[ProjectedClast], *,
                     min_radius_px: float = 4.0, match_scale: float = 2.0) -> DetectionReport:
    """Greedy precision/recall of detections vs visible projected truth (EVAL only).

    Only truth boulders with ``radius_px >= min_radius_px`` are scorable (smaller ones are
    sub-resolution / on the horizon and not reliably distinguishable). Each scorable truth is
    matched to its nearest unused detection within ``match_scale * truth_radius_px``; matched
    detections are true positives, unmatched scorable truth are false negatives, and any
    leftover detections that fall within the visible-truth field but match nothing are false
    positives. Detections outside the visible-truth band (e.g. on the crater rim's far slope,
    where the metadata places no boulders for this view) are not penalised, because absence of
    projected truth there is a visibility limitation, not a confirmed empty region.
    """
    scorable = sorted((p for p in projected if p.radius_px >= float(min_radius_px)),
                      key=lambda p: -p.radius_px)
    if not scorable:
        raise ValueError("no scorable truth boulders (empty projection or radius gate too high)")
    dets = list(detections)
    used = [False] * len(dets)
    matched_pairs: list[tuple[int, int]] = []
    tp = 0
    for p in scorable:
        tol = float(match_scale) * p.radius_px
        best_j, best_d = -1, tol
        for j, d in enumerate(dets):
            if used[j]:
                continue
            dist = float(np.hypot(d.u - p.u, d.v - p.v))
            if dist <= best_d:
                best_d, best_j = dist, j
        if best_j >= 0:
            used[best_j] = True
            matched_pairs.append((best_j, p.clast_id))
            tp += 1
    fn = len(scorable) - tp
    # false positives: unmatched detections that lie inside the visible-truth field bounding box
    if scorable:
        us = [p.u for p in scorable]; vs = [p.v for p in scorable]
        u0, u1 = min(us) - 30.0, max(us) + 30.0
        v0, v1 = min(vs) - 30.0, max(vs) + 30.0
    fp = 0
    for j, d in enumerate(dets):
        if used[j]:
            continue
        if u0 <= d.u <= u1 and v0 <= d.v <= v1:
            fp += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / len(scorable)
    return DetectionReport(
        true_positives=tp, false_positives=fp, false_negatives=fn,
        n_detections=len(dets), n_truth_scorable=len(scorable),
        precision=precision, recall=recall,
        match_radius_px=float(match_scale), matched_pairs=tuple(matched_pairs),
    )


# -------------------------------------------------------------------------------- visual

def save_detection_overlay(image: np.ndarray, detections: list[RockDetection],
                           projected: list[ProjectedClast], report: DetectionReport,
                           out_path: str, *, min_radius_px: float = 4.0) -> str:
    """Render and save a detections-overlay PNG (truth = green, detections = cyan)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    img = np.asarray(image)
    disp = img[..., :3] if img.ndim == 3 else img
    fig, ax = plt.subplots(figsize=(8.0, 6.0))
    ax.imshow(disp, cmap=None if img.ndim == 3 else "gray")
    matched_clast_ids = {cid for _, cid in report.matched_pairs}
    for p in projected:
        if p.radius_px < float(min_radius_px):
            continue
        hit = p.clast_id in matched_clast_ids
        ax.add_patch(Circle((p.u, p.v), max(p.radius_px, 4.0), fill=False,
                            ec="lime" if hit else "yellow", lw=1.4,
                            ls="-" if hit else "--"))
    for d in detections:
        ax.add_patch(Circle((d.u, d.v), max(d.radius_px, 3.0), fill=False, ec="cyan", lw=1.0))
    ax.set_title(
        f"rock_detect: P={report.precision:.2f} R={report.recall:.2f} "
        f"(TP={report.true_positives} FP={report.false_positives} FN={report.false_negatives}, "
        f"truth green/yellow, det cyan)")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path
