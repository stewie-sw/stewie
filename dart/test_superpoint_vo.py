"""TDD for dart.superpoint_vo: SuperPoint+LightGlue stereo VO on the REAL LuSNAR Moon_1 traverse.

Real inputs only (the on-disk UE-rendered LuSNAR sensor frames). The tests prove:
  * the truth firewall (invariant I3): the estimator signature accepts images + a StereoVOConfig only
    -- no pose / GtPose / gt / truth parameter -- AND a poison run (every GT position corrupted) yields
    a byte-identical estimate, since the estimator output cannot depend on GT it never receives;
  * the SuperPoint+LightGlue stereo-PnP VO runs on a few real frames and produces a physically sane
    metric trajectory (positive stereo depths, a non-degenerate path, valid steps).

Ground truth (reader.pose) is read ONLY in the firewall/scoring assertions, never passed to the
estimator.
"""
import inspect
import os

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("lightglue")

from dart.lusnar_reader import (  # noqa: E402
    LUSNAR_BASELINE_M,
    LUSNAR_INTRINSICS,
    LusnarReader,
)
from dart.stereo_vo import StereoVOConfig  # noqa: E402
from dart import superpoint_vo  # noqa: E402

SCENE = "/mnt/projects/datasets/argus_dem_nav/lusnar/extracted/Moon_1"
_have_scene = os.path.isdir(os.path.join(SCENE, "image0", "color"))
pytestmark = pytest.mark.skipif(not _have_scene, reason="LuSNAR Moon_1 scene not present")

# A few REAL frames spanning genuine motion. The rover is parked for the first ~20 frames (GT step
# ~1 mm), so a moving window (frames 30/35/40/45, ~3.3 m of GT travel) actually exercises temporal PnP.
_MOVING_IDXS = [30, 35, 40, 45]
_N = len(_MOVING_IDXS)


def _config() -> StereoVOConfig:
    K = LUSNAR_INTRINSICS
    return StereoVOConfig(
        fx_px=K.fx, fy_px=K.fy, cx_px=K.cx, cy_px=K.cy,
        baseline_m=LUSNAR_BASELINE_M,
        n_features=2048, row_tol_px=2.0, min_disparity_px=1.0,
        reprojection_px=2.0, min_pnp_inliers=12,
    )


def _pairs(reader, idxs=_MOVING_IDXS):
    return [(reader.frame(i).left, reader.frame(i).right) for i in idxs]


def test_estimator_signature_is_pose_free():
    """I3: the estimator API can only receive images + calibration; no GT field is even nameable."""
    sig = inspect.signature(superpoint_vo.estimate_vo_superpoint)
    names = list(sig.parameters)
    assert names[0] == "stereo_pairs"
    for p in names:
        assert not any(bad in p.lower() for bad in ("pose", "gt", "truth", "depth", "lidar")), p
    tri = inspect.signature(superpoint_vo.triangulate_stereo_superpoint)
    for p in tri.parameters:
        assert not any(bad in p.lower() for bad in ("pose", "gt", "truth", "depth", "lidar")), p


def test_stereo_triangulation_is_metric_and_positive():
    """Stereo cloud is non-empty with strictly positive (metric) depths from fx*B/disparity."""
    reader = LusnarReader(SCENE)
    f0 = reader.frame(0)
    cloud, _feats, _kp = superpoint_vo.triangulate_stereo_superpoint(f0.left, f0.right, _config())
    assert cloud.points_3d.shape[0] > 100
    assert np.all(cloud.points_3d[:, 2] > 0.0)
    assert np.all(cloud.disparity_px > 0.0)
    # plausible lunar foreground depths (metres), not degenerate
    assert 0.5 < float(np.median(cloud.points_3d[:, 2])) < 100.0


def test_vo_runs_on_real_frames():
    """The full SuperPoint+LightGlue stereo-PnP VO produces a sane metric trajectory on real frames,
    recovering the GROUND-TRUTH path length from stereo scale alone (GT read only here, for scoring)."""
    reader = LusnarReader(SCENE)
    res = superpoint_vo.estimate_vo_superpoint(_pairs(reader), _config())
    traj = res.trajectory_xyz_m
    assert traj.shape == (_N, 3)
    assert res.camera_poses.shape == (_N, 4, 4)
    assert sum(res.vo.step_valid) == _N - 1  # every step trusted on this clean moving window
    # per-step motion is bounded to a physical rover step (no PnP blow-up)
    steps = np.linalg.norm(np.diff(traj, axis=0), axis=1)
    assert float(np.max(steps)) < 5.0
    # metric scale check: recovered path length matches GT path length (stereo scale, no GT input)
    est_len = float(np.sum(steps))
    gt_pos = np.array([reader.pose(i).position_m for i in _MOVING_IDXS], float)  # EVAL-ONLY
    gt_len = float(np.sum(np.linalg.norm(np.diff(gt_pos, axis=0), axis=1)))
    assert gt_len > 2.0  # this window genuinely moves
    assert abs(est_len - gt_len) / gt_len < 0.20  # within 20% (observed ~0.2%)


def test_i3_poison_estimate_is_byte_identical_without_gt():
    """I3 poison test: corrupt every GT position; the estimate is byte-identical (estimator never reads
    GT). Also confirms a GT-withheld reader (require_pose=False) gives the same estimate."""
    cfg = _config()
    clean = LusnarReader(SCENE)
    clean_pairs = _pairs(clean)
    res_clean = superpoint_vo.estimate_vo_superpoint(clean_pairs, cfg, deterministic=True)

    poison = LusnarReader(SCENE)
    poison._gt_pos = poison._gt_pos + 1.0e6        # corrupt every GT position (eval layer only)
    poison._gt_quat = poison._gt_quat + 0.137      # corrupt every GT orientation too
    poison_pairs = _pairs(poison)
    res_poison = superpoint_vo.estimate_vo_superpoint(poison_pairs, cfg, deterministic=True)

    assert np.array_equal(res_clean.camera_poses, res_poison.camera_poses)
    assert np.array_equal(res_clean.trajectory_xyz_m, res_poison.trajectory_xyz_m)

    withheld = LusnarReader(SCENE, require_pose=False)
    res_withheld = superpoint_vo.estimate_vo_superpoint(_pairs(withheld), cfg, deterministic=True)
    assert np.array_equal(res_clean.camera_poses, res_withheld.camera_poses)
