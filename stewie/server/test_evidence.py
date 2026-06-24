"""#108: GET /evidence surfaces the grounded navigation evidence for the cockpit -- the comparison
(accuracy/precision vs the cited baselines), generalization (the capability matrix positioning the
three approach classes), and photometric+depth modality precision. All numbers come from
dart.comparison (sourced constants + the parallax covariance model); no synthetic data.
"""
from fastapi.testclient import TestClient

from stewie.server import server as SRV


def _ev():
    return TestClient(SRV.app).get("/evidence")


def test_evidence_route_ok_and_has_the_three_evidence_sections():
    r = _ev()
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    for k in ("capability_matrix", "accuracy_precision", "modality_sigma", "operational_cost"):
        assert k in j, f"missing evidence section {k}"


def test_generalization_matrix_positions_the_three_approach_classes():
    cm = _ev().json()["capability_matrix"]
    assert {"Stanford NAV Lab (LAC)", "ShadowNav (JPL)", "ARGUS"}.issubset(cm.keys())
    # ARGUS is the map-free, active-reconfiguration approach using shadow as a geometric instrument
    assert cm["ARGUS"]["active_reconfiguration"] is True
    assert cm["ARGUS"]["shadow_role"].startswith("GEOMETRIC")
    assert cm["ShadowNav (JPL)"]["needs_orbital_prior"] is True


def test_comparison_reports_accuracy_precision_per_system_with_frames():
    ap = _ev().json()["accuracy_precision"]
    assert ap["ARGUS"]["frame"] == "local (map-free)"
    assert ap["Stanford NAV Lab (LAC)"]["frame"] == "relative (SLAM)"
    assert ap["ShadowNav (JPL)"]["frame"] == "global (orbital map)"
    assert "_note" in ap                                      # the honest different-problem-scales caveat


def test_photometric_depth_modality_articulation_beats_stereo_at_range():
    ms = _ev().json()["modality_sigma"]
    assert ms["range_m"] == 6.0
    assert ms["articulation_advantage_x"] > 1.0
    assert ms["articulation_parallax_sigma_m"] < ms["stereo_sigma_m"]
