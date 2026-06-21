"""#183/#79 shadow-nav landmarks -> ARGUS heading factors. The converter pairs each accepted shadow
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
    # shadow-SLAM/ARGUS: shadow bearings + ephemeris sun geometry -> gated pose-graph yaw factors
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
    g = PG.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, math.radians(-30.0)), sigma_xy=0.05, sigma_yaw=math.radians(90.0))
    n = SF.add_shadow_yaw_factors(g, 0, facs)
    assert n == 3
    est = g.optimize()[0]
    assert abs(PG._wrap(est[2] - math.radians(true_yaw_deg))) < math.radians(3.0)


def test_anti_solar_from_sun_azimuth():
    # the shadow ray is opposite the sun; the converter exposes the conversion the ephemeris feeds.
    assert SF.anti_solar_az_deg(35.0) == 215.0
    assert SF.anti_solar_az_deg(300.0) == 120.0
