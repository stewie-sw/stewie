"""[REQ:PM-03] Eval-mode semantic segmentation from grayscale WITHOUT truth masks.

STEWIE DART perception must label at least ground / rock / lander / fiducial / sky from a
grayscale render with NO truth mask supplied (evaluation mode). These tests feed a real
Godot render, assert the per-pixel labels partition the frame and cover the closeable
classes, prove the perception signature takes an image ONLY (invariant I3 -- truth
firewall), and score the rock labels against held-out clast TRUTH on a strictly separate
EVAL path (tagged GROUND_TRUTH_EVAL).

Honesty gate: lander and fiducial are NOT closeable from grayscale appearance alone here
(no AprilTag is present in this render; a reliable off-board-hardware / marker segmenter
that works from grayscale needs a learned model on GPU). They are declared GATED and
returned as empty masks -- never fabricated.
"""
import inspect
import json
import os

import numpy as np
import pytest
from imageio.v3 import imread

from dart import masking
from dart import rock_detect as rd

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
_SAMPLES = os.path.normpath(os.path.join(ROOT, "samples"))
# Real stewie render that has all four closeable classes visible (black airless sky at the
# top, lit regolith ground, sunlit boulder caps, and a foreground crater shadow) AND a
# matching camera pose + clast truth for the EVAL-path scoring below.
FRAME = os.path.join(ROOT, "stewie", "eval", "validation", "a6_traverse",
                     "cam", "frame_000", "front_left.png")
TRUTH_POSES = os.path.join(ROOT, "stewie", "eval", "validation", "a6_traverse",
                           "truth", "truth.json")
SEQUENCE = os.path.join(ROOT, "stewie", "eval", "validation", "a6_traverse", "sequence.json")
CRATER_META = os.path.join(_SAMPLES, "crater_boulders", "metadata.json")

_have_frame = os.path.exists(FRAME)
_have_eval = all(os.path.exists(p) for p in (FRAME, TRUTH_POSES, SEQUENCE, CRATER_META))
needs_frame = pytest.mark.skipif(not _have_frame, reason="real render absent")
needs_eval = pytest.mark.skipif(not _have_eval, reason="real render/truth eval inputs absent")

# The row's five named classes plus the self-supervised shadow subset.
ROW_CLASSES = ("ground", "rock", "lander", "fiducial", "sky")


def test_segment_signature_takes_only_an_image():  # [REQ:PM-03]
    # I3 firewall at the API level: the segmenter cannot be handed a truth mask, pose, or
    # clast metadata -- it is a pure function of the rendered image (+ tuning knobs).
    params = list(inspect.signature(masking.segment_eval_mode).parameters)
    assert params and params[0] == "image"
    for forbidden in ("truth", "pose", "mask", "clast", "metadata", "gt", "label", "center"):
        assert not any(forbidden in p.lower() for p in params), \
            f"segmenter exposes a truth-side parameter containing '{forbidden}'"


@needs_frame
def test_segment_covers_classes_and_partitions():  # [REQ:PM-03]
    img = np.asarray(imread(FRAME))
    seg = masking.segment_eval_mode(img)
    assert seg.provenance == "RUNTIME_DERIVED"  # perception output, not a truth input
    # every one of the row's five named classes is present as a label key (+ shadow)
    for c in ROW_CLASSES:
        assert c in seg.labels, f"missing class label '{c}'"
    assert "shadow" in seg.labels
    H, W = img.shape[:2]
    for c, m in seg.labels.items():
        assert m.dtype == np.bool_ and m.shape == (H, W), f"bad mask for '{c}'"
    # the closeable classes are real, non-empty regions recovered from grayscale
    for c in ("sky", "ground", "rock", "shadow"):
        assert seg.labels[c].any(), f"closeable class '{c}' is empty"
    # per-pixel partition: every pixel gets exactly one label across all classes
    stacked = np.stack(list(seg.labels.values())).astype(int).sum(axis=0)
    assert stacked.min() == 1 and stacked.max() == 1, "labels do not partition the frame"


@needs_frame
def test_lander_fiducial_declared_gated_not_faked():  # [REQ:PM-03]
    # The two classes that are NOT closeable from grayscale appearance here must be declared
    # GATED and returned empty -- an honest gate, never fabricated detections.
    img = np.asarray(imread(FRAME))
    seg = masking.segment_eval_mode(img)
    assert seg.gated_classes == ("lander", "fiducial")
    for c in seg.gated_classes:
        assert not seg.labels[c].any(), f"gated class '{c}' must not be fabricated"


@needs_frame
def test_sky_is_top_region_not_foreground_shadow():  # [REQ:PM-03]
    # The physically meaningful check that distinguishes sky from shadow: airless lunar sky
    # is the BLACK region connected to the top of the frame (space is up in a rover forward
    # camera). The foreground crater shadow -- equally dark -- must NOT be labelled sky.
    img = np.asarray(imread(FRAME))
    seg = masking.segment_eval_mode(img)
    sky = seg.labels["sky"]
    h = sky.shape[0]
    top_band = sky[: h // 5]
    bottom_band = sky[-3 * h // 10:]
    assert top_band.mean() > 0.5, "sky not found in the top band"
    assert bottom_band.mean() < 0.05, "sky label leaked into the foreground (shadow mislabelled)"


@needs_eval
def test_score_rock_labels_vs_held_out_truth_eval_path():  # [REQ:PM-03]
    # EVAL path only: the segmenter runs truth-free above; here the held-out clast TRUTH is
    # projected with the true camera pose and the rock LABEL is scored against it. Truth
    # enters ONLY this scoring call, and the report is tagged GROUND_TRUTH_EVAL.
    img = np.asarray(imread(FRAME))
    seg = masking.segment_eval_mode(img)                      # truth-free perception
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    projected = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    report = masking.score_rock_labels(seg.labels["rock"], projected, min_radius_px=4.0)
    assert report.provenance == "GROUND_TRUTH_EVAL"
    assert report.n_truth_visible > 5                         # a real held-out truth set
    assert report.n_on_rock_label > 0
    assert 0.0 <= report.recall <= 1.0
    # genuine recovery, not a tautology: the rock label lands on a clear majority-fraction of
    # the visible truth caps (measured ~0.41-0.50 on this real frame).
    assert report.recall > 0.3


def test_score_rock_labels_empty_truth_raises():  # [REQ:PM-03]
    with pytest.raises(ValueError):
        masking.score_rock_labels(np.zeros((8, 8), dtype=bool), [], min_radius_px=4.0)
