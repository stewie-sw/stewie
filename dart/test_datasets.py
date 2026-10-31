"""Dataset-agnostic perception: any dataset yields a PerceptionFrame; detect + score run unchanged.
Real datasets swap in via a load_<name>_frame adapter (none fabricated). Sim renders are the only data."""
import os

import numpy as np
import pytest

from dart import datasets as DS

_TR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "stewie", "eval", "validation", "a6_traverse")
_HAVE = os.path.exists(os.path.join(_TR, "cam", "frame_000", "front_left.png"))


def test_mono_frame_detects_without_labels():
    # a monocular frame (no stereo) still detects; scoring without labels -> metrics None (qualitative)
    img = np.zeros((64, 64, 3), np.uint8)
    f = DS.PerceptionFrame(image_left=img, source="unit")
    out = DS.score(f, DS.detect(f))
    assert out["precision"] is None and "qualitative" in out["note"]


@pytest.mark.skipif(not _HAVE, reason="sim render absent")
def test_sim_adapter_detect_and_score_via_interface():
    f = DS.load_sim_frame(_TR, 0, with_labels=True)
    assert f.image_right is not None and f.labels and f.source.startswith("sim:")
    obs = DS.detect(f)
    m = DS.score(f, obs)
    assert m["n_detections"] == len(obs)
    assert 0.0 <= m["precision"] <= 1.0 and 0.0 <= m["recall"] <= 1.0 and 0.0 <= m["f1"] <= 1.0
    # the support filter is dataset-agnostic too: fewer detections, still scorable
    m2 = DS.score(f, DS.detect(f, min_stereo_support=2))
    assert m2["n_detections"] <= m["n_detections"]


def test_no_real_adapter_stub_present():
    # the no-stub rule: datasets.py must not ship a NotImplementedError placeholder adapter
    src = open(DS.__file__).read()
    assert "NotImplementedError" not in src


