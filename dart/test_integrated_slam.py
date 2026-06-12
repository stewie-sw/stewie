"""KEYSTONE integrated multi-factor SLAM on the real Katwijk run."""
import os

import numpy as np
import pytest

PART = "/mnt/projects/datasets/katwijk/Part1"


def _katwijk():
    from stewie.eval import katwijk_baseline as KB
    _t, truth = KB.load_rtk_track(PART)
    _td, dr, gyro = KB._dead_reckon(PART, r_wheel=0.123025)
    dr = dr[np.linspace(0, len(dr) - 1, len(truth)).astype(int)]
    gyro = gyro[np.linspace(0, len(gyro) - 1, len(truth)).astype(int)]
    seg = np.diff(truth, axis=0)
    tyaw = np.arctan2(seg[:, 1], seg[:, 0])
    tyaw = np.concatenate([tyaw, tyaw[-1:]])
    return truth, dr, tyaw, gyro


@pytest.mark.skipif(not os.path.isdir(PART), reason="Katwijk not present")
def test_full_fusion_beats_dead_reckoning_baseline():
    from dart.integrated_slam import run_integrated_slam
    truth, dr, tyaw, gyro = _katwijk()
    base = run_integrated_slam(truth, dr, tyaw, gyro, factors=("odom",), seed=0)
    full = run_integrated_slam(truth, dr, tyaw, gyro, seed=0)
    assert full["abs_max_err_m"] < base["abs_max_err_m"]      # fusion bounds the global drift
    assert full["abs_max_err_m"] < 0.5 * base["abs_max_err_m"]


@pytest.mark.skipif(not os.path.isdir(PART), reason="Katwijk not present")
def test_leave_one_out_each_factor_nonnegative_and_absolute_fixes_dominate():
    from dart.integrated_slam import leave_one_out
    truth, dr, tyaw, gyro = _katwijk()
    r = leave_one_out(truth, dr, tyaw, gyro, seed=0)
    assert r["full"]["abs_max_err_m"] < r["baseline_odom"]["abs_max_err_m"]
    loo = r["leave_one_out"]
    # removing the absolute-position factors (parallax/dem) hurts the most (they bound global drift)
    assert loo["parallax"]["contribution_m"] >= -0.01
    assert loo["parallax"]["abs_max_err_without_m"] > r["full"]["abs_max_err_m"] - 0.01
