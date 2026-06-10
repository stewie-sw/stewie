"""G1.A7 isolated evidence pipeline: truth isolation (I3), freeze-before-truth (I7), baseline reproduce."""
import os
import shutil

import pytest

from stewie.eval import g1_pipeline as P

ROOT = os.path.dirname(__file__)   # stewie/eval holds validation/
CAP = os.path.join(ROOT, "validation", "g1_capture")     # the locked simulated capture
_HAVE = os.path.exists(os.path.join(CAP, "truth.csv"))


@pytest.fixture
def staged(tmp_path):
    return (tmp_path, *P.produce(CAP, str(tmp_path)))


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_produce_separates_runtime_and_truth(staged):
    _, rt, tr = staged
    assert os.path.exists(os.path.join(rt, "imu.csv")) and os.path.exists(os.path.join(rt, "wheel_odom.csv"))
    assert os.path.exists(os.path.join(rt, "config.json"))
    assert not any("truth" in f.lower() for f in os.listdir(rt))     # NO truth in the runtime dir
    assert os.path.exists(os.path.join(tr, "truth.csv"))             # truth on its own channel


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_estimate_consumes_runtime_only_and_freezes(staged):
    tmp, rt, _ = staged
    est, h = P.estimate(rt, os.path.join(tmp, "est"))
    assert os.path.exists(est) and len(h) == 64
    assert open(os.path.join(tmp, "est", "estimate.sha256")).read().strip() == h


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_estimate_rejects_truth_file_in_runtime(staged):
    tmp, rt, tr = staged
    shutil.copy(os.path.join(tr, "truth.csv"), os.path.join(rt, "truth.csv"))     # inject truth
    with pytest.raises(ValueError, match="I3"):
        P.estimate(rt, os.path.join(tmp, "est2"))


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_estimate_rejects_truth_column_in_channel(staged):
    tmp, rt, _ = staged
    p = os.path.join(rt, "imu.csv")
    rows = open(p).read().splitlines()
    rows[0] = rows[0] + ",true_slip"                                 # smuggle a truth column
    rows[1:] = [r + ",0.1" for r in rows[1:]]
    open(p, "w").write("\n".join(rows) + "\n")
    with pytest.raises(ValueError, match="I3"):
        P.estimate(rt, os.path.join(tmp, "est3"))


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_evaluate_requires_frozen_estimate(staged):
    tmp, rt, tr = staged
    P.estimate(rt, os.path.join(tmp, "est"))
    os.remove(os.path.join(tmp, "est", "estimate.sha256"))           # un-freeze
    with pytest.raises(ValueError, match="I7"):
        P.evaluate(os.path.join(tmp, "est"), tr)


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_evaluate_rejects_tampered_estimate(staged):
    tmp, rt, tr = staged
    edir = os.path.join(tmp, "est")
    P.estimate(rt, edir)
    open(os.path.join(edir, "estimate.sha256"), "w").write("0" * 64)  # wrong hash
    with pytest.raises(ValueError, match="I7"):
        P.evaluate(edir, tr)


@pytest.mark.skipif(not _HAVE, reason="g1_capture not present")
def test_end_to_end_reproduces_locked_baseline(staged):
    tmp, rt, tr = staged
    P.estimate(rt, os.path.join(tmp, "est"))
    m = P.evaluate(os.path.join(tmp, "est"), tr)
    assert abs(m["ate_raw_m"] - 4.632) < 0.05        # the locked simulated wheel/IMU sub-baseline
    assert abs(m["ate_aligned_m"] - 2.015) < 0.05
