"""Unified feature front end for the VO/landmark backbone: CLASSICAL (cv2 ORB, cv2 SIFT) and
LEARNED (kornia DISK + LightGlue) keypoint extraction and matching, with a per-method benchmark
on a rendered lunar stereo pair.

Each method returns a frozen :class:`MatchResult`: keypoint counts, raw-match count, the
RANSAC-fundamental inlier ratio, runtime, and the median Sampson (epipolar) distance of the
accepted inliers. The Sampson distance is the standard first-order geometric reprojection error
for the epipolar constraint x'^T F x = 0; on a well-matched stereo pair it is sub-pixel-to-few-pixel
for the inliers, so it is a genuine recovered numeric quantity, not a pass-through of the matcher.

Truth firewall (invariant I3): the perception entry points (:func:`benchmark_method`,
:func:`benchmark_all`) accept rendered images only -- no pose, slip, clast, or other ground-truth
field is ever an argument. The clast count is exposed strictly as an EVAL-path helper
(:func:`count_clasts_in_truth`) for scoring scene difficulty and never feeds the matcher.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/perception/features.py, 2026-06-09 (M2)
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass(frozen=True)
class MatchResult:
    """Benchmark of one feature method on one stereo pair. ``runtime_s`` covers detect + match +
    RANSAC. ``points_left``/``points_right`` are the RANSAC inlier correspondences in pixel
    coordinates of the left/right image; ``fundamental`` is the estimated 3x3 F (None if RANSAC
    could not fit one)."""

    method: str
    n_keypoints_left: int
    n_keypoints_right: int
    n_raw_matches: int
    n_inliers: int
    inlier_ratio: float
    median_sampson_px: float
    runtime_s: float
    fundamental: np.ndarray | None = None
    points_left: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    points_right: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))


def to_gray_u8(img: np.ndarray) -> np.ndarray:
    """RGB(A)/gray array -> single-channel uint8 (the form every detector here expects)."""
    a = np.asarray(img)
    if a.ndim == 3:
        a = cv2.cvtColor(a[..., :3], cv2.COLOR_RGB2GRAY)
    if a.dtype != np.uint8:
        a = np.clip(a, 0, 255).astype(np.uint8)
    return a


def sampson_distances(pts1: np.ndarray, pts2: np.ndarray, F: np.ndarray) -> np.ndarray:
    """First-order (Sampson) distance to the epipolar variety for correspondences (x, x') under F.

    For each pair the residual is r = x'^T F x and the Sampson distance is
        |r| / sqrt( (Fx)_0^2 + (Fx)_1^2 + (F^T x')_0^2 + (F^T x')_1^2 ),
    i.e. the geometric epipolar error in pixels. Returns an (N,) array.
    """
    p1 = np.asarray(pts1, dtype=float).reshape(-1, 2)
    p2 = np.asarray(pts2, dtype=float).reshape(-1, 2)
    if p1.shape != p2.shape:
        raise ValueError("pts1 and pts2 must have the same (N, 2) shape")
    Fm = np.asarray(F, dtype=float).reshape(3, 3)
    ones = np.ones((p1.shape[0], 1))
    x1 = np.hstack([p1, ones])           # (N, 3)
    x2 = np.hstack([p2, ones])           # (N, 3)
    Fx1 = x1 @ Fm.T                      # (N, 3) == (F x)^T per row
    Ftx2 = x2 @ Fm                       # (N, 3) == (F^T x')^T per row
    r = np.einsum("ij,ij->i", x2, Fx1)  # x'^T F x
    denom = Fx1[:, 0] ** 2 + Fx1[:, 1] ** 2 + Ftx2[:, 0] ** 2 + Ftx2[:, 1] ** 2
    denom = np.where(denom <= 0.0, np.nan, denom)
    return np.abs(r) / np.sqrt(denom)


def _ransac_fundamental(
    pts1: np.ndarray, pts2: np.ndarray, ransac_thresh_px: float, confidence: float
):
    """cv2 fundamental-matrix RANSAC. Returns (F, inlier_bool_mask). F is None / mask all-False
    when fewer than 8 correspondences or no consensus set is found."""
    if len(pts1) < 8:
        return None, np.zeros(len(pts1), dtype=bool)
    F, mask = cv2.findFundamentalMat(
        pts1.astype(np.float32), pts2.astype(np.float32),
        method=cv2.FM_RANSAC, ransacReprojThreshold=ransac_thresh_px,
        confidence=confidence,
    )
    if F is None or mask is None or F.shape != (3, 3):
        return None, np.zeros(len(pts1), dtype=bool)
    return F, mask.ravel().astype(bool)


def _finish(method, kp1_n, kp2_n, pts1, pts2, ransac_thresh_px, confidence, t0):
    """Run RANSAC on raw correspondences (pts1, pts2) and pack a MatchResult (shared tail of every
    method so classical and learned report identically)."""
    n_raw = len(pts1)
    F, mask = _ransac_fundamental(pts1, pts2, ransac_thresh_px, confidence)
    inl1, inl2 = pts1[mask], pts2[mask]
    n_inl = int(mask.sum())
    ratio = float(n_inl) / float(n_raw) if n_raw else 0.0
    if F is not None and n_inl > 0:
        med = float(np.nanmedian(sampson_distances(inl1, inl2, F)))
    else:
        med = float("nan")
    return MatchResult(
        method=method, n_keypoints_left=int(kp1_n), n_keypoints_right=int(kp2_n),
        n_raw_matches=int(n_raw), n_inliers=n_inl, inlier_ratio=ratio,
        median_sampson_px=med, runtime_s=time.perf_counter() - t0,
        fundamental=F, points_left=inl1, points_right=inl2,
    )


# ---- CLASSICAL: cv2 ORB / SIFT, mutual-NN matching ----
def _classical(method, left, right, n_features, ransac_thresh_px, confidence):
    g1, g2 = to_gray_u8(left), to_gray_u8(right)
    t0 = time.perf_counter()
    if method == "orb":
        det = cv2.ORB_create(nfeatures=n_features)            # type: ignore[attr-defined]
        norm = cv2.NORM_HAMMING
    else:  # sift
        det = cv2.SIFT_create(nfeatures=n_features)           # type: ignore[attr-defined]
        norm = cv2.NORM_L2
    kp1, des1 = det.detectAndCompute(g1, None)
    kp2, des2 = det.detectAndCompute(g2, None)
    if des1 is None or des2 is None or len(kp1) == 0 or len(kp2) == 0:
        return MatchResult(method, len(kp1), len(kp2), 0, 0, 0.0, float("nan"),
                           time.perf_counter() - t0)
    bf = cv2.BFMatcher(norm, crossCheck=True)                 # mutual nearest neighbour
    matches = bf.match(des1, des2)
    pts1 = np.array([kp1[m.queryIdx].pt for m in matches], dtype=float).reshape(-1, 2)
    pts2 = np.array([kp2[m.trainIdx].pt for m in matches], dtype=float).reshape(-1, 2)
    return _finish(method, len(kp1), len(kp2), pts1, pts2, ransac_thresh_px, confidence, t0)


# ---- LEARNED: kornia DISK + LightGlue ----
_DISK = None
_LG = None


def _load_learned():
    """Lazy-load DISK + LightGlue once (pretrained weights download on first use)."""
    global _DISK, _LG
    if _DISK is None or _LG is None:
        import torch
        from kornia.feature import DISK, LightGlueMatcher
        dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _DISK = DISK.from_pretrained("depth").to(dev).eval()
        _LG = LightGlueMatcher("disk").to(dev).eval()
    return _DISK, _LG


def _disk_lightglue(left, right, n_features, ransac_thresh_px, confidence):
    import torch
    from kornia.feature import laf_from_center_scale_ori
    from kornia.utils import image_to_tensor

    disk, lg = _load_learned()
    dev = next(disk.parameters()).device
    t0 = time.perf_counter()

    def _to_t(img):
        g = to_gray_u8(img)
        rgb = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
        t = image_to_tensor(rgb, keepdim=False).float() / 255.0  # (1,3,H,W)
        return t.to(dev)

    t1, t2 = _to_t(left), _to_t(right)
    with torch.inference_mode():
        f1 = disk(t1, n=n_features, pad_if_not_divisible=True)[0]
        f2 = disk(t2, n=n_features, pad_if_not_divisible=True)[0]
        kp1, kp2 = f1.keypoints, f2.keypoints
        if kp1.shape[0] == 0 or kp2.shape[0] == 0:
            return MatchResult("disk_lightglue", kp1.shape[0], kp2.shape[0], 0, 0, 0.0,
                               float("nan"), time.perf_counter() - t0)
        laf1 = laf_from_center_scale_ori(kp1[None])
        laf2 = laf_from_center_scale_ori(kp2[None])
        hw1 = (t1.shape[-2], t1.shape[-1])
        hw2 = (t2.shape[-2], t2.shape[-1])
        _, idxs = lg(f1.descriptors, f2.descriptors, laf1, laf2, hw1=hw1, hw2=hw2)
    idxs_np = idxs.detach().cpu().numpy().reshape(-1, 2)
    kp1_np = kp1.detach().cpu().numpy()
    kp2_np = kp2.detach().cpu().numpy()
    if idxs_np.shape[0] == 0:
        return MatchResult("disk_lightglue", kp1_np.shape[0], kp2_np.shape[0], 0, 0, 0.0,
                           float("nan"), time.perf_counter() - t0)
    pts1 = kp1_np[idxs_np[:, 0]]
    pts2 = kp2_np[idxs_np[:, 1]]
    return _finish("disk_lightglue", kp1_np.shape[0], kp2_np.shape[0],
                   pts1, pts2, ransac_thresh_px, confidence, t0)


_METHODS = ("orb", "sift", "disk_lightglue")


def available_methods() -> tuple[str, ...]:
    """Names accepted by :func:`benchmark_method` (classical: orb, sift; learned: disk_lightglue)."""
    return _METHODS


def benchmark_method(
    image_left: np.ndarray,
    image_right: np.ndarray,
    method: str,
    *,
    n_features: int = 2048,
    ransac_thresh_px: float = 1.5,
    confidence: float = 0.999,
) -> MatchResult:
    """Extract + match + RANSAC-fundamental one method on a stereo pair (rendered images only).

    Inputs are images: no ground-truth field is ever passed in (invariant I3 truth firewall).
    """
    if method not in _METHODS:
        raise ValueError(f"unknown method '{method}'; available: {_METHODS}")
    if method in ("orb", "sift"):
        return _classical(method, image_left, image_right, n_features, ransac_thresh_px, confidence)
    return _disk_lightglue(image_left, image_right, n_features, ransac_thresh_px, confidence)


def benchmark_all(
    image_left: np.ndarray,
    image_right: np.ndarray,
    *,
    n_features: int = 2048,
) -> list[MatchResult]:
    """Run every available method on the same pair and return the list of results."""
    return [
        benchmark_method(image_left, image_right, m, n_features=n_features)
        for m in _METHODS
    ]


def save_match_visualization(
    image_left: np.ndarray,
    image_right: np.ndarray,
    result: MatchResult,
    out_path: str,
    *,
    max_lines: int = 80,
) -> str:
    """Save a side-by-side PNG of the left/right images with RANSAC-inlier correspondences drawn as
    lines. Returns the written path. Uses the Agg backend (no display required)."""
    import matplotlib
    matplotlib.use("Agg")
    import os

    import matplotlib.pyplot as plt

    gl, gr = to_gray_u8(image_left), to_gray_u8(image_right)
    h = max(gl.shape[0], gr.shape[0])
    canvas = np.zeros((h, gl.shape[1] + gr.shape[1]), dtype=np.uint8)
    canvas[: gl.shape[0], : gl.shape[1]] = gl
    canvas[: gr.shape[0], gl.shape[1] :] = gr
    off = gl.shape[1]

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(canvas, cmap="gray", vmin=0, vmax=255)
    p1, p2 = result.points_left, result.points_right
    n = min(len(p1), max_lines)
    if n:
        sel = np.linspace(0, len(p1) - 1, n).astype(int)   # deterministic even subsample of REAL matches for display
        for i in sel:
            x1, y1 = p1[i]
            x2, y2 = p2[i]
            ax.plot([x1, x2 + off], [y1, y2], "-", color="lime", linewidth=0.5, alpha=0.7)
            ax.plot([x1], [y1], ".", color="red", markersize=2)
            ax.plot([x2 + off], [y2], ".", color="yellow", markersize=2)
    ax.set_title(
        f"{result.method}: kp L/R={result.n_keypoints_left}/{result.n_keypoints_right}  "
        f"raw={result.n_raw_matches}  inliers={result.n_inliers} "
        f"(ratio={result.inlier_ratio:.2f})  "
        f"median Sampson={result.median_sampson_px:.2f}px  t={result.runtime_s*1e3:.0f}ms"
    )
    ax.axis("off")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ---- EVAL-ONLY (invariant I3): scene-difficulty truth; NEVER a perception input ----
def count_clasts_in_truth(metadata_json_path: str) -> int:
    """Number of ground-truth clasts (boulders) in a scene's metadata.json. EVAL-PATH ONLY: this
    reads scene ground truth to characterize matching difficulty and must never be wired into the
    feature/match inputs above (truth firewall)."""
    with open(metadata_json_path) as fh:
        meta = json.load(fh)
    return len(meta.get("clasts", []))
