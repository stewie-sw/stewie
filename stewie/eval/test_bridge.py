import json
import os

import pytest

from stewie.bridge import dustgym_io

# Committed real Dustgym 1024x768 capture (no synthetic data).
REAL_SENSORS = os.path.join(os.path.dirname(__file__), "fixtures", "frame", "runtime_sensors.json")
REAL_TRUTH = os.path.join(os.path.dirname(__file__), "fixtures", "frame", "evaluation_truth.json")
_has = os.path.exists(REAL_SENSORS)


@pytest.mark.skipif(not _has, reason="dustgym sensors.json fixture not present")
def test_read_real_sensors_frame():
    f = dustgym_io.read_sensors(REAL_SENSORS)
    assert len(f.cameras) == 8
    names = {c.name for c in f.cameras}
    assert {"front_left", "front_right", "rear_left", "rear_right"} <= names
    # real stereo baseline ~7 cm and real fx from the twin render
    assert abs(f.stereo_baseline_m - 0.07) < 1e-2
    fl = f.camera("front_left")
    assert 600 < fl.fx < 750 and fl.image.endswith(".png")
    # the Sun block carries the low-sun regime
    assert f.sun_elevation_deg is not None and f.sun_azimuth_deg is not None
    assert f.profile_id == "DUSTGYM_IPEX_V1"
    assert len(f.profile_sha256) == 64 and f.calibration_id
    assert f.timestamp_s == 0.0 and f.provenance == "RUNTIME_SENSOR"


@pytest.mark.skipif(not _has, reason="dustgym sensors.json fixture not present")
def test_truth_firewall_sensorframe_carries_no_truth():
    """I3 leakage gate (HIGH-08): the estimator-facing SensorFrame must NOT expose rover/lander
    truth; that lives only on the eval-channel EvaluationTruthPacket with GROUND_TRUTH_EVAL
    provenance."""
    f = dustgym_io.read_sensors(REAL_SENSORS)
    for forbidden in ("rover_pos_m", "rover_quat_xyzw", "lander_pos_m"):
        assert not hasattr(f, forbidden), f"SensorFrame leaks truth field {forbidden}"
    assert not {"rover", "lander", "camera_poses_in_world"}.intersection(f.raw)
    assert all("pose_in_world" not in camera for camera in f.raw["cameras"])
    truth = dustgym_io.read_evaluation_truth(REAL_TRUTH)
    assert truth.provenance == "GROUND_TRUTH_EVAL"
    assert truth.rover_pos_m.shape == (3,) and truth.lander_pos_m.shape == (3,)


@pytest.mark.skipif(not _has, reason="dustgym sensors.json fixture not present")
def test_load_real_camera_image():
    img = dustgym_io.load_camera_image(REAL_SENSORS, "front_left")
    assert img.ndim in (2, 3) and img.shape[0] > 0


def test_legacy_combined_packet_is_rejected():
    legacy = os.path.join(os.path.dirname(REAL_SENSORS), "sensors.json")
    with pytest.raises(dustgym_io.PacketValidationError, match="runtime_sensors.json"):
        dustgym_io.read_sensors(legacy)


def test_runtime_truth_injection_is_rejected(tmp_path):
    data = json.load(open(REAL_SENSORS))
    data["rover"] = {"position_m": [0, 0, 0]}
    path = tmp_path / "runtime_sensors.json"
    path.write_text(json.dumps(data))
    with pytest.raises(dustgym_io.PacketValidationError, match="evaluation-only"):
        dustgym_io.read_sensors(str(path), validate_images=False)


def test_bad_profile_checksum_is_rejected_by_profile_validator():
    from stewie.specs.profiles import MixedProfileError, load_profile, validate_sensor_frame

    frame = dustgym_io.read_sensors(REAL_SENSORS)
    frame.raw["profile_sha256"] = "0" * 64
    object.__setattr__(frame, "profile_sha256", "0" * 64)
    with pytest.raises(MixedProfileError, match="checksum"):
        validate_sensor_frame(load_profile("dustgym"), frame)


def test_write_cmd_vel_roundtrip(tmp_path):
    p = dustgym_io.write_cmd_vel(str(tmp_path), 0.2, -0.1, 7)
    d = json.load(open(p))
    assert d["v_ms"] == 0.2 and d["omega_rads"] == -0.1 and d["frame_index"] == 7


def test_write_posture_command_roundtrip(tmp_path):
    p = dustgym_io.write_posture_command(str(tmp_path), 1.2, 0.0, posture="MEERKAT",
                                         drum_front=0.5)
    d = json.load(open(p))
    assert d["arm_front_rad"] == 1.2 and d["posture"] == "MEERKAT" and d["drum_front"] == 0.5
