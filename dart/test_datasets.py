"""Dataset-agnostic perception: any dataset yields a PerceptionFrame; detect + score run unchanged.
Real datasets swap in via a load_<name>_frame adapter (none fabricated). Sim renders are the only data."""
import os

import numpy as np
import pytest

from dart import datasets as DS

_TR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dissertation", "validation", "a6_traverse")
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


_AI4 = "/mnt/projects/datasets/ai4mars/extracted/ai4mars-dataset-merged-0.6"
_AI4_HAVE = os.path.isdir(os.path.join(_AI4, "msl/ncam/images/edr"))


@pytest.mark.skipif(not _AI4_HAVE, reason="AI4Mars not extracted")
def test_ai4mars_adapter_loads_real_frame_and_scores():
    import glob
    frame = None
    for p in sorted(glob.glob(os.path.join(_AI4, "msl/ncam/images/edr/*.JPG"))):
        base = os.path.splitext(os.path.basename(p))[0]
        try:
            f = DS.load_ai4mars_frame(_AI4, base)
        except FileNotFoundError:
            continue
        if f.labels:
            frame = f
            break
    assert frame is not None and frame.image_right is None and frame.source.startswith("ai4mars:")
    assert all(lb.radius_px > 0 for lb in frame.labels)         # real big-rock label centroids
    m = DS.score(frame, DS.detect(frame))                       # detect + score on REAL Mars imagery
    assert m["precision"] is not None and 0.0 <= m["precision"] <= 1.0
