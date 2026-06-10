import numpy as np
import pytest

from stewie.eval import metrics


def test_ate_raw_known():
    est = np.array([[0, 0], [1, 0], [2, 0]], float)
    gt = np.array([[0, 0], [1, 1], [2, 0]], float)
    assert abs(metrics.ate_rmse_raw(est, gt) - np.sqrt(1 / 3)) < 1e-9   # errors 0,1,0


def test_ate_aligned_is_gauge_invariant():
    # an S-ish path, then a GLOBAL rotation + translation -> aligned ATE ~ 0
    gt = np.array([[0, 0], [1, 0.2], [2, 0.1], [3, -0.3], [4, 0.0]], float)
    th = np.radians(90.0); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    est = (R @ gt.T).T + np.array([5.0, -2.0])
    assert metrics.ate_rmse(est, gt) < 1e-9         # alignment removes the global gauge
    assert metrics.ate_rmse_raw(est, gt) > 1.0      # raw sees the whole gauge


def test_rpe_gauge_invariant():
    gt = np.array([[0, 0, 0], [1, 0, 0.2], [2, 0.3, 0.4], [2.5, 1.0, 1.0]], float)
    th = np.radians(37.0); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    est = gt.copy(); est[:, :2] = (R @ gt[:, :2].T).T + np.array([3.0, 1.0]); est[:, 2] = gt[:, 2] + th
    assert metrics.rpe_rmse(est, gt) < 1e-9          # identical motion under a global gauge -> 0
    assert metrics.rpe_rmse(gt, gt) < 1e-12


def test_umeyama_recovers_known_transform():
    src = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], float)
    th = np.radians(30.0); R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    dst = (R @ src.T).T + np.array([2.0, -1.0])
    Rm, t, s = metrics.umeyama_align_2d(src, dst)
    assert np.allclose(Rm, R, atol=1e-9) and np.allclose(t, [2, -1], atol=1e-9)


def test_heading_error_wraps():
    assert metrics.heading_error_deg(np.array([np.pi - 0.01]), np.array([-np.pi + 0.01])) < 2.0


@pytest.mark.parametrize(
    ("fn", "est", "gt"),
    [
        (metrics.umeyama_align_2d, np.empty((0, 2)), np.empty((0, 2))),
        (metrics.final_position_error, np.empty((0, 2)), np.empty((0, 2))),
        (metrics.final_position_error, np.zeros((2, 2)), np.zeros((3, 2))),
        (metrics.ate_rmse, np.array([[0.0, np.nan], [1.0, 0.0]]), np.zeros((2, 2))),
    ],
)
def test_metrics_reject_invalid_trajectories(fn, est, gt):
    with pytest.raises(ValueError):
        fn(est, gt)


def test_similarity_alignment_rejects_zero_source_variance():
    src = np.ones((3, 2))
    with pytest.raises(ValueError, match="nonzero source variance"):
        metrics.umeyama_align_2d(src, src, with_scale=True)


def test_rpe_requires_heading_column():
    with pytest.raises(ValueError, match=r">=3"):
        metrics.rpe_rmse(np.zeros((2, 2)), np.zeros((2, 2)))


def test_heading_error_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="shape mismatch"):
        metrics.heading_error_deg(np.zeros(2), np.zeros(3))
    with pytest.raises(ValueError, match="finite"):
        metrics.heading_error_deg(np.array([np.nan]), np.array([0.0]))
