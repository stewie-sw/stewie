"""A5 consumer: parse + validate the dustgym runtime proprioception packet (round trip + firewalls)."""
import os
import sys

import pytest

from stewie.bridge import proprioception_io as pio

_DUST = os.environ.get("DUSTGYM_ROOT", "/mnt/projects/foss_ipex/dustgym")


def _packet():
    sys.path.insert(0, _DUST)
    from stewie.twin import proprioception as pp
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
    from stewie.sensors.imu_wheel import body_odometry_from_encoders
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


def test_rejects_unit_mismatch():
    # valid samples but WRONG declared units -> reject (A5 acceptance: unit-mismatched fixture fails)
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "units": {"gyro_z": "deg/s", "accel_xy": "m/s^2"},
                                 "samples": [{"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0]}]},
                        "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="unit mismatch"):
        pio.parse_proprioception(pkt)


def test_rejects_missing_units_when_ok():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK",
                                 "samples": [{"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0]}]},
                        "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="missing the required units"):
        pio.parse_proprioception(pkt)


def test_rejects_out_of_order_timestamps():
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "units": {"gyro_z": "rad/s", "accel_xy": "m/s^2"},
                                 "samples": [{"t": 1.0, "gyro_z": 0.0, "accel_xy": [0, 0]},
                                             {"t": 0.5, "gyro_z": 0.0, "accel_xy": [0, 0]}]},
                        "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="monotonic"):
        pio.parse_proprioception(pkt)


def test_rejects_desynchronized_channels():
    # imu window [0,0.04], wheel window [100,100.2] -> disjoint beyond tolerance (no silent resampling)
    iu = {"gyro_z": "rad/s", "accel_xy": "m/s^2"}
    wu = {"encoder_delta": "rad", "encoder_count_delta": "count", "covariance": "rad^2"}
    cov = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    pkt = {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
           "channels": {
               "imu": {"status": "OK", "units": iu, "samples": [
                   {"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0]},
                   {"t": 0.04, "gyro_z": 0.0, "accel_xy": [0, 0]}]},
               "wheel": {"status": "OK", "units": wu, "order": ["LF", "RF", "LR", "RR"],
                         "wheel_radius_m": 0.15, "encoder_counts_per_rev": 4096, "config_revision": "rev0",
                         "samples": [
                             {"t": 100.0, "encoder_delta_rad": [0, 0, 0, 0],
                              "encoder_count_delta": [0, 0, 0, 0], "covariance": cov},
                             {"t": 100.2, "encoder_delta_rad": [0, 0, 0, 0],
                              "encoder_count_delta": [0, 0, 0, 0], "covariance": cov}]}}}
    with pytest.raises(ValueError, match="unsynchronized"):
        pio.parse_proprioception(pkt)


def _wheel_ok_packet(config_revision="rev0"):
    wu = {"encoder_delta": "rad", "encoder_count_delta": "count", "covariance": "rad^2"}
    cov = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    ch = {"status": "OK", "units": wu, "order": ["LF", "RF", "LR", "RR"], "wheel_radius_m": 0.15,
          "encoder_counts_per_rev": 4096, "samples": [
              {"t": 0.0, "encoder_delta_rad": [0, 0, 0, 0], "encoder_count_delta": [0, 0, 0, 0],
               "covariance": cov}]}
    if config_revision is not None:
        ch["config_revision"] = config_revision
    return {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
            "channels": {"imu": {"status": "UNAVAILABLE"}, "wheel": ch}}


def test_rejects_wheel_missing_config_revision():
    with pytest.raises(ValueError, match="config_revision"):
        pio.parse_proprioception(_wheel_ok_packet(config_revision=None))


def test_calibration_profile_identity_match_and_mismatch():
    pio.parse_proprioception(_wheel_ok_packet("rev7"), expected_profile="rev7")     # match -> OK
    with pytest.raises(ValueError, match="calibration profile mismatch"):
        pio.parse_proprioception(_wheel_ok_packet("rev7"), expected_profile="rev9")  # mismatch -> reject


_JU = {"arm_pitch": "rad", "chassis_lift": "m", "camera_height": "m"}


def test_rejects_joint_payload_non_finite():
    # joints OK, valid schema, but a non-finite arm pitch -> reject
    pkt = {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE"}, "wheel": {"status": "UNAVAILABLE"},
                        "joints": {"status": "OK", "units": _JU, "samples": [
                            {"t": 0.0, "arm_front_pitch_rad": float("inf"), "arm_back_pitch_rad": 0.0,
                             "chassis_lift_m": 0.0, "camera_heights_m": {}}]}}}
    with pytest.raises(ValueError, match="non-finite"):
        pio.parse_proprioception(pkt)


def test_rejects_unknown_joint_field():
    pkt = {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE"}, "wheel": {"status": "UNAVAILABLE"},
                        "joints": {"status": "OK", "units": _JU, "samples": [
                            {"t": 0.0, "arm_front_pitch_rad": 0.1, "arm_back_pitch_rad": -0.1,
                             "chassis_lift_m": 0.0, "camera_heights_m": {}, "secret": 1.0}]}}}
    with pytest.raises(ValueError, match="allow-list"):
        pio.parse_proprioception(pkt)


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_round_trip_with_measured_joints():
    sys.path.insert(0, _DUST)
    from stewie.twin import proprioception as pp
    from stewie.twin import runtime_packet as rp
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(5)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.30, 0.0, (0, 0, 0, 0), dt=0.1) for i in range(3)]
    joints = rp.joint_channel(0.1, -0.1, t=0.0)                    # real FK measured-joint channel (A4)
    pkt = pp.runtime_proprioception_packet(imu, wheel, sequence_id=7, imu_rate_hz=100, wheel_rate_hz=10,
                                           joints=joints)
    parsed = pio.parse_proprioception(pkt)                          # A5 validates + returns the joints
    assert parsed["joints"] and "joints" not in parsed["unavailable"]
    assert "camera_heights_m" in parsed["joints"][0] and "power" in parsed["unavailable"]


def test_rejects_stale_channel_against_clock():
    # freshest imu sample at t=0.04 but the consumer clock is at t=100 -> stale, reject (no extrapolation)
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "units": {"gyro_z": "rad/s", "accel_xy": "m/s^2"},
                                 "samples": [{"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0]},
                                             {"t": 0.04, "gyro_z": 0.0, "accel_xy": [0, 0]}]},
                        "wheel": {"status": "UNAVAILABLE"}}}
    pio.parse_proprioception(pkt)                                   # no now_s -> staleness not enforced
    with pytest.raises(ValueError, match="stale"):
        pio.parse_proprioception(pkt, now_s=100.0, max_age_s=1.0)   # consumer clock far ahead -> reject


@pytest.mark.skipif(not os.path.isdir(_DUST), reason="dustgym not available")
def test_round_trip_with_power_telemetry():
    sys.path.insert(0, _DUST)
    from stewie.specs import ipex_specs as sp
    from stewie.twin import proprioception as pp
    from stewie.twin import runtime_packet as rp
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(5)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.30, 0.0, (0, 0, 0, 0), dt=0.1) for i in range(3)]
    power = rp.power_channel(sp.drive_power_w(), 0.85, t=0.0)       # real draw + SoC belief (A4)
    pkt = pp.runtime_proprioception_packet(imu, wheel, sequence_id=7, imu_rate_hz=100, wheel_rate_hz=10,
                                           power=power)
    parsed = pio.parse_proprioception(pkt)                          # A5 per-field validates power
    assert parsed["power"] and "power" not in parsed["unavailable"]
    assert parsed["power"][0]["voltage_v"] > 0 and 0 <= parsed["power"][0]["soc_frac"] <= 1


def test_rejects_power_soc_out_of_range():
    pu = {"voltage": "V", "current": "A", "power": "W", "soc": "frac"}
    pkt = {"schema_version": "proprioception/1.1", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "UNAVAILABLE"}, "wheel": {"status": "UNAVAILABLE"},
                        "power": {"status": "OK", "units": pu, "samples": [
                            {"t": 0.0, "voltage_v": 44.4, "current_a": 1.0, "power_w": 44.4,
                             "soc_frac": 1.5}]}}}
    with pytest.raises(ValueError, match="soc_frac out of"):
        pio.parse_proprioception(pkt)


def test_rejects_negative_imu_variance():
    # audit 2026-06-09: variances are covariances (I4) -> must be >= 0
    pkt = {"schema_version": "proprioception/1.0", "clock": "x", "sequence_id": 0,
           "channels": {"imu": {"status": "OK", "units": {"gyro_z": "rad/s", "accel_xy": "m/s^2"},
                                 "samples": [{"t": 0.0, "gyro_z": 0.0, "accel_xy": [0, 0],
                                              "gyro_var": -1e-6}]},
                        "wheel": {"status": "UNAVAILABLE"}}}
    with pytest.raises(ValueError, match="variance is negative"):
        pio.parse_proprioception(pkt)
