"""A6 consumer: parse + validate the canonical single-clock dustgym_runtime packet (P0-3).

Unifies the producer-side channels (camera + IMU + raw four-wheel + measured joints) on ONE clock.
Reuses proprioception_io for the imu/wheel channels, adds camera + joints parsing, and enforces the
truth firewall (I3). The camera frame timestamps must be monotonic and carry no true pose.
"""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/bridge/runtime_io.py, 2026-06-09 (M2)
from __future__ import annotations

import json
import os

import numpy as np

from .proprioception_io import _FORBIDDEN, _JOINT_SAMPLE_KEYS, _allowed, parse_proprioception

_CAMERA_CHAN_KEYS = {"status", "frames", "reference_camera", "baseline_m", "intrinsics",
                     "rate_hz", "units", "provenance", "reason"}
_FRAME_KEYS = {"name", "t", "path"}

# A6/A7 acceptance: the estimator input directory must contain NO truth/ground-truth files (I3).
_TRUTH_FILE_PATTERNS = ("truth", "ground_truth", "_gt", "pose_true", "true_pose", "slip", "terrain_truth")


def assert_input_dir_clean(input_dir: str) -> bool:
    """Reject if any truth/ground-truth file is present in the estimator input directory (I3 directory
    isolation). The estimator must never see truth; this guards the capture/handoff boundary."""
    bad = []
    for root, _dirs, files in os.walk(input_dir):
        for fn in files:
            low = fn.lower()
            if any(p in low for p in _TRUTH_FILE_PATTERNS):
                bad.append(os.path.join(root, fn))
    if bad:
        raise ValueError(f"truth file(s) present in estimator input dir (I3 violation): {bad[:5]}")
    return True


def parse_canonical(packet: dict) -> dict:
    if not str(packet.get("schema_version", "")).startswith("dustgym_runtime/"):
        raise ValueError("not a canonical dustgym_runtime packet")
    blob = json.dumps(packet).lower()
    for k in _FORBIDDEN:
        if k in blob:
            raise ValueError(f"truth key '{k}' present in canonical packet (I3 violation)")
    clock, seq, chans = packet["clock"], packet["sequence_id"], packet["channels"]

    # imu + wheel via the proprioception parser (joints/power handled below so we don't double-parse)
    proprio = {"schema_version": "proprioception/1.1", "clock": clock, "sequence_id": seq,
               "channels": {"imu": chans.get("imu", {"status": "UNAVAILABLE"}),
                            "wheel": chans.get("wheel", {"status": "UNAVAILABLE"}),
                            "joints": {"status": "UNAVAILABLE"}, "power": {"status": "UNAVAILABLE"}}}
    parsed = parse_proprioception(proprio)
    out = {"clock": clock, "sequence_id": seq, "imu": parsed["imu"], "wheel": parsed["wheel"],
           "camera_frames": [], "joints": None, "unavailable": []}

    cam = chans.get("camera", {})
    _allowed(cam, _CAMERA_CHAN_KEYS, "camera channel")
    if cam.get("status") == "OK":
        frames = cam.get("frames") or []
        if not frames:
            raise ValueError("camera status OK but no frames")
        for f in frames:                      # strict frame allow-list: a novel (truth) key cannot ride in
            _allowed(f, _FRAME_KEYS, "camera frame")
            if "t" not in f or "name" not in f:
                raise ValueError("camera frame missing required 't'/'name' (audit L02)")
        # PER-CAMERA strict monotonicity: a stereo pair shares a keyframe timestamp (NOT a duplicate),
        # but a single camera must not repeat or go backwards.
        by_cam: dict = {}
        for f in frames:
            by_cam.setdefault(f.get("name", "?"), []).append(float(f["t"]))
        for name, cts in by_cam.items():
            a = np.asarray(cts, float)
            if a.size > 1 and np.any(np.diff(a) <= 0.0):
                raise ValueError(f"camera '{name}' frame timestamps not strictly monotonic "
                                 f"(duplicate/out-of-order)")
        # keyframe cadence + timing metrics (req 4: jitter, drops, duplicates) on the unique keyframe times
        kf = np.array(sorted({float(f["t"]) for f in frames}))
        d = np.diff(kf)
        med = float(np.median(d)) if d.size else 0.0
        out["camera_timing"] = {
            "n_frames": len(frames), "n_keyframes": int(kf.size), "n_cameras": len(by_cam),
            "interval_mean_s": float(d.mean()) if d.size else 0.0,
            "interval_jitter_s": float(d.std()) if d.size else 0.0,
            "max_gap_s": float(d.max()) if d.size else 0.0,
            "drops": int(np.sum(d > 1.5 * med)) if med > 0 else 0,
            "duplicates": 0,                          # per-camera strict monotonicity rejected any above
        }
        out["camera_frames"] = frames
    else:
        if cam.get("frames"):
            raise ValueError("camera UNAVAILABLE but carries frames")
        out["unavailable"].append("camera")

    j = chans.get("joints", {})
    if j.get("status") == "OK":
        s = j.get("samples") or []
        if not s:
            raise ValueError("joints status OK but no payload")
        for x in s:
            _allowed(x, _JOINT_SAMPLE_KEYS, "joints sample")
        out["joints"] = s[0]                          # arm angles + posture-conditioned per-camera heights
    else:
        out["unavailable"].append("joints")

    if chans.get("power", {}).get("status") != "OK":
        out["unavailable"].append("power")

    # exact association on ONE clock: the camera keyframes must fall within the proprioception time window
    # -- the canonical-clock guarantee that camera + IMU/wheel are the same run, not stitched from separate
    # captures. Deterministic from the packet (no wall-clock) -> reproducible.
    if out["camera_frames"] and (out["imu"] or out["wheel"]):
        prop_t = [s.t for s in out["imu"]] + [s.t for s in out["wheel"]]
        kf_t = [float(f["t"]) for f in out["camera_frames"]]
        lo, hi = min(prop_t), max(prop_t)
        span = max(hi - lo, 1e-9)
        if min(kf_t) < lo - span or max(kf_t) > hi + span:
            raise ValueError("camera keyframes fall outside the proprioception window -- canonical-clock "
                             "association broken (camera + proprioception are not the same run)")
    return out
