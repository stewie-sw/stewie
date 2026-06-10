"""G1 blocker #4: produce -> estimate -> evaluate as PERMISSION-ISOLATED roles.

The honesty architecture in code, not convention: the PRODUCER writes only produced/ artifacts;
the ESTIMATOR reads produced/ but is structurally DENIED truth files and writes only estimates/;
the EVALUATOR alone reads both sides and writes evaluation/. Violations raise PermissionError at
the file layer (RoleFS), so 'the estimator peeked at truth' is impossible by construction, not by
discipline. Exercised end-to-end on REAL g2cal artifacts.
"""
import json
import os

import pytest

from stewie.eval import roles as R

G2CAL = os.path.join(os.path.dirname(__file__), "validation", "g2cal", "pose_0")


def test_producer_writes_only_produced(tmp_path):
    fs = R.RoleFS("produce", str(tmp_path))
    fs.write_json("produced/sensors.json", {"ok": 1})
    assert json.load(open(tmp_path / "produced" / "sensors.json"))["ok"] == 1
    with pytest.raises(PermissionError):
        fs.write_json("estimates/pose.json", {})
    with pytest.raises(PermissionError):
        fs.write_json("evaluation/verdict.json", {})


def test_estimator_cannot_touch_truth(tmp_path):
    (tmp_path / "produced").mkdir()
    json.dump({"img": "x.png"}, open(tmp_path / "produced" / "sensors.json", "w"))
    json.dump({"true_pose": [0, 0]}, open(tmp_path / "produced" / "evaluation_truth.json", "w"))
    fs = R.RoleFS("estimate", str(tmp_path))
    assert fs.read_json("produced/sensors.json")["img"] == "x.png"
    with pytest.raises(PermissionError):
        fs.read_json("produced/evaluation_truth.json")     # truth is DENIED to the estimator
    fs.write_json("estimates/pose.json", {"xy": [1, 2]})
    with pytest.raises(PermissionError):
        fs.write_json("produced/sensors.json", {"tampered": True})


def test_evaluator_reads_both_writes_verdict(tmp_path):
    (tmp_path / "produced").mkdir(); (tmp_path / "estimates").mkdir()
    json.dump({"true_xy": [1.0, 2.0]}, open(tmp_path / "produced" / "evaluation_truth.json", "w"))
    json.dump({"xy": [1.1, 2.2]}, open(tmp_path / "estimates" / "pose.json", "w"))
    fs = R.RoleFS("evaluate", str(tmp_path))
    truth = fs.read_json("produced/evaluation_truth.json")
    est = fs.read_json("estimates/pose.json")
    err = ((truth["true_xy"][0] - est["xy"][0]) ** 2
           + (truth["true_xy"][1] - est["xy"][1]) ** 2) ** 0.5
    fs.write_json("evaluation/verdict.json", {"err_m": err})
    assert json.load(open(tmp_path / "evaluation" / "verdict.json"))["err_m"] == pytest.approx(
        0.2236, abs=1e-3)
    with pytest.raises(PermissionError):
        fs.write_json("estimates/pose.json", {})           # the evaluator never edits estimates


def test_traversal_escape_refused(tmp_path):
    fs = R.RoleFS("produce", str(tmp_path))
    with pytest.raises(PermissionError):
        fs.write_json("produced/../../etc/passwd.json", {})


@pytest.mark.skipif(not os.path.isdir(G2CAL), reason="g2cal evidence not present")
def test_pipeline_on_real_g2cal_artifacts(tmp_path):
    """The three commands run in role order on a REAL captured pose; the verdict is real."""
    out = R.run_pipeline(G2CAL, str(tmp_path))
    v = json.load(open(os.path.join(str(tmp_path), "evaluation", "verdict.json")))
    assert v == out
    assert v["n_disparities"] > 100
    assert v["expected_within_p10_p90"] is True            # range-consistency, not median-matching
    # the estimator's output exists and contains NO truth-derived fields
    e = json.load(open(os.path.join(str(tmp_path), "estimates", "stereo.json")))
    assert "true" not in json.dumps(e).lower()


@pytest.mark.skipif(not os.path.isdir(G2CAL), reason="g2cal evidence not present")
def test_pipeline_via_runtime_reproduces_direct(tmp_path):
    """THE G1 closure: the locked-capture evaluation run THROUGH the persistent runtime seam
    (produce attaches to the live process; the packet's camera channel references the real
    frames) reproduces the direct pipeline's verdict exactly (same images, same estimator)."""
    direct = R.run_pipeline(G2CAL, str(tmp_path / "direct"))
    via = R.run_pipeline_via_runtime(G2CAL, str(tmp_path / "via"))
    assert via["expected_within_p10_p90"] is True
    for k in ("n_disparities", "median_disparity_px", "expected_disparity_px"):
        assert via[k] == direct[k], f"runtime-fed {k} diverged from the direct evidence"
    assert via["via_persistent_runtime"] is True
