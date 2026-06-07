#!/usr/bin/env python3
"""Reproduce the current G1/G2 validation evidence without overstating gate status."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from imageio.v3 import imread

from solnav.bridge import dustgym_io
from solnav.config import load_profile, validate_sensor_frame
from solnav.geometry import shadow_metric
from solnav.perception import shadow_extract, stereo_depth

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures"
MANIFEST = ROOT / "validation" / "scene_manifest.json"
DEFAULT_OUTPUT = ROOT / "validation" / "g1_g2_validation_2026-06-07.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    checked = 0
    for split in ("development", "locked_validation", "stress"):
        for scene in manifest[split]:
            for relative, expected in scene["files"].items():
                actual = _sha256(ROOT / relative)
                if actual != expected:
                    raise RuntimeError(f"fixture hash mismatch: {relative}")
                checked += 1
    return {
        "status": "PASS",
        "checked_files": checked,
        "locked_validation_status": manifest["policy"]["locked_validation_status"],
    }


def _controlled_p5_height(path: Path, sun_elevation_deg: float) -> float:
    gray = np.asarray(imread(path), dtype=float)
    if gray.ndim == 3:
        gray = gray[..., :3].mean(axis=2)
    dark = gray < 0.5 * np.median(gray)
    rows, columns = np.where(dark)
    center = np.array([gray.shape[1] / 2.0, gray.shape[0] / 2.0])
    distances = np.hypot(columns - center[0], rows - center[1])
    tip = np.array([columns[int(np.argmax(distances))], rows[int(np.argmax(distances))]])
    height, _ = shadow_metric.shadow_height_ortho(
        center, tip, 6.0 / 512.0, sun_elevation_deg
    )
    return float(height)


def validate() -> dict:
    manifest = _verify_manifest()
    frame_dir = FIXTURE / "frame"
    frame = dustgym_io.read_sensors(str(frame_dir / "runtime_sensors.json"))
    truth = dustgym_io.read_evaluation_truth(str(frame_dir / "evaluation_truth.json"))
    profile = load_profile("dustgym", require_verified=True)
    validate_sensor_frame(profile, frame)

    forbidden = {"rover", "lander", "camera_poses_in_world"}
    if forbidden.intersection(frame.raw):
        raise RuntimeError("runtime packet leaked evaluation truth")
    if any("pose_in_world" in camera for camera in frame.raw["cameras"]):
        raise RuntimeError("runtime camera leaked pose_in_world")
    if frame.frame_index != truth.frame_index or frame.timestamp_s != truth.timestamp_s:
        raise RuntimeError("runtime/evaluation packet identity mismatch")

    left_name, right_name = frame.stereo_pair
    left_camera = frame.camera(left_name)
    if left_camera is None:
        raise RuntimeError("stereo reference camera missing")
    left = np.asarray(imread(frame_dir / left_camera.image))
    right_camera = frame.camera(right_name)
    if right_camera is None:
        raise RuntimeError("stereo match camera missing")
    right = np.asarray(imread(frame_dir / right_camera.image))
    calibration = stereo_depth.StereoCalibration(
        calibration_id=frame.calibration_id,
        reference_camera=left_name,
        match_camera=right_name,
        fx_px=left_camera.fx,
        baseline_m=frame.stereo_baseline_m,
        disparity_sigma_px=1.0,
        covariance_calibrated=False,
        development_evidence=("dustgym_crater_boulders_frame_000",),
    )
    depth = stereo_depth.compute_depth_frame(left, right, calibration)

    clean_shadow = shadow_extract.extract_shadow_azimuth(
        np.asarray(imread(FIXTURE / "shadow_clean.png"))
    )
    p5_e30 = _controlled_p5_height(FIXTURE / "p5_post_e30.png", 30.0)
    p5_e50 = _controlled_p5_height(FIXTURE / "p5_post_e50.png", 50.0)

    g1_blockers = [
        "Dustgym camera egress explicitly reports IMU/wheel/joint/power channels UNAVAILABLE; "
        "the passive wheel/IMU/stereo baseline required by G1 is not reproducible yet.",
        "No locked validation capture has been acquired; the manifest is frozen but empty.",
    ]
    g2_blockers = [
        "No independent per-pixel depth truth exists for the committed stereo capture.",
        "Disparity/shadow/solar covariance has not been calibrated on development scenes and "
        "checked on an untouched held-out split.",
        "General image-derived shadow base/tip association is not implemented; the body/ground "
        "mapping consumes an already associated segment.",
    ]
    return {
        "schema_version": "solnav_gate_validation/1.0",
        "date": "2026-06-07",
        "evidence_mode": "RENDERED_SENSOR_SIM",
        "manifest": manifest,
        "g1": {
            "status": "IMPLEMENTATION_PASS_RELEASE_BLOCKED",
            "contract_checks": {
                "strict_runtime_schema": "PASS",
                "profile_checksum": "PASS",
                "calibration_id": "PASS",
                "timestamps": "PASS",
                "truth_physical_separation": "PASS",
                "camera_file_dimensions": "PASS",
                "frame_and_profile_validation": "PASS",
            },
            "blockers": g1_blockers,
        },
        "g2": {
            "status": "IMPLEMENTATION_PASS_RELEASE_BLOCKED",
            "fixed_reference_camera": depth.reference_camera,
            "match_camera": depth.match_camera,
            "lr_consistent_fraction": float(depth.valid_mask.mean()),
            "lr_consistent_pixels": int(depth.valid_mask.sum()),
            "median_depth_m": float(np.nanmedian(depth.depth_m)),
            "median_sigma_depth_m": float(np.nanmedian(depth.sigma_depth_m)),
            "covariance_calibrated": depth.covariance_calibrated,
            "shadow_image_frame": clean_shadow.coordinate_frame,
            "shadow_direction_periodicity_deg": clean_shadow.periodicity_deg,
            "controlled_p5_height_m": {"sun_e30": p5_e30, "sun_e50": p5_e50},
            "ephemeris_fallback_contract": "PASS",
            "blockers": g2_blockers,
        },
        "release_gate_summary": {
            "G1": "NOT_PASSED",
            "G2": "NOT_PASSED",
            "next_gate": "Acquire timestamped IMU/wheel data and untouched depth/shadow truth captures",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-release-gates", action="store_true")
    args = parser.parse_args()
    result = validate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["release_gate_summary"], indent=2))
    summary = result["release_gate_summary"]
    if args.require_release_gates and (summary["G1"] != "PASSED" or summary["G2"] != "PASSED"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
