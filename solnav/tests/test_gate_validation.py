from solnav.eval.gates import validate


def test_gate_validation_is_reproducible_and_honest():
    report = validate()
    assert report["g1"]["contract_checks"]["truth_physical_separation"] == "PASS"
    assert report["g2"]["fixed_reference_camera"] == "front_left"
    assert report["g2"]["lr_consistent_fraction"] > 0.0
    assert not report["g2"]["covariance_calibrated"]
    # G1 release stays NOT_PASSED (a simulated baseline is locked, but real-world + stereo remain)
    assert report["release_gate_summary"]["G1"].startswith("NOT_PASSED")
    assert report["release_gate_summary"]["G2"] == "NOT_PASSED"
    closure = report["g1"]["simulated_closure"]
    assert closure is not None and closure["stereo"] == "NOT_INCLUDED"
    assert closure["baseline_wheel_imu_ate_raw_m"] > 0.0
    assert report["g1"]["status"] == "SIM_BASELINE_LOCKED_REALWORLD_BLOCKED"
