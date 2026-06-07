from scripts.validate_g1_g2 import validate


def test_gate_validation_is_reproducible_and_honest():
    report = validate()
    assert report["g1"]["contract_checks"]["truth_physical_separation"] == "PASS"
    assert report["g2"]["fixed_reference_camera"] == "front_left"
    assert report["g2"]["lr_consistent_fraction"] > 0.0
    assert not report["g2"]["covariance_calibrated"]
    assert report["release_gate_summary"]["G1"] == "NOT_PASSED"
    assert report["release_gate_summary"]["G2"] == "NOT_PASSED"
