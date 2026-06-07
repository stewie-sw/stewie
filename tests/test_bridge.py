import json
import os

import pytest

from solnav.bridge import dustgym_io

# Committed REAL subsample of a dustgym/LAC Seam-2 frame (no synthetic data).
REAL_SENSORS = os.path.join(os.path.dirname(__file__), "fixtures", "frame", "sensors.json")
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


@pytest.mark.skipif(not _has, reason="dustgym sensors.json fixture not present")
def test_truth_firewall_sensorframe_carries_no_truth():
    """I3 leakage gate (HIGH-08): the estimator-facing SensorFrame must NOT expose rover/lander
    truth; that lives only on the eval-channel EvaluationTruthPacket with GROUND_TRUTH_EVAL
    provenance."""
    f = dustgym_io.read_sensors(REAL_SENSORS)
    for forbidden in ("rover_pos_m", "rover_quat_xyzw", "lander_pos_m"):
        assert not hasattr(f, forbidden), f"SensorFrame leaks truth field {forbidden}"
    truth = dustgym_io.read_evaluation_truth(REAL_SENSORS)
    assert truth.provenance == "GROUND_TRUTH_EVAL"
    assert truth.rover_pos_m.shape == (3,) and truth.lander_pos_m.shape == (3,)


@pytest.mark.skipif(not _has, reason="dustgym sensors.json fixture not present")
def test_load_real_camera_image():
    img = dustgym_io.load_camera_image(REAL_SENSORS, "front_left")
    assert img.ndim in (2, 3) and img.shape[0] > 0


def test_write_cmd_vel_roundtrip(tmp_path):
    p = dustgym_io.write_cmd_vel(str(tmp_path), 0.2, -0.1, 7)
    d = json.load(open(p))
    assert d["v_ms"] == 0.2 and d["omega_rads"] == -0.1 and d["frame_index"] == 7


def test_write_posture_command_roundtrip(tmp_path):
    p = dustgym_io.write_posture_command(str(tmp_path), 1.2, 0.0, posture="MEERKAT",
                                         drum_front=0.5)
    d = json.load(open(p))
    assert d["arm_front_rad"] == 1.2 and d["posture"] == "MEERKAT" and d["drum_front"] == 0.5
