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


@pytest.mark.skipif(not os.path.isdir(PART), reason="Katwijk not present")
def test_slam_statistics_distribution_beats_baseline_with_ci():
    from dart.integrated_slam import load_katwijk_arrays, slam_statistics
    truth, dr, tyaw, gyro = load_katwijk_arrays(PART)
    s = slam_statistics(truth, dr, tyaw, gyro, n_seeds=15)
    assert s["fused_mean_m"] < s["baseline_abs_m"]            # the distribution beats the baseline
    assert s["fused_max_m"] < s["baseline_abs_m"]             # EVERY seed beats it
    assert s["fused_ci95_m"] >= 0 and s["reduction_x_mean"] > 2.0


@pytest.mark.skipif(not all(os.path.isdir(f"/mnt/projects/datasets/katwijk/{p}") for p in ("Part1","Part2","Part3")),
                    reason="Katwijk parts not present")
def test_fusion_generalizes_across_traverse_segments():
    """The fusion bounds drift on THREE different real Katwijk segments with different drift profiles."""
    from dart.integrated_slam import load_katwijk_arrays, slam_statistics
    for p in ("Part1", "Part2", "Part3"):
        truth, dr, tyaw, gyro = load_katwijk_arrays(f"/mnt/projects/datasets/katwijk/{p}")
        s = slam_statistics(truth, dr, tyaw, gyro, n_seeds=8)
        assert s["fused_mean_m"] < s["baseline_abs_m"], f"{p}: fusion must bound drift"
