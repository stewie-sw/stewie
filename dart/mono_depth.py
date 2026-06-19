"""Monocular-depth producer + score-vs-reference benchmark (PRD #185, the §10 perception track).

A single-camera depth cue (DepthAnything-V2) to complement the rig's passive STEREO depth
(dart.stereo_depth): where stereo has no overlap or texture, a learned monocular prior still gives a
dense relative-depth field. Monocular depth is SCALE-AMBIGUOUS, so it is never a metric source on its
own -- it is aligned (least-squares scale+shift) to a metric reference, then scored. Two references:
`benchmark_traverse` aligns to the rig's stereo depth on the same real frame (the rover's actual
measurement, NOT ground truth); `benchmark_vs_truth` aligns to the per-pixel ray-cast terrain GROUND
TRUTH at the known camera pose (stewie.eval.depth_truth) -- the stronger reference, with a guard that
refuses degenerate poses (camera at/under the surface -> ~0 truth depth).

torch/transformers are imported lazily inside the functions so importing `dart` (and the test suite)
stays fast and dependency-light.
"""
from __future__ import annotations

import numpy as np

_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
_PIPE = None


def _pipe(model_id: str = _MODEL_ID):
    """Lazy, cached depth-estimation pipeline (GPU if available, else CPU)."""
    global _PIPE
    if _PIPE is None:
        import torch
        from transformers import pipeline
        dev = 0 if torch.cuda.is_available() else -1
        _PIPE = pipeline("depth-estimation", model=model_id, device=dev)
    return _PIPE


def predict_relative_depth(image_rgb: np.ndarray, model_id: str = _MODEL_ID) -> np.ndarray:
    """Run the monocular model on an HxWx3 RGB image; return the RAW predicted field at the image
    resolution (float32). DepthAnything emits a relative INVERSE-depth (disparity-like: nearer = larger);
    callers align it to metric via `align_to_metric`. Not metric on its own."""
    from PIL import Image
    img = Image.fromarray(np.asarray(image_rgb, dtype=np.uint8)[..., :3])
    out = _pipe(model_id)(img)
    pred = out.get("predicted_depth")
    if pred is not None:                                   # raw tensor at model resolution -> resize to input
        arr = pred.detach().to("cpu").numpy().astype(np.float32)
        arr = np.squeeze(arr)
        if arr.shape != (img.height, img.width):
            arr = np.asarray(Image.fromarray(arr).resize((img.width, img.height), Image.Resampling.BILINEAR),
                             dtype=np.float32)
        return arr
    return np.asarray(out["depth"], dtype=np.float32)      # fallback: the normalized visualization


def align_to_metric(pred: np.ndarray, ref_depth_m: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Align a relative monocular field to a metric reference (m) by least-squares scale+shift on the
    masked pixels. Auto-detects orientation: if `pred` correlates NEGATIVELY with reference depth it is
    inverse-depth (nearer = larger), so it is inverted to a depth proxy first. Returns metric depth (m)."""
    m = mask & np.isfinite(pred) & np.isfinite(ref_depth_m) & (ref_depth_m > 0)
    if int(m.sum()) < 50:
        raise ValueError("too few co-valid pixels to align monocular depth to the reference")
    p = pred[m].astype(np.float64)
    r = ref_depth_m[m].astype(np.float64)
    # orientation: DepthAnything is inverse-depth, so pred usually anti-correlates with metric depth
    if np.corrcoef(p, r)[0, 1] < 0:
        proxy = 1.0 / np.clip(pred, 1e-6, None)
        pv = proxy[m].astype(np.float64)
    else:
        proxy = pred.astype(np.float64)
        pv = p
    # least-squares scale a + shift b: a*proxy + b ~= ref
    a, b = np.polyfit(pv, r, 1)
    aligned = a * proxy + b
    return aligned.astype(np.float32)


def depth_metrics(pred_m: np.ndarray, ref_m: np.ndarray, mask: np.ndarray) -> dict:
    """Standard monocular-depth error metrics on the masked, positive-depth pixels."""
    m = mask & np.isfinite(pred_m) & np.isfinite(ref_m) & (ref_m > 0) & (pred_m > 0)
    n = int(m.sum())
    if n < 50:
        raise ValueError("too few valid pixels to score depth")
    p = pred_m[m].astype(np.float64)
    r = ref_m[m].astype(np.float64)
    abs_rel = float(np.mean(np.abs(p - r) / r))
    rmse = float(np.sqrt(np.mean((p - r) ** 2)))
    ratio = np.maximum(p / r, r / p)
    delta1 = float(np.mean(ratio < 1.25))
    return {"n_pixels": n, "abs_rel": abs_rel, "rmse_m": rmse, "delta1": delta1}


def benchmark_frame(left_rgb: np.ndarray, right_rgb: np.ndarray, *, fx_px: float,
                    baseline_m: float = 0.05) -> dict:
    """One frame: stereo metric depth (the reference) vs monocular depth (aligned to it). Returns the
    metrics + the co-valid pixel count. Uses the SAME left image for both, so the comparison is fair."""
    from dart import stereo_depth as SD
    calib = SD.StereoCalibration(calibration_id="mono_bench", reference_camera="front_left",
                                 match_camera="front_right", fx_px=float(fx_px),
                                 baseline_m=float(baseline_m), disparity_sigma_px=1.0,
                                 covariance_calibrated=False, development_evidence=("a6_traverse",))
    stereo = SD.compute_depth_frame(left_rgb, right_rgb, calib)
    pred = predict_relative_depth(left_rgb)
    aligned = align_to_metric(pred, stereo.depth_m, stereo.valid_mask)
    m = depth_metrics(aligned, stereo.depth_m, stereo.valid_mask)
    m["stereo_valid_fraction"] = float(stereo.valid_mask.mean())
    return m


def benchmark_traverse(traverse_dir: str, *, fx_px: float, baseline_m: float = 0.05) -> dict:
    """Score monocular depth against the stereo metric reference across every frame of a rendered
    traverse (e.g. stewie/eval/validation/a6_traverse/cam). Real frames only; aggregates AbsRel/RMSE/
    delta1. Report-only -- mono is a scale-aligned cue, the stereo reference is the rig's measurement
    (NOT ground truth; a per-pixel DEM-raycast truth is the stronger, deferred reference)."""
    import glob
    import os

    import imageio.v2 as imageio

    frame_dirs = sorted(d for d in glob.glob(os.path.join(traverse_dir, "frame_*")) if os.path.isdir(d))
    per_frame = {}
    for fd in frame_dirs:
        lp, rp = os.path.join(fd, "front_left.png"), os.path.join(fd, "front_right.png")
        if not (os.path.exists(lp) and os.path.exists(rp)):
            continue
        left = np.asarray(imageio.imread(lp))
        right = np.asarray(imageio.imread(rp))
        per_frame[os.path.basename(fd)] = benchmark_frame(left, right, fx_px=fx_px, baseline_m=baseline_m)
    if not per_frame:
        raise FileNotFoundError(f"no frame_*/front_{{left,right}}.png under {traverse_dir}")
    keys = ("abs_rel", "rmse_m", "delta1")
    agg = {k: float(np.mean([f[k] for f in per_frame.values()])) for k in keys}
    return {
        "model": _MODEL_ID,
        "reference": "stereo_metric_depth (dart.stereo_depth; rig measurement, not ground truth)",
        "baseline_m": baseline_m,
        "frames": per_frame,
        "aggregate": agg,
        "note": ("monocular depth is scale-ambiguous -> least-squares scale+shift aligned to the stereo "
                 "reference per frame, then scored. For GROUND-TRUTH scoring (not just stereo) use "
                 "benchmark_vs_truth, which scores against the ray-cast terrain truth."),
    }


def benchmark_vs_truth(pose_dir: str, scene_dir: str, *, left: str = "front_left", stride: int = 4) -> dict:
    """Score monocular depth against per-pixel GROUND TRUTH (not stereo): the ray-cast terrain depth
    from the known camera pose (stewie.eval.depth_truth.ray_cast_depth), masked by comparison_keep_mask
    so clast/lander/occluded pixels (where the terrain heightfield is NOT the visible surface) are
    excluded. Reuses the exact camera-dict construction the G2 calibration uses (run intrinsics + truth
    pose_in_world). Mono is scale-aligned to the truth, then scored AbsRel/RMSE/delta1.

    This is the stronger reference the stereo benchmark deferred to -- the truth is exact geometry on the
    real DEM at the real pose, not a measurement. Needs a pose dir with sensors.json + evaluation_truth.json
    (e.g. stewie/eval/validation/g2cal/pose_N) and the conserved scene (samples/crater_boulders)."""
    import json
    import os

    import imageio.v2 as imageio

    from stewie.eval import depth_truth as DT
    run = json.load(open(os.path.join(pose_dir, "sensors.json")))
    truth = json.load(open(os.path.join(pose_dir, "evaluation_truth.json")))
    cam_r = {c["name"]: c for c in run["cameras"]}
    cam_t = {c["name"]: c for c in truth["camera_poses_in_world"]}
    if left not in cam_r:
        left = run["cameras"][0]["name"]                                   # fall back to the first camera
    cam = {**cam_r[left], "pose_in_world": cam_t[left]["pose_in_world"]}
    img = np.asarray(imageio.imread(os.path.join(pose_dir, cam_r[left]["image"])))
    T = DT.ray_cast_depth(cam, scene_dir, stride=stride, lander=run.get("lander"))
    keep = DT.comparison_keep_mask(cam, T, scene_dir)                      # clast/lander/occlusion masking
    zt = T["depth_m"]
    # guard: a physically sane truth. A degenerate raycast (camera at/under the surface -> depth ~0)
    # would make scale-alignment + AbsRel meaningless; refuse it instead of reporting a hollow 0.0 RMSE.
    valid_t = zt[keep & np.isfinite(zt)]
    if valid_t.size < 50 or float(np.median(valid_t)) < 0.05:
        raise ValueError(f"degenerate ray-cast truth for {left} (median depth "
                         f"{float(np.median(valid_t)) if valid_t.size else float('nan'):.4f} m); "
                         "camera likely at/under the surface — pose excluded")
    pred = predict_relative_depth(img)
    rr, cc = np.meshgrid(T["rows"], T["cols"], indexing="ij")
    pred_s = pred[rr, cc]                                                   # mono at the truth's strided grid
    aligned = align_to_metric(pred_s, zt, keep)
    m = depth_metrics(aligned, zt, keep)
    m["reference"] = "ray_cast_depth GROUND TRUTH (terrain; clast/lander/occlusion-masked keep)"
    m["truth_valid_px"] = int((np.isfinite(zt) & keep).sum())
    m["camera"] = left
    return m

