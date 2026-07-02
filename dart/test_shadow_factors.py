"""[REQ:AS-08] #183/#79 shadow-nav landmarks -> Navigation heading factors. The converter pairs each accepted shadow
landmark (from shadow_landmarks.py) with its body-frame bearing of the anti-solar shadow ray and the
ephemeris anti-solar azimuth, building the gated PoseGraphSE2 shadow_yaw factors. These tests verify
the gate and that the estimator recovers a deliberately-wrong heading from the shadow factors. Real
estimator, no synthetic sensor data -- the inputs are literal bearings exercising the math.

Run: <venv>/bin/python -m pytest dart/test_shadow_factors.py -q
"""
import math

from dart import pose_graph_se2 as PG
from dart import shadow_factors as SF


def test_low_contrast_shadow_is_rejected_not_fed_to_graph():
    # a faint/ambiguous shadow (contrast below the gate) is NOT a usable heading measurement
    facs = SF.shadow_yaw_factors([{"contrast": 10.0}], [175.0],
                                 anti_solar_az_deg=215.0, min_contrast=20.0)
    assert facs[0]["accepted"] is False
    g = PG.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), 0.1, 0.5)
    assert SF.add_shadow_yaw_factors(g, 0, facs) == 0     # rejected -> nothing enters the graph


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
    assert all(f["accepted"] for f in facs)
    for f in facs:                                        # each factor implies ~true yaw
        assert abs(PG._wrap(f["yaw_rad"] - math.radians(true_yaw_deg))) < math.radians(3.0)
    # covariance propagation: each accepted factor carries the NON-NEGATIVE information (inverse yaw
    # variance) tied to its sigma_deg, so the graph fuses it covariance-weighted (NavFactor.information
    # >= 0). sigma_deg=6 -> sigma_rad=radians(6) -> information = 1/sigma_rad^2 ~= 91.2.
    sig_rad = math.radians(6.0)
    for f in facs:
        assert f["information"] >= 0.0                    # NavFactor invariant: information is non-negative
        assert f["information"] == 1.0 / f["sigma_rad"] ** 2   # tied to sigma, i.e. 1/sigma^2 (inv variance)
        assert abs(f["information"] - 1.0 / sig_rad ** 2) < 1e-9
        assert f["information"] >= SF.MIN_HEADING_INFORMATION  # sharp shadow -> heading is observable
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
    assert all(f["accepted"] for f in fuzzy)                  # residual/contrast gate passes (good match)
    assert all(f["information"] < SF.MIN_HEADING_INFORMATION for f in fuzzy)   # but below observability floor
    g2 = PG.PoseGraphSE2()
    g2.add_prior(0, (0.0, 0.0, math.radians(-30.0)), sigma_xy=0.05, sigma_yaw=math.radians(90.0))
    assert SF.add_shadow_yaw_factors(g2, 0, fuzzy) == 0       # low observability -> nothing enters the graph


def test_anti_solar_from_sun_azimuth():
    # the shadow ray is opposite the sun; the converter exposes the conversion the ephemeris feeds.
    assert SF.anti_solar_az_deg(35.0) == 215.0
    assert SF.anti_solar_az_deg(300.0) == 120.0
