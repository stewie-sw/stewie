"""[REQ:AS-16] localization benchmark acceptance (§25 Phase 13): the report carries per-method
metrics, ablations, failure classes across the lunar conditions, a fixed seed, and a reproducible
command."""
import json

from dart import nav_benchmark as NB


def test_report_covers_all_five_methods_with_metrics():
    r = NB.benchmark_report(seed=0)
    assert set(r["methods"]) == {"passive_vo", "stereo_slam", "shadownav", "argus", "fused"}
    # ARGUS carries quantitative metrics (range sigma + accuracy/precision from the sourced models)
    a = r["methods"]["argus"]
    assert a["range_sigma_m"] > 0 and a["accuracy_m"] > 0 and a["precision_m"] > 0
    # the post-re-freeze 0.05 m stereo baseline -> dh/b ratio ~3.49 (the re-freeze flows into the bench)
    assert abs(a["baseline_ratio_dh_over_b"] - 0.1743 / 0.05) < 0.05


def test_report_has_ablation_and_failure_classes_over_conditions():
    r = NB.benchmark_report(seed=0)
    assert "modality_range_sigma" in r["ablation"]
    assert r["ablation"]["parallax_ground_truth_error_rows"]          # seeded ground-truth error rows
    assert set(r["failure_classes"]) == set(r["methods"])             # every method has failure classes
    # the condition axes are the AS-16 set, and methods fail under the right conditions
    assert set(r["conditions"]) == {"sun_angle", "terrain_change", "rocks", "psr",
                                    "camera_degradation", "excavation_state"}
    assert any("psr" in f for f in r["failure_classes"]["shadownav"])         # ShadowNav dies in PSR
    assert any("far_range" in f for f in r["failure_classes"]["argus"])       # ARGUS dies past resolvable range
    assert any("texture" in f for f in r["failure_classes"]["passive_vo"])    # VO dies on low texture
    assert r["failure_classes"]["fused"] == ["all_inputs_simultaneously_lost"]  # robust to any single loss


def test_report_is_seeded_and_reproducible():
    r1 = NB.benchmark_report(seed=0)
    r2 = NB.benchmark_report(seed=0)
    assert r1["seed"] == 0
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)   # deterministic at a fixed seed
    assert "benchmark_report(seed=0)" in r1["reproducible_command"]


def test_report_is_report_only_no_passfail():
    r = NB.benchmark_report(seed=0)
    assert "pass" not in r["note"].split(".")[0] or "report-only" in r["note"]
    # no fabricated verdict keys
    assert "passed" not in r and "failed" not in r and "verdict" not in r
