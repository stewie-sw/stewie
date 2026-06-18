from stewie.specs.system_profile import IPEX


def test_camera_counts():
    assert IPEX.n_cameras == 8
    assert IPEX.max_live_cameras == 4


def test_real_stereo_and_intrinsics():
    assert abs(IPEX.stereo_baseline_m - 0.07) < 1e-3
    assert 600 < IPEX.fx_px < 750


def test_energy_model():
    assert abs(IPEX.pack_joules() - 1332.0 * 3600.0) < 1e-6
    assert IPEX.drive_j_per_m > 0 and IPEX.dig_j_per_kg > IPEX.drive_j_per_m


def test_regolith_and_drums():
    assert IPEX.n_drums == 4
    assert abs(IPEX.regolith_capacity_kg() - 30.0) < 1e-9   # 30 kg/cycle [SPEC]
    assert IPEX.regolith_per_cycle_min_kg == 15.0


def test_mobility_envelope():
    assert IPEX.slope_max_deg == 15.0
    assert abs(IPEX.drive_speed_ms - 0.30) < 1e-9
    assert IPEX.arm_angle_max_rad > 2.0           # absolute mechanical max
    assert IPEX.arm_nominal_max_deg == 55.0       # nominal ops limit [SPEC]
    assert abs(IPEX.scale_factor_vs_rassor2 - 0.7) < 1e-9


def test_fiducial_spec():
    assert IPEX.apriltag_family == "tag36h11"
    assert abs(IPEX.apriltag_size_m - 0.15) < 1e-9
