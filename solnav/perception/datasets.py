"""Dataset-agnostic perception interface -- swap real datasets in CLEANLY.

The detector/sizer (obstacle_map, rock_detect, stereo_vo) already take raw image arrays, so the only
per-dataset code is a thin ADAPTER that yields a standard ``PerceptionFrame`` (image[s] + optional prior
DEM + optional pose + optional EVAL labels). Detection and P/R/F1 then run UNCHANGED on whichever set is
loaded -- the SIMULATED Godot renders today, or a REAL set (Katwijk / AI4Mars / lunar) once its bytes are
fetched. Real adapters are NOT faked: each is a real loader that reads its native format and raises a
clear "not fetched" error until the data exists (cf. load_haworth_dem). Labels live ONLY on the
eval-scoring path (I3); the detector is handed images only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from . import obstacle_map, rock_detect


@dataclass(frozen=True)
class Label:
    """One eval-only ground-truth obstacle, in image pixels (u, v, radius_px) -- dataset-agnostic."""
    u: float
    v: float
    radius_px: float
    radius_m: float = 0.0
    provenance: str = "GROUND_TRUTH_EVAL"


@dataclass(frozen=True)
class PerceptionFrame:
    """A standard perception frame any dataset adapter yields. The detector consumes the image(s) only;
    dem/pose/labels are optional context (labels are EVAL-only)."""
    image_left: np.ndarray
    image_right: np.ndarray | None = None     # None for a monocular dataset (no stereo sizing)
    dem: tuple | None = None                  # (Z, cell_m) prior terrain, optional
    dem_origin: tuple = (0.0, 0.0)
    pose: tuple | None = None                 # (x, y, yaw_rad) known rover pose, optional
    labels: list = field(default_factory=list)  # EVAL-only ground-truth obstacles (Label), optional
    hfov_deg: float = 73.99
    baseline_m: float = 0.07
    source: str = "unknown"


def detect(frame: PerceptionFrame, *, min_stereo_support: int = 0):
    """Run the obstacle detector/sizer on a frame's IMAGES only (dataset-agnostic). Stereo frame ->
    sized + gated obstacles; mono frame -> appearance detections (no metric size)."""
    if frame.image_right is not None:
        return obstacle_map.classify(frame.image_left, frame.image_right, hfov_deg=frame.hfov_deg,
                                      baseline_m=frame.baseline_m, min_stereo_support=min_stereo_support)
    return rock_detect.detect_rocks(frame.image_left)


def score(frame: PerceptionFrame, detections) -> dict:
    """Dataset-agnostic P/R/F1 of detections vs the frame's EVAL labels (empty -> metrics None)."""
    if not frame.labels:
        return {"n_detections": len(detections), "precision": None, "recall": None, "f1": None,
                "note": "no labels for this frame -> qualitative detection only"}
    dets = [rock_detect.RockDetection(u=d.u, v=d.v, radius_px=d.radius_px, score=getattr(d, "score", 1.0))
            for d in detections]
    proj = [rock_detect.ProjectedClast(clast_id=i, u=lb.u, v=lb.v, radius_px=lb.radius_px,
                                       radius_m=lb.radius_m, distance_m=0.0) for i, lb in enumerate(frame.labels)]
    rep = rock_detect.score_detections(dets, proj)
    p, r = rep.precision, rep.recall
    f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
    return {"n_detections": len(detections), "precision": p, "recall": r, "f1": f1,
            "true_positives": rep.true_positives, "false_positives": rep.false_positives}


# ---- adapters: one per dataset, all yielding the same PerceptionFrame -----------------------------
def load_sim_frame(traverse_dir: str, frame: int = 0, *, with_labels: bool = False,
                   clast_metadata: str | None = None) -> PerceptionFrame:
    """SIMULATED Godot a6-traverse adapter (the only data present today): the rendered stereo pair, and
    (eval-only) the projected clast-truth labels. NOTE: simulated imagery -- not real lunar perception."""
    import cv2
    cam = os.path.join(traverse_dir, "cam", f"frame_{frame:03d}")
    left = cv2.imread(os.path.join(cam, "front_left.png"))
    right = cv2.imread(os.path.join(cam, "front_right.png"))
    if left is None or right is None:
        raise FileNotFoundError(f"sim stereo frame {frame} not found under {cam} (render the a6 traverse first)")
    labels: list = []
    if with_labels:
        import json
        meta = clast_metadata or "/mnt/projects/foss_ipex/dustgym/samples/crater_boulders/metadata.json"
        clasts = json.load(open(meta))["clasts"]
        pose = rock_detect.load_frame_pose(os.path.join(traverse_dir, "sequence.json"),
                                           os.path.join(traverse_dir, "truth", "truth.json"), frame, "front_left")
        proj = rock_detect.project_clast_truth(clasts, pose, left.shape[1], left.shape[0])
        labels = [Label(u=p.u, v=p.v, radius_px=p.radius_px, radius_m=p.radius_m) for p in proj]
    return PerceptionFrame(image_left=left, image_right=right, labels=labels, source="sim:a6_traverse")


def _mask_to_labels(mask, *, min_area_px: int = 150) -> list:
    """Connected components of a boolean obstacle mask -> Label(u, v, radius_px) centroids (eval truth)."""
    import cv2
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(mask.astype("uint8"), connectivity=8)
    out = []
    for k in range(1, n):
        area = int(stats[k, cv2.CC_STAT_AREA])
        if area >= min_area_px:
            out.append(Label(u=float(cent[k, 0]), v=float(cent[k, 1]),
                             radius_px=float((area / 3.141592653589793) ** 0.5)))
    return out


def load_ai4mars_frame(root: str, base: str, *, split: str = "train", subsystem: str = "msl/ncam",
                       min_label_area_px: int = 150) -> PerceptionFrame:
    """REAL AI4Mars adapter (Zenodo 15995036): an MSL Navcam EDR image + its crowd-sourced semantic label.
    The 'big rock' NAV class (3) becomes the eval obstacle labels (connected components -> Label). AI4Mars
    is MONOCULAR (no stereo pair) -> image_right=None -> appearance detection only; the stereo size-gate +
    DEM cross-analysis ride a stereo set (MER/MSL PDS). Real Mars imagery; labels are EVAL-only (I3)."""
    import cv2
    img = cv2.imread(os.path.join(root, subsystem, "images", "edr", base + ".JPG"))
    lbl = cv2.imread(os.path.join(root, subsystem, "labels", split, base + ".png"), cv2.IMREAD_UNCHANGED)
    if img is None or lbl is None:
        raise FileNotFoundError(f"AI4Mars frame {base!r} not found under {root}/{subsystem} (split={split})")
    labels = _mask_to_labels(lbl == 3, min_area_px=min_label_area_px)        # NAV class 3 = big rock
    return PerceptionFrame(image_left=img, image_right=None, labels=labels,
                           source=f"ai4mars:{subsystem}/{base}")


# To add ANOTHER real dataset, write one `load_<name>_frame(...) -> PerceptionFrame` (cf. load_ai4mars_frame
# above) -- e.g. Katwijk (real rover stereo + rocks + DEM; ESA, network-blocked here). detect + score then
# run UNCHANGED. Add the loader only once its bytes are fetched + the parser is tested on the real files.
