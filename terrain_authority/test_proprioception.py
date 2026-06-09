"""Proprioception sensor-generation tests (moved from solnav; the producer owns the sensor model)."""
import numpy as np

from terrain_authority import proprioception as pp


def test_imu_white_noise_matches_datasheet_sigma():
    m = pp.ImuWheelModel(seed=1)
    g = np.array([m.step_imu(i * m.dt, 0.0).gyro_z_rps for i in range(2000)])
    assert 0.6 * m.gyro_sigma < g.std() < 1.6 * m.gyro_sigma
    assert abs(g.mean()) < 5 * m.gyro_sigma


def test_imu_tracks_true_yaw_rate():
    m = pp.ImuWheelModel(seed=2)
    g = np.array([m.step_imu(i * m.dt, np.radians(8.0)).gyro_z_rps for i in range(500)])
    assert abs(g.mean() - np.radians(8.0)) < 3 * m.gyro_sigma


def test_imu_sample_carries_covariance_I4():
    s = pp.ImuWheelModel(seed=5).step_imu(0.0, 0.0)
    assert s.gyro_var > 0.0 and s.accel_var > 0.0


def test_wheel_overreads_under_slip():
    s = pp.ImuWheelModel(seed=3).step_wheel(0.0, true_v_mps=0.30, slip=0.20)
    assert abs(s.v_mps - 0.30 / 0.80) < 0.05 and s.provenance == "SIMULATED_SENSOR"


def test_encoder_straight_equal_counts():
    s = pp.ImuWheelModel(seed=0).step_wheel_encoders(0.0, 0.30, 0.0, (0, 0, 0, 0), dt=0.1)
    assert int(s.encoder_count_delta.max() - s.encoder_count_delta.min()) <= 1


def test_encoder_pivot_signs_oppose():
    c = pp.ImuWheelModel(seed=0).step_wheel_encoders(0.0, 0.0, 0.6, (0, 0, 0, 0), dt=0.1).encoder_count_delta
    assert c[0] < 0 and c[2] < 0 and c[1] > 0 and c[3] > 0


def test_encoder_no_truth_leak_and_psd_covariance():
    s = pp.ImuWheelModel(seed=6).step_wheel_encoders(0.0, 0.30, 0.1, (0.0, 0.3, 0.0, 0.3), dt=0.1)
    assert "slip" not in vars(s) and s.provenance == "SIMULATED_SENSOR"
    assert s.covariance.shape == (4, 4) and np.allclose(s.covariance, s.covariance.T)
    assert np.all(np.linalg.eigvalsh(s.covariance) >= -1e-12)


def test_reproducible_seed():
    a = pp.ImuWheelModel(seed=0).step_imu(0.0, 0.1).gyro_z_rps
    b = pp.ImuWheelModel(seed=0).step_imu(0.0, 0.1).gyro_z_rps
    assert a == b


def test_g1a1_param_provenance():
    """G1.A1 acceptance (params now producer-owned): accel range corrected, modeling shortcuts labeled
    ASSUMPTION, wheel band is a design goal not a measured soil law."""
    p = pp.load_params()
    im = p["imu"]; a = im["accel"]; bm = im["bias_model"]
    assert a["range_mps2"] == 200.0 and "range_provenance" in a
    assert "ASSUMPTION" in im.get("white_noise_provenance", "")
    assert "ASSUMPTION" in bm.get("stationary_sigma_provenance", "")
    assert bm["correlation_time_s"] == 1000.0 and "ASSUMPTION" in bm["correlation_time_provenance"]
    prov = p["wheel_odometry"]["acceptance_envelope"]["provenance"].lower()
    assert ("design goal" in prov or "contextual" in prov) and "not a universal measured soil-error law" in prov


def test_runtime_packet_publishes_raw_four_wheel():
    import json
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(3)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.3, 0.1, (0, 0, 0, 0), dt=0.1) for i in range(2)]
    pkt = pp.runtime_proprioception_packet(imu, wheel, sequence_id=0, imu_rate_hz=100, wheel_rate_hz=10)
    w = pkt["channels"]["wheel"]
    assert w["status"] == "OK" and w["order"] == ["LF", "RF", "LR", "RR"]
    assert len(w["samples"][0]["encoder_delta_rad"]) == 4 and w["encoder_counts_per_rev"] == 4096
    assert "slip" not in json.dumps(pkt).lower()                  # no truth (I3)
    assert pkt["channels"]["joints"]["status"] == "UNAVAILABLE"   # honest, not faked


def test_packet_emits_measured_joints_when_supplied():
    # A4: the proprioception packet carries the real measured-joint channel when one is supplied;
    # otherwise joints stays honestly UNAVAILABLE and power is always UNAVAILABLE (no telemetry model).
    from terrain_authority import runtime_packet as rp
    m = pp.ImuWheelModel(seed=0)
    imu = [m.step_imu(i * 0.01, 0.0) for i in range(3)]
    wheel = [m.step_wheel_encoders(i * 0.1, 0.30, 0.0, (0, 0, 0, 0), dt=0.1) for i in range(2)]
    base = pp.runtime_proprioception_packet(imu, wheel, sequence_id=1, imu_rate_hz=100, wheel_rate_hz=10)
    assert base["channels"]["joints"]["status"] == "UNAVAILABLE"     # honest default
    joints = rp.joint_channel(0.1, -0.1, t=0.0)
    pkt = pp.runtime_proprioception_packet(imu, wheel, sequence_id=1, imu_rate_hz=100, wheel_rate_hz=10,
                                           joints=joints)
    jc = pkt["channels"]["joints"]
    assert jc["status"] == "OK" and jc["samples"][0]["arm_front_pitch_rad"] == 0.1
    assert pkt["channels"]["power"]["status"] == "UNAVAILABLE"        # no battery-telemetry model -> not faked
