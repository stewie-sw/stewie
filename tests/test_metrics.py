import numpy as np

from solnav.eval import metrics


def test_ate_rmse_known():
    est = np.array([[0, 0], [1, 0], [2, 0]], float)
    gt = np.array([[0, 0], [1, 1], [2, 0]], float)
    # errors: 0, 1, 0 -> rms = sqrt(1/3)
    assert abs(metrics.ate_rmse(est, gt) - np.sqrt(1/3)) < 1e-9


def test_final_position_error():
    est = np.array([[0, 0], [3, 4]], float)
    gt = np.array([[0, 0], [0, 0]], float)
    assert abs(metrics.final_position_error(est, gt) - 5.0) < 1e-9


def test_heading_error_wraps():
    est = np.array([np.pi - 0.01]); gt = np.array([-np.pi + 0.01])
    # wrapped diff ~ -0.02 rad -> ~1.15 deg, not ~360
    assert metrics.heading_error_deg(est, gt) < 2.0


def test_rpe_zero_for_identical():
    p = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], float)
    assert metrics.rpe_rmse(p, p) < 1e-12
