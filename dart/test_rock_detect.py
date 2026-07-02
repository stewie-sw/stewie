"""Boulder/rock detection on a REAL rendered lunar image, scored against the
crater_boulders clast TRUTH on an EVAL-only path (invariant I3).

The detector input is ONLY the rendered PNG (appearance: sunlit boulder caps next to
hard cast shadows). The clast TRUTH (metadata.json 'clasts' + true camera pose) enters
ONLY the projection/scoring path -- never the detector. These tests assert that firewall
and that precision/recall are computed honestly against the real, independently-projected
truth (a genuine numeric recovery, not a tautology).
"""
import json
import os

import numpy as np
import pytest
from imageio.v3 import imread

from dart import rock_detect as rd
from dart import rock_taxonomy as RT
_REPO_SAMPLES = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "samples"))

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
FRAME0_L = os.path.join(ROOT, "stewie", "eval", "validation", "a6_traverse", "cam", "frame_000", "front_left.png")
TRUTH_POSES = os.path.join(ROOT, "stewie", "eval", "validation", "a6_traverse", "truth", "truth.json")
SEQUENCE = os.path.join(ROOT, "stewie", "eval", "validation", "a6_traverse", "sequence.json")
CRATER_META = os.path.join(_REPO_SAMPLES, "crater_boulders/metadata.json")

_have_inputs = all(os.path.exists(p) for p in (FRAME0_L, TRUTH_POSES, CRATER_META))
needs_inputs = pytest.mark.skipif(not _have_inputs, reason="real render/truth inputs absent")


# --------------------------------------------------------------------------- detector

@needs_inputs
def test_detect_returns_runtime_detections_with_no_truth_access():
    img = np.asarray(imread(FRAME0_L))
    dets = rd.detect_rocks(img)
    assert isinstance(dets, list) and len(dets) > 0
    H, W = img.shape[:2]
    for d in dets:
        assert d.provenance == "RUNTIME_DERIVED"
        assert d.coordinate_frame == "IMAGE_X_RIGHT_Y_DOWN"
        assert 0.0 <= d.u < W and 0.0 <= d.v < H
        assert d.radius_px > 0.0 and np.isfinite(d.score)


def test_detect_on_flat_image_finds_nothing():
    # A uniform frame has no bright-cap/shadow contrast -> no boulders (no false invention).
    assert rd.detect_rocks(np.full((120, 160, 3), 90, np.uint8)) == []


@needs_inputs
def test_detector_signature_takes_only_an_image():  # [REQ:PM-12]
    # I3 firewall at the API level: the detector cannot be handed truth.
    import inspect
    params = list(inspect.signature(rd.detect_rocks).parameters)
    for forbidden in ("clast", "truth", "pose", "metadata", "gt", "center", "slip"):
        assert not any(forbidden in p.lower() for p in params), f"detector exposes '{forbidden}'"


# ------------------------------------------------------------------ truth projection (EVAL)

@needs_inputs
def test_project_clast_truth_lands_on_visible_boulders():
    # Independent geometric recovery: the two largest in-frame clasts (ids 142, 141)
    # must project to bright pixels (the sunlit caps), validating the camera model.
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    img = np.asarray(imread(FRAME0_L))
    gray = img[..., :3].mean(axis=2) if img.ndim == 3 else img.astype(float)
    proj = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    assert len(proj) > 5
    by_id = {p.clast_id: p for p in proj}
    assert 142 in by_id and 141 in by_id
    bright_ref = np.percentile(gray, 90.0)
    for cid in (142, 141):
        p = by_id[cid]
        patch = gray[max(0, int(p.v) - 2):int(p.v) + 3, max(0, int(p.u) - 2):int(p.u) + 3]
        assert patch.max() >= 0.6 * bright_ref  # the projected cap sits on lit terrain


@needs_inputs
def test_visible_truth_count_is_recovered_exactly():
    # MATH anchor: with a fixed visibility rule the number of scorable (in-frame, large
    # enough) truth boulders is a deterministic known integer, recovered from real data.
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    img = np.asarray(imread(FRAME0_L))
    proj = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    visible = [p for p in proj if p.radius_px >= 4.0]
    # 22 with the corrected 1/cz pinhole scaling (audit 2026-06-09): the old slant-range radius
    # under-sized 4 off-axis boulders below the 4 px gate (the previous pinned count was 18)
    assert len(visible) == 22


# ------------------------------------------------------------------------ scoring (EVAL)

@needs_inputs
def test_score_precision_recall_consistency():
    img = np.asarray(imread(FRAME0_L))
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    dets = rd.detect_rocks(img)
    proj = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    rep = rd.score_detections(dets, proj, min_radius_px=4.0)
    # honest bookkeeping: TP+FP == matched-detection accounting, TP+FN == scorable truth
    assert rep.true_positives + rep.false_negatives == rep.n_truth_scorable
    assert rep.true_positives <= rep.n_detections
    assert 0.0 <= rep.precision <= 1.0 and 0.0 <= rep.recall <= 1.0
    if rep.true_positives:
        assert abs(rep.precision - rep.true_positives / (rep.true_positives + rep.false_positives)) < 1e-9
        assert abs(rep.recall - rep.true_positives / rep.n_truth_scorable) < 1e-9
    assert rep.provenance == "GROUND_TRUTH_EVAL"  # this report is EVAL-side, not estimator input


@needs_inputs
def test_perfect_detector_against_truth_scores_unity():
    # Feed the projected truth back in as "detections": recall must be 1.0 and every
    # match within tolerance -> proves the matcher is sound (not a rigged constant).
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    img = np.asarray(imread(FRAME0_L))
    proj = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    visible = [p for p in proj if p.radius_px >= 4.0]
    oracle = [rd.RockDetection(u=p.u, v=p.v, radius_px=p.radius_px, score=1.0) for p in visible]
    rep = rd.score_detections(oracle, proj, min_radius_px=4.0)
    assert rep.true_positives == len(visible)
    assert rep.false_negatives == 0
    assert abs(rep.recall - 1.0) < 1e-9


def test_score_empty_truth_raises():
    with pytest.raises(ValueError):
        rd.score_detections([], [], min_radius_px=4.0)


# ---------------------------------------------------------------- acceptance gate (EVAL)

# Class-A hazard acceptance floors on the held-out a6_traverse frame. The pipeline is fully
# deterministic, so the floors sit one-to-two boulders below the measured operating point
# (2026-07-02: hazard recall 13/20 = 0.65, in-band precision 14/38 = 0.368) -- a genuine
# detector regression trips the gate; nothing else moves the numbers.
CLASS_A_RECALL_FLOOR = 0.60
IN_BAND_PRECISION_FLOOR = 0.30


@needs_inputs
def test_class_a_hazard_acceptance_gate():  # [REQ:ML-03]
    """Acceptance gate: Class-A (>7 cm) rock hazards must be recovered from the HELD-OUT
    a6_traverse render at or above the declared floors, scored against the real
    crater_boulders truth labels. The hazard class comes from the operational taxonomy
    (rock_taxonomy.classify -> is_obstacle at the 7 cm avoid threshold), truth enters only
    the projection/scoring path (I3 firewall), and the gate is falsifiable: a degraded
    detector on the same frame fails it."""
    img = np.asarray(imread(FRAME0_L))
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    dets = rd.detect_rocks(img)
    proj = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    rep = rd.score_detections(dets, proj, min_radius_px=4.0)
    # hazard truth = scorable projected clasts whose TAXONOMY class is avoid (>7 cm diameter)
    scorable = [p for p in proj if p.radius_px >= 4.0]
    hazards = [p for p in scorable if RT.classify(2.0 * p.radius_m).is_obstacle]
    assert len(hazards) >= 10  # non-vacuous: a real hazard population is on the frame
    matched_ids = {cid for _, cid in rep.matched_pairs}
    tp = sum(1 for p in hazards if p.clast_id in matched_ids)
    recall = tp / len(hazards)
    assert recall >= CLASS_A_RECALL_FLOOR, (
        f"Class-A hazard recall {recall:.3f} ({tp}/{len(hazards)}) "
        f"below the {CLASS_A_RECALL_FLOOR} acceptance floor")
    assert rep.precision >= IN_BAND_PRECISION_FLOOR, (
        f"in-band precision {rep.precision:.3f} below the {IN_BAND_PRECISION_FLOOR} floor")
    # falsifiability: the SAME gate fails a degraded detector (top-3 detections only) on the
    # same real frame -- the floors are doing work, not rubber-stamping.
    rep_bad = rd.score_detections(dets[:3], proj, min_radius_px=4.0)
    bad_ids = {cid for _, cid in rep_bad.matched_pairs}
    bad_recall = sum(1 for p in hazards if p.clast_id in bad_ids) / len(hazards)
    assert bad_recall < CLASS_A_RECALL_FLOOR


# -------------------------------------------------------------------------------- visual

@needs_inputs
def test_overlay_png_written(tmp_path):
    img = np.asarray(imread(FRAME0_L))
    pose = rd.load_frame_pose(SEQUENCE, TRUTH_POSES, frame=0, camera="front_left")
    clasts = json.loads(open(CRATER_META).read())["clasts"]
    dets = rd.detect_rocks(img)
    proj = rd.project_clast_truth(clasts, pose, img.shape[1], img.shape[0])
    rep = rd.score_detections(dets, proj, min_radius_px=4.0)
    out = tmp_path / "overlay.png"
    rd.save_detection_overlay(img, dets, proj, rep, str(out), min_radius_px=4.0)
    assert out.exists() and out.stat().st_size > 1000
