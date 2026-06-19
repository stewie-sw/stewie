"""[REQ:AS-07] integrated truth-denied nav-spine acceptance (§25 Phase 5).

Runs the REAL spine (stereo VO + obstacle detection) on the real a6_traverse rendered stereo and
asserts the one truth-denied report carries ATE, coverage, obstacle recall, and recovery decisions,
and that the estimator entry takes NO truth input (invariant I3)."""
import inspect
import os

from stewie.eval import nav_spine_eval as nse

_HERE = os.path.dirname(os.path.abspath(__file__))
CAM = os.path.join(_HERE, "validation", "a6_traverse", "cam")
TRUTH = os.path.join(_HERE, "validation", "a6_traverse", "truth", "truth.json")


def _report():
    return nse.run_nav_spine(CAM, hfov_deg=73.99, baseline_m=0.07)


def test_run_nav_spine_takes_no_truth_input():
    # invariant I3: the estimator entry accepts ONLY images + calibration -- no pose/truth field
    params = set(inspect.signature(nse.run_nav_spine).parameters)
    for forbidden in ("truth", "pose", "gt", "ground_truth", "slip", "clast", "truth_path"):
        assert forbidden not in params, f"estimator entry exposes a truth field: {forbidden}"
    assert params == {"cam_dir", "hfov_deg", "baseline_m"}


def test_truth_denied_report_carries_the_full_metric_set():
    sc = nse.score_nav(_report(), TRUTH)
    for key in ("ate_m", "coverage_frac", "recovery_holds", "obstacles_detected",
                "path_len_err_m", "n_frames"):
        assert key in sc, f"AS-07 report missing {key}"
    assert sc["truth_channel"] == "GROUND_TRUTH_EVAL"


def test_ate_and_path_length_are_real_and_bounded():
    sc = nse.score_nav(_report(), TRUTH)
    assert sc["n_frames"] == 4
    # real VO on the real 0.86 m traverse: ATE within a loose nav bound, path recovered to scale
    assert 0.0 < sc["ate_m"] < 0.25, sc["ate_m"]
    assert 0.5 < sc["est_path_len_m"] < 1.2, sc["est_path_len_m"]
    assert sc["path_len_err_m"] < 0.25, sc["path_len_err_m"]


def test_coverage_recovery_and_obstacle_detection_reported():
    sc = nse.score_nav(_report(), TRUTH)
    assert 0.0 <= sc["coverage_frac"] <= 1.0
    assert sc["coverage_frac"] == 1.0          # the clean a6 traverse: every inter-frame step valid
    assert sc["recovery_holds"] == 0           # no VO loss on this traverse (held-pose recovery count)
    assert sc["obstacles_detected"] > 0        # the rocky crater_boulders scene yields real detections
