"""TDD for dart.viz.run_figures: the reusable STEWIE estimator figure generator.

Runs against the REAL keystone artifacts -- the frozen LuSNAR Moon_1 VO estimate (TUM, 547 poses), the
real LuSNAR ground truth (via the reader adapter), and the committed scoring JSON. Data-gated: skips
cleanly where the LuSNAR scene or the keystone artifacts are not present, mirroring the _have_lusnar
pattern in test_lusnar_reader. Pure geometry + plotting (no model loading), so it is fast.

What it pins:
  * the four figures are written and non-empty (real PNG bytes);
  * the recomputed ATE (SE(3) and Sim(3)) reproduces the committed scoring artifact to <1e-3 m -- this
    is the load-bearing check that the figure generator scores identically to the run-time scorer;
  * the metrics JSON is written with the comparison block and the RPE reproduces the committed value;
  * the generic GtSamples input path (positions + timestamps, no orientations) also produces figures.
"""
import json
import os

import numpy as np
import pytest

from dart.viz import run_figures

_LUSNAR_MOON1 = "/mnt/projects/datasets/argus_dem_nav/lusnar/extracted/Moon_1"
_VALID = "/mnt/projects/stewie/code/stewie/eval/validation"
_FROZEN_TUM = os.path.join(_VALID, "lusnar_vo_estimate_2026-06-28.tum")
_REFERENCE = os.path.join(_VALID, "lusnar_vo_dem_anchor_2026-06-28.json")

_have_lusnar = (
    os.path.isdir(os.path.join(_LUSNAR_MOON1, "image0", "color"))
    and os.path.isfile(os.path.join(_LUSNAR_MOON1, "gt.txt"))
    and os.path.isfile(_FROZEN_TUM)
    and os.path.isfile(_REFERENCE)
)
_skip = pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 scene or keystone artifacts not present")

_FIG_KEYS = ("trajectory_overlay", "ate_error_map", "drift_vs_distance", "rpe_curve")


@pytest.fixture(scope="module")
def _result(tmp_path_factory):
    """Generate the figure set once (module-scoped) against the real LuSNAR keystone artifacts."""
    out = tmp_path_factory.mktemp("argus_figs")
    gt = run_figures.lusnar_gt_trajectory(_LUSNAR_MOON1, stride=2)
    return run_figures.generate_figures(
        _FROZEN_TUM, gt, str(out), "lusnar_vo_test",
        reference_artifact=_REFERENCE, ate_tol_m=1e-3,
    )


@_skip
def test_four_pngs_written_and_non_empty(_result):
    figs = _result["figures"]
    assert set(figs) == set(_FIG_KEYS)
    for key in _FIG_KEYS:
        path = figs[key]
        assert os.path.isfile(path), f"missing figure {key}: {path}"
        assert os.path.getsize(path) > 1024, f"figure {key} is suspiciously small ({path})"
        with open(path, "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n", f"figure {key} is not a real PNG ({path})"


@_skip
def test_recomputed_ate_matches_committed_artifact(_result):
    ref = json.load(open(_REFERENCE))["scoring"]
    m = _result["metrics"]
    # SE(3) and Sim(3) ATE reproduce the committed scoring to <1e-3 m.
    assert abs(m["ate_aligned_se3_m"]["rmse"] - ref["ate_aligned_se3_m"]["rmse"]) < 1e-3
    assert abs(m["ate_aligned_sim3_m"]["rmse"] - ref["ate_aligned_sim3_m"]["rmse"]) < 1e-3
    # the Sim(3) scale also reproduces.
    assert abs(m["sim3_scale"] - ref["sim3_scale"]) < 1e-4
    # the comparison block agrees and is recorded.
    c = _result["comparison"]
    assert c["ate_matches_reference"] is True
    assert c["ate_se3_rmse_delta_m"] < 1e-3
    assert c["ate_sim3_rmse_delta_m"] < 1e-3


@_skip
def test_rpe_reproduces_committed_value(_result):
    ref = json.load(open(_REFERENCE))["scoring"]
    m = _result["metrics"]
    assert m["rpe_kind"] == "hand_eye_frame_to_frame"
    # the hand-eye-corrected frame-to-frame RPE matches the committed headline value.
    assert abs(m["rpe_trans_m"]["rmse"] - ref["rpe_frame_to_frame_m"]["rmse"]) < 1e-3
    assert abs(m["rpe_rotation_deg"]["rmse"] - ref["rpe_frame_to_frame_rotation_deg"]["rmse"]) < 1e-3


@_skip
def test_metrics_json_written(_result):
    path = _result["metrics_path"]
    assert os.path.isfile(path)
    on_disk = json.load(open(path))
    assert on_disk["n_pose_pairs"] == 547
    assert on_disk["label"] == "lusnar_vo_test"
    assert "comparison" in on_disk
    assert on_disk["gt_path_length_m"] > 0.0


@_skip
def test_bundle_array_shapes_are_consistent():
    """The per-pose / per-step arrays have the lengths the figures assume (N and N-1)."""
    traj_est = run_figures.load_estimate(_FROZEN_TUM)
    gt = run_figures.lusnar_gt_trajectory(_LUSNAR_MOON1, stride=2)
    b = run_figures.compute_figure_bundle(traj_est, gt)
    n = b.metrics["n_pose_pairs"]
    assert b.gt_xyz.shape == (n, 3)
    assert b.est_aligned_xyz.shape == (n, 3)
    assert b.ate_per_pose_m.shape == (n,)
    assert b.cum_gt_dist_m.shape == (n,)
    assert b.rpe_trans_per_step_m.shape == (n - 1,)
    assert b.rpe_rot_per_step_deg is not None and b.rpe_rot_per_step_deg.shape == (n - 1,)


@_skip
def test_generic_gtsamples_path_without_orientations(tmp_path):
    """The dataset-agnostic GtSamples input (positions + timestamps, no orientations) still produces
    the figure set; ATE is position-based so it matches, and RPE falls back to world-displacement."""
    from dart.lusnar_reader import LusnarReader
    reader = LusnarReader(_LUSNAR_MOON1)
    indices = list(range(0, len(reader), 2))
    pos = np.array([reader.pose(i).position_m for i in indices], float)
    ts = np.array([reader.timestamps[i] for i in indices], float) / 1e9
    gt = run_figures.GtSamples(positions_xyz=pos, timestamps_s=ts)  # no orientations
    res = run_figures.generate_figures(
        _FROZEN_TUM, gt, str(tmp_path), "lusnar_vo_generic",
        reference_artifact=_REFERENCE, ate_tol_m=1e-3,
    )
    assert res["metrics"]["rpe_kind"] == "world_displacement"
    # ATE is unaffected by the missing GT orientation -> still reproduces the committed value.
    ref = json.load(open(_REFERENCE))["scoring"]
    assert abs(res["metrics"]["ate_aligned_se3_m"]["rmse"] - ref["ate_aligned_se3_m"]["rmse"]) < 1e-3
    for key in _FIG_KEYS:
        assert os.path.getsize(res["figures"][key]) > 1024
