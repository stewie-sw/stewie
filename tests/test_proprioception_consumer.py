"""A5 consumer: parse + validate the dustgym runtime proprioception packet (round trip + firewalls)."""
import os
import sys

import pytest

from solnav.bridge import proprioception_io as pio

_DUST = os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym")


def _packet():
    sys.path.insert(0, _DUST)
    from terrain_authority import proprioception as pp
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(5)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.30, 0.0, (0, 0, 0, 0), dt=0.1) for i in range(3)]
    return pp.runtime_proprioception_packet(imu, wheel, sequence_id=7, imu_rate_hz=100, wheel_rate_hz=10)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_round_trip_producer_to_consumer():
    parsed = pio.parse_proprioception(_packet())
    assert parsed["sequence_id"] == 7 and parsed["clock"] == "sim_monotonic"
    assert len(parsed["imu"]) == 5 and len(parsed["wheel"]) == 3
    assert parsed["imu"][0].gyro_var > 0.0                     # I4 covariance survived
    assert set(parsed["unavailable"]) == {"joints", "power"}   # honestly unavailable channels
    w = parsed["wheel"][0]                                     # RAW four-wheel encoder sample (P0-2)
    assert w.encoder_delta_rad.shape == (4,) and w.covariance.shape == (4, 4)
    assert "slip" not in vars(w)                               # no truth on the raw sample (I3)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_consumer_derives_odometry_from_raw_four_wheel():
    from solnav.sensors.imu_wheel import body_odometry_from_encoders
    w = pio.parse_proprioception(_packet())["wheel"][0]
    v, omega = body_odometry_from_encoders(w, 0.5207, 0.1)     # solnav OWNS the derivation
    assert v > 0 and abs(omega) < 0.05                          # straight drive -> forward, ~zero yaw


def test_rejects_non_psd_wheel_covariance():
    pkt = {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE"}, "wheel": {
               "status": "OK", "order": ["LF", "RF", "LR", "RR"], "wheel_radius_m": 0.15,
               "encoder_counts_per_rev": 4096, "samples": [{
                   "t": 0.0, "encoder_delta_rad": [0, 0, 0, 0], "encoder_count_delta": [0, 0, 0, 0],
                   "covariance": [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]}]}}}
    with pytest.raises(ValueError, match="PSD"):
        pio.parse_proprioception(pkt)


def test_rejects_truth_key_I3():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE"}, "lander_pos_m": [1, 2, 3]}}
    with pytest.raises(ValueError, match="truth key"):
        pio.parse_proprioception(pkt)


def test_rejects_ok_without_payload():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "samples": []}, "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="no payload"):
        pio.parse_proprioception(pkt)


def test_rejects_unavailable_with_samples():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE", "samples": [{"t": 0}]},
                        "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="carries samples"):
        pio.parse_proprioception(pkt)


def test_rejects_non_monotonic_timestamps():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "samples": [
               {"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0]},
               {"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0]}]},
               "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="monotonic"):
        pio.parse_proprioception(pkt)


def test_rejects_non_finite_imu():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "samples": [
               {"t": 0.0, "gyro_z": float("nan"), "accel_xy": [0, 0]}]},
               "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="non-finite"):
        pio.parse_proprioception(pkt)


def test_rejects_asymmetric_wheel_covariance():
    cov = [[1, 0.5, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]   # finite, PSD-ish, NOT symmetric
    pkt = {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE"}, "wheel": {
               "status": "OK", "order": ["LF", "RF", "LR", "RR"], "wheel_radius_m": 0.15,
               "encoder_counts_per_rev": 4096, "samples": [{
                   "t": 0.0, "encoder_delta_rad": [0, 0, 0, 0], "encoder_count_delta": [0, 0, 0, 0],
                   "covariance": cov}]}}}
    with pytest.raises(ValueError, match="symmetric"):
        pio.parse_proprioception(pkt)


def test_rejects_unknown_key_allowlist():
    # a novel field the denylist would MISS -> the strict allow-list rejects it (I3 hardening)
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "samples": [
               {"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0], "covert_field": 1.0}]},
               "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="allow-list"):
        pio.parse_proprioception(pkt)
