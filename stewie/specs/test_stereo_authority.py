"""[REQ:AS-17] gate test for the TRL5 stereo-baseline authority (post-0.05 re-freeze)."""
from stewie.specs import stereo_authority as SA


def test_authority_validates_clean():
    assert SA.validate_stereo_authority() == []


def test_active_is_trl5_final_005_and_loaded_profile_agrees():
    a = SA.active_profile()
    assert a.name == "trl5_final" and a.status == SA.ACTIVE_FLIGHT and abs(a.baseline_m - 0.05) < 1e-9
    assert abs(SA.loaded_profile_baseline_m() - 0.05) < 1e-4


def test_shoulder_split_is_rejected_legacy_and_distinct():
    s = SA.PROFILES["shoulder_split"]
    assert s.status == SA.REJECTED_LEGACY and not s.is_active_default
    assert abs(s.baseline_m - 0.165) < 1e-9
    # the two named baselines must never collapse
    assert SA.TRL5_FINAL_BASELINE_M != SA.SHOULDER_SPLIT_BASELINE_M


def test_gate_rejects_a_profile_that_drifts_to_the_rejected_split():
    import stewie.specs.stereo_authority as m
    orig = m.loaded_profile_baseline_m
    m.loaded_profile_baseline_m = lambda: SA.SHOULDER_SPLIT_BASELINE_M
    try:
        errs = SA.validate_stereo_authority()
        assert any("rejected shoulder split" in e or "!= TRL5-final" in e for e in errs)
    finally:
        m.loaded_profile_baseline_m = orig
