"""Integrated multi-factor SE(2) estimator: measured-fix fusion."""

import numpy as np

def test_typed_measured_fixes_feed_yaw_and_anisotropic_xy_without_truth_draws():
    from dart.factors import EvidenceClass, FactorType, Frame, MeasurementFactor
    from dart.integrated_slam import run_integrated_slam

    truth = np.array([[float(i), 0.0] for i in range(12)])
    dr = truth + np.column_stack([np.linspace(0.0, 2.0, 12), np.zeros(12)])
    yaw = np.zeros(12)
    gyro = np.zeros(12)
    typed = [
        MeasurementFactor(FactorType.SHADOW_YAW, 2, 0.0, [[0.01]], Frame.WORLD, "unit", EvidenceClass.MEASURED),
        MeasurementFactor(
            FactorType.PARALLAX_XY,
            2,
            [4.0, 0.0],
            [[0.01, 0.0], [0.0, 1.0]],
            Frame.WORLD,
            "unit",
            EvidenceClass.COMPUTED,
        ),
        MeasurementFactor(
            FactorType.DEM_XY,
            4,
            [8.0, 0.0],
            [[0.04, 0.0], [0.0, 0.04]],
            Frame.DEM,
            "unit",
            EvidenceClass.MEASURED,
        ),
    ]
    out = run_integrated_slam(truth, dr, yaw, gyro, n_keyframes=6, fix_interval=2, measured_fixes=typed)
    assert out["measured"] == 3
    assert out["ate_aligned_m"] < 0.5
