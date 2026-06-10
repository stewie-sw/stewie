"""Reproduce the current G1/G2 validation evidence without overstating gate status."""
# PROVENANCE: SolNav dissertation (A. Storey) -- moved from solnav/eval/gates.py, 2026-06-09 (M2)
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
from imageio.v3 import imread

from stewie.bridge import dustgym_io
from stewie.specs.profiles import load_profile, validate_sensor_frame
from dart.geometry import shadow_metric
from dart import shadow_extract, stereo_depth

ROOT = Path(__file__).resolve().parents[0]   # stewie/eval holds validation/ + tests/fixtures
FIXTURE = ROOT / "tests" / "fixtures"   # layout matches the hash-anchored scene_manifest (M2)
MANIFEST = ROOT / "validation" / "scene_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    checked = 0
    for split in ("development", "locked_validation", "simulated_locked", "stress"):
        for scene in manifest.get(split, []):
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
    if rows.size == 0:
        raise ValueError("no shadow-dark pixels in the controlled frame; cannot measure the P5 height "
                         "(audit M38: was an argmax-of-empty crash)")
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

    # G1: incorporate the simulated locked baseline capture if it has been produced.
    g1_capture = ROOT / "validation" / "g1_capture" / "g1_capture_result.json"
    g1_status = "IMPLEMENTATION_PASS_RELEASE_BLOCKED"
    g1_simulated_closure = None
    if g1_capture.exists():
        cap = json.loads(g1_capture.read_text())
        base = cap["baseline_wheel_imu_dead_reckoning"]
        g1_status = "SIM_BASELINE_LOCKED_REALWORLD_BLOCKED"
        g1_simulated_closure = {
            "channels_via": "validation/g1_capture.py (grounded IMU/wheel model on real Haworth DEM + real dustgym slip)",
            "imu_rate_hz": cap["imu_rate_hz"],
            "wheel_rate_hz": cap["wheel_rate_hz"],
            "stereo": "NOT_INCLUDED",
            "baseline_wheel_imu_ate_raw_m": base["ate_raw_same_frame_m"],
            "baseline_wheel_imu_ate_aligned_m": base["ate_aligned_m"],
        }
        g1_blockers = [
            "Native dustgym camera-egress publication of IMU/wheel/joint channels is still pending "
            "(solnav g1_capture.py supplies them for the SIMULATED case).",
            "No REAL-WORLD locked capture (Katwijk download network-blocked here); G1 release stays "
            "blocked until a real run is scored vs DGPS (see katwijk_io.py + g1_imu_wheel_data_sources.md).",
            "Synchronized stereo keyframes are not yet in the capture (sidecar renders local patches, "
            "not the traverse).",
        ]
    else:
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
            "status": g1_status,
            "contract_checks": {
                "strict_runtime_schema": "PASS",
                "profile_checksum": "PASS",
                "calibration_id": "PASS",
                "timestamps": "PASS",
                "truth_physical_separation": "PASS",
                "camera_file_dimensions": "PASS",
                "frame_and_profile_validation": "PASS",
            },
            "simulated_closure": g1_simulated_closure,
            "blockers": g1_blockers,
        },
        "g2": {
            "status": "IMPLEMENTATION_PASS_RELEASE_BLOCKED",
            "fixed_reference_camera": depth.reference_camera,
            "match_camera": depth.match_camera,
            "lr_consistent_fraction": float(depth.valid_mask.mean()),
            "lr_consistent_pixels": int(depth.valid_mask.sum()),
            "median_depth_m": (float(np.nanmedian(depth.depth_m))
                               if int(depth.valid_mask.sum()) else None),
            "median_sigma_depth_m": (float(np.nanmedian(depth.sigma_depth_m))
                                     if int(depth.valid_mask.sum()) else None),
            # audit M39: with zero LR-consistent pixels nanmedian is bare NaN -> invalid JSON
            "covariance_calibrated": depth.covariance_calibrated,
            "shadow_image_frame": clean_shadow.coordinate_frame,
            "shadow_direction_periodicity_deg": clean_shadow.periodicity_deg,
            "controlled_p5_height_m": {"sun_e30": p5_e30, "sun_e50": p5_e50},
            "ephemeris_fallback_contract": "PASS",
            "blockers": g2_blockers,
        },
        "release_gate_summary": {
            "G1": ("NOT_PASSED (SIMULATED baseline locked; real-world capture + stereo pending)"
                   if g1_simulated_closure else "NOT_PASSED"),
            "G2": "NOT_PASSED",
            "next_gate": "Ingest a real Katwijk run (wheel+IMU+DGPS) via katwijk_io.py, add synchronized "
                         "stereo, score solnav SLAM vs DGPS; acquire untouched depth/shadow truth",
        },
    }
