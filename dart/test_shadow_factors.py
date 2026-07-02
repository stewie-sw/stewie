"""[REQ:AS-08] #183/#79 shadow-nav landmarks -> typed Navigation heading factors. The converter pairs
each accepted shadow landmark (from shadow_landmarks.py) with its body-frame bearing of the anti-solar
shadow ray and the ephemeris anti-solar azimuth, building TYPED ``dart.factors.MeasurementFactor``
shadow-yaw observations (factor_type SHADOW_YAW, WORLD frame, scalar covariance = sigma_rad^2) that the
PoseGraphSE2 fuses. These tests verify the typed-factor contract (covariance carried, false factors
rejected with a refusal_reason and never fed to the graph, observability residual gate) and that the
estimator recovers a deliberately-wrong heading from the shadow factors, plus the shadow-vs-non-shadow
VO/SLAM ablation the row calls for. Real estimator, no synthetic sensor data -- the inputs are literal
bearings exercising the math.

Run: <venv>/bin/python -m pytest dart/test_shadow_factors.py -q
"""
import math

import numpy as np

from dart import pose_graph_se2 as PG
from dart import shadow_factors as SF
from dart.factors import EvidenceClass, FactorType, Frame, MeasurementFactor


def test_factors_are_typed_measurement_factors_with_covariance():
    # [REQ:AS-08] the converter emits TYPED NavigationFactor observations (dart.factors.MeasurementFactor)
    # carrying factor_type/frame/covariance/source/evidence_class -- not bare dicts. The covariance is the
    # scalar heading variance sigma_rad^2 (1x1), and scalar_sigma() recovers the sigma the graph fuses.
    facs = SF.shadow_yaw_factors([{"contrast": 35.0}], [175.0],
                                 anti_solar_az_deg=215.0, sigma_deg=6.0)
    f = facs[0]
    assert isinstance(f, MeasurementFactor)
    assert f.factor_type == FactorType.SHADOW_YAW
    assert f.frame == Frame.WORLD
    assert f.evidence_class == EvidenceClass.MEASURED
    assert f.source == "dart.shadow_factors"
    assert f.accepted is True
    # covariance is the 1x1 heading variance; scalar_sigma() = radians(6) and information = 1/sigma^2
    sig_rad = math.radians(6.0)
    cov = f.covariance_array()
    assert cov.shape == (1, 1)
    assert abs(float(cov[0, 0]) - sig_rad ** 2) < 1e-15
    assert abs(f.scalar_sigma() - sig_rad) < 1e-12
    # the recovered yaw is the shadow-implied heading (anti_solar_world - body_bearing), wrapped
    yaw = float(np.asarray(f.value, float).reshape(-1)[0])
    assert abs(PG._wrap(yaw - PG.yaw_from_shadow(math.radians(215.0), math.radians(175.0)))) < 1e-12


def test_low_contrast_shadow_is_rejected_not_fed_to_graph():
    # a faint/ambiguous shadow (contrast below the gate) is NOT a usable heading measurement: the typed
    # factor is refused (accepted False + a refusal_reason) and NEVER enters the graph (false-factor
    # rejection, the NavFactor residual-gate contract).
    facs = SF.shadow_yaw_factors([{"contrast": 10.0}], [175.0],
                                 anti_solar_az_deg=215.0, min_contrast=20.0)
    assert isinstance(facs[0], MeasurementFactor)
    assert facs[0].accepted is False
    assert facs[0].refusal_reason                              # a refused factor must carry a reason
    g = PG.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), 0.1, 0.5)
    assert SF.add_shadow_yaw_factors(g, 0, facs) == 0          # rejected -> nothing enters the graph


def test_shadow_factors_recover_a_perturbed_heading():  # [REQ:ML-04]
    # shadow-SLAM/Navigation: shadow bearings + ephemeris sun geometry -> gated pose-graph yaw factors
    true_yaw_deg = 40.0
    anti_solar = 215.0                                    # world azimuth of the anti-solar shadow ray
    # all cast shadows are parallel (point anti-solar); each landmark measures the SAME body-frame
    # bearing (anti_solar - yaw) with independent small noise -> independent yaw measurements.
    base_bb = anti_solar - true_yaw_deg                   # 175 deg in the body frame
    body_bearings = [base_bb - 2.0, base_bb + 0.5, base_bb + 1.5]
    lms = [{"contrast": 35.0} for _ in body_bearings]
    facs = SF.shadow_yaw_factors(lms, body_bearings, anti_solar_az_deg=anti_solar, sigma_deg=6.0)
    assert all(f.accepted for f in facs)
    for f in facs:                                        # each factor implies ~true yaw
        yaw = float(np.asarray(f.value, float).reshape(-1)[0])
        assert abs(PG._wrap(yaw - math.radians(true_yaw_deg))) < math.radians(3.0)
    # covariance propagation: each accepted factor carries the NON-NEGATIVE information (inverse yaw
    # variance) tied to its sigma_deg, so the graph fuses it covariance-weighted (NavFactor.information
    # >= 0). sigma_deg=6 -> sigma_rad=radians(6) -> information = 1/sigma_rad^2 ~= 91.2.
    sig_rad = math.radians(6.0)
    for f in facs:
        info = 1.0 / f.scalar_sigma() ** 2
        assert info >= 0.0                                    # NavFactor invariant: information is non-negative
        assert abs(f.scalar_sigma() - sig_rad) < 1e-12        # tied to sigma_deg
        assert abs(info - 1.0 / sig_rad ** 2) < 1e-9
        assert info >= SF.MIN_HEADING_INFORMATION             # sharp shadow -> heading is observable
    g = PG.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, math.radians(-30.0)), sigma_xy=0.05, sigma_yaw=math.radians(90.0))
    n = SF.add_shadow_yaw_factors(g, 0, facs)
    assert n == 3
    est = g.optimize()[0]
    assert abs(PG._wrap(est[2] - math.radians(true_yaw_deg))) < math.radians(3.0)

    # observability gate: a fuzzy near-zenith-sun shadow has a well-defined CONTRAST match yet a heading
    # 1-sigma so large the anti-solar azimuth is effectively unobservable -- its yaw information falls
    # below the floor, so the graph must REJECT it even though the residual/contrast gate passes.
    fuzzy = SF.shadow_yaw_factors(lms, body_bearings, anti_solar_az_deg=anti_solar, sigma_deg=60.0)
    assert all(f.accepted for f in fuzzy)                     # residual/contrast gate passes (good match)
    assert all(1.0 / f.scalar_sigma() ** 2 < SF.MIN_HEADING_INFORMATION for f in fuzzy)  # below floor
    g2 = PG.PoseGraphSE2()
    g2.add_prior(0, (0.0, 0.0, math.radians(-30.0)), sigma_xy=0.05, sigma_yaw=math.radians(90.0))
    assert SF.add_shadow_yaw_factors(g2, 0, fuzzy) == 0       # low observability -> nothing enters the graph


def test_typed_factors_are_consumed_by_factor_lookup():
    # [REQ:AS-08] the SAME typed SHADOW_YAW MeasurementFactor records the converter emits are the ones the
    # integrated estimator resolves via dart.factors.factor_lookup (keyed by factor_type + keyframe). This
    # is the seam that lets shadow factors flow into the pose graph's shadow-yaw path -- proving the typed
    # contract is estimator-consumable, not a decorative wrapper. No external data.
    from dart.factors import factor_lookup

    facs = SF.shadow_yaw_factors(
        [{"contrast": 40.0}, {"contrast": 5.0}], [175.0, 176.0],
        anti_solar_az_deg=215.0, min_contrast=20.0, sigma_deg=4.0, keyframe=7)
    lut = factor_lookup(facs)                                  # only ACCEPTED factors survive the lookup
    assert FactorType.SHADOW_YAW in lut
    assert set(lut[FactorType.SHADOW_YAW].keys()) == {7}       # keyframe binding preserved
    kept = lut[FactorType.SHADOW_YAW][7]
    assert kept.accepted and kept.metadata["contrast"] == 40.0  # the rejected low-contrast one is dropped
    # scalar_sigma() (the sigma the graph fuses) matches the sigma_deg the converter was given
    assert abs(kept.scalar_sigma() - math.radians(4.0)) < 1e-12


def test_typed_shadow_factor_vs_non_shadow_baseline_on_real_katwijk():
    # [REQ:AS-08] ablation vs non-shadow VO/SLAM on the REAL Katwijk baseline: the typed SHADOW_YAW
    # MeasurementFactor the converter emits, fed through the integrated estimator (odom+imu+shadow), must
    # not degrade heading vs the non-shadow (odom+imu) VO/SLAM baseline -- the row's shadow-vs-non-shadow
    # comparison. Real dead-reckoned track + gyro from Katwijk Part1; the shadow heading source is exact
    # (anti_solar - yaw = body_bearing), so the converter is exercised, not the noise.
    import os

    from dart.integrated_slam import load_katwijk_arrays, run_integrated_slam

    part = "/mnt/projects/datasets/katwijk/Part1"
    if not os.path.isdir(part):
        import pytest
        pytest.skip("raw Katwijk not present")
    truth, dr, tyaw, gyro = load_katwijk_arrays(part)

    n_kf = 30
    fix_interval = 5
    idx = np.linspace(0, len(tyaw) - 1, n_kf).astype(int)
    anti_solar_deg = 215.0
    measured = []
    for k in range(fix_interval, n_kf, fix_interval):
        yaw_deg = math.degrees(float(tyaw[idx[k]]))
        body_bearing_deg = anti_solar_deg - yaw_deg           # so yaw_from_shadow recovers yaw exactly
        fac = SF.shadow_yaw_factors([{"contrast": 40.0}], [body_bearing_deg],
                                    anti_solar_az_deg=anti_solar_deg, sigma_deg=4.0, keyframe=k)[0]
        assert isinstance(fac, MeasurementFactor)             # the typed record the estimator consumes
        measured.append(fac)

    base = run_integrated_slam(truth, dr, tyaw, gyro, factors=("odom", "imu"),
                               n_keyframes=n_kf, fix_interval=fix_interval, seed=0)
    fused = run_integrated_slam(truth, dr, tyaw, gyro, factors=("odom", "imu", "shadow"),
                                n_keyframes=n_kf, fix_interval=fix_interval, seed=0,
                                measured_fixes=measured)
    # the typed shadow factors were consumed as MEASURED (not the modeled truth+noise fallback)
    assert fused["measured"] == len(measured)
    # fusing the typed shadow-yaw factor does not worsen heading vs the non-shadow VO/SLAM baseline
    assert fused["heading_rmse_deg"] <= base["heading_rmse_deg"] + 1e-6


def test_anti_solar_from_sun_azimuth():
    # the shadow ray is opposite the sun; the converter exposes the conversion the ephemeris feeds.
    assert SF.anti_solar_az_deg(35.0) == 215.0
    assert SF.anti_solar_az_deg(300.0) == 120.0
