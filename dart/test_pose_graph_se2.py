"""#78: the SE(2)+IMU pose-graph upgrade (orientation state + gyro-preintegrated yaw factors).

The 2-D PoseGraph estimates position only; ARGUS needs heading too (the shadow/stereo factors are
bearing-bearing, and the rover drives in its body frame). PoseGraphSE2 estimates (x, y, yaw) per
node via Gauss-Newton on the SE(2) manifold, with:
  - prior            : anchor a node's full pose
  - between          : a relative SE(2) motion (wheel odometry, in the body frame)
  - imu_yaw          : a gyro-PREINTEGRATED relative heading change (the IMU factor)
  - absolute         : a map-relative (x, y) position fix (DEM / shadow)
Planar by design: pitch/roll come from terrain conformance (rover.conform_pose), not free state.
Real factors only; no fabricated measurements.
"""
import math

import pytest

from dart import pose_graph_se2 as PG2


def test_odometry_chain_reproduces_dead_reckoning():
    """[REQ:CP-06] a straight body-frame odometry chain integrates to the dead-reckoned pose."""
    g = PG2.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.01, sigma_yaw=0.01)
    g.add_between(0, 1, (1.0, 0.0, 0.0), sigma_xy=0.05, sigma_yaw=0.05)   # 1 m forward
    g.add_between(1, 2, (1.0, 0.0, math.pi / 2), sigma_xy=0.05, sigma_yaw=0.05)  # 1 m + turn 90deg
    est = g.optimize()
    assert est[1] == pytest.approx((1.0, 0.0, 0.0), abs=1e-3)
    assert est[2][0] == pytest.approx(2.0, abs=1e-3) and est[2][1] == pytest.approx(0.0, abs=1e-3)
    assert est[2][2] == pytest.approx(math.pi / 2, abs=1e-3)              # heading carried


def test_imu_yaw_factor_corrects_a_drifted_heading():
    """[REQ:SN] a gyro-preintegrated yaw factor pulls a drifted heading toward the measured turn,
    and the node's yaw uncertainty shrinks below the odometry-only value."""
    g = PG2.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.01, sigma_yaw=0.01)
    g.add_between(0, 1, (1.0, 0.0, 0.30), sigma_xy=0.05, sigma_yaw=0.50)  # noisy odo heading
    odo = g.optimize_with_cov()
    g.add_imu_yaw(0, 1, 0.10, sigma=0.02)                                # the gyro says +0.10 rad
    fused = g.optimize_with_cov()
    assert abs(fused["pose"][1][2] - 0.10) < abs(odo["pose"][1][2] - 0.10)  # pulled toward the gyro
    assert fused["yaw_sigma"][1] < odo["yaw_sigma"][1]                    # heading sigma shrinks


def test_absolute_fix_pulls_position_back_and_shrinks_sigma():
    """[REQ:CP-06] a DEM/shadow (x,y) fix corrects accumulated drift; the node's xy sigma shrinks."""
    g = PG2.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.01, sigma_yaw=0.01)
    g.add_between(0, 1, (1.0, 0.0, 0.0), sigma_xy=0.30, sigma_yaw=0.30)
    g.add_between(1, 2, (1.0, 0.0, 0.0), sigma_xy=0.30, sigma_yaw=0.30)
    odo = g.optimize_with_cov()
    g.add_absolute(2, (1.85, 0.10), sigma=0.05)
    fused = g.optimize_with_cov()
    assert abs(fused["pose"][2][0] - 1.85) < abs(odo["pose"][2][0] - 1.85)
    assert fused["xy_sigma"][2] < odo["xy_sigma"][2]


def test_turning_chain_places_nodes_with_heading_coupling():
    """SE(2) couples heading into translation: forward motion after a 90deg turn moves in +y."""
    g = PG2.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, math.pi / 2), sigma_xy=0.01, sigma_yaw=0.01)  # facing +y
    g.add_between(0, 1, (1.0, 0.0, 0.0), sigma_xy=0.05, sigma_yaw=0.05)      # 1 m "forward" = +y
    est = g.optimize()
    assert est[1][0] == pytest.approx(0.0, abs=1e-3) and est[1][1] == pytest.approx(1.0, abs=1e-3)


def test_shadow_yaw_factor_corrects_heading_weakly():
    # [REQ:SN-03] shadow fused as a weak covariance-weighted yaw factor, never an unqualified heading
    """SN-03 [REQ:SN-03]: an accepted shadow gives a WEAK absolute-yaw factor (covariance-weighted),
    never an unqualified heading. A sharp (low-sun) shadow pulls a drifted heading toward the
    shadow-derived yaw and shrinks yaw sigma; a fuzzy (high-sun, large-sigma) shadow does NOT
    dominate a confident prior."""
    # yaw_from_shadow: the rover heading implied by where the (anti-solar) shadow sits in body frame
    measured = PG2.yaw_from_shadow(shadow_world_az=0.0, observed_body_bearing=-0.10)
    assert abs(measured - 0.10) < 1e-9                        # yaw = world_az - body_bearing

    # a SHARP shadow (small sigma) corrects a drifted prior + shrinks sigma
    g = PG2.PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.30), sigma_xy=0.01, sigma_yaw=0.50)   # drifted heading, uncertain
    base = g.optimize_with_cov()
    g.add_shadow_yaw(0, measured_yaw=0.10, sigma=0.05)               # sharp shadow says yaw ~0.10
    fused = g.optimize_with_cov()
    assert abs(fused["pose"][0][2] - 0.10) < abs(base["pose"][0][2] - 0.10)   # pulled toward the shadow
    assert fused["yaw_sigma"][0] < base["yaw_sigma"][0]                       # weak fix still shrinks sigma

    # a FUZZY shadow (large sigma) must NOT override a CONFIDENT prior (the 'weak, never unqualified' rule)
    g2 = PG2.PoseGraphSE2()
    g2.add_prior(0, (0.0, 0.0, 0.05), sigma_xy=0.01, sigma_yaw=0.02)  # confident heading 0.05
    g2.add_shadow_yaw(0, measured_yaw=0.80, sigma=1.5)               # a fuzzy, far-off shadow
    out = g2.optimize()
    assert abs(out[0][2] - 0.05) < 0.10                              # prior holds; shadow doesn't dominate


def test_h15_gauge_free_se2_graph_reports_unobservable_not_finite_sigma():
    """Audit H-15 (2026-06-13): an SE(2) graph with only relative (between) factors is GAUGE-FREE -- the
    global (x,y,yaw) is unobservable. The solver ridge keeps it solvable but the covariance is ridge-induced
    (the audit probe got ~23.5 km), NOT physical. optimize_with_cov must report observable=False with
    INFINITE xy/yaw sigma; a prior anchors the gauge -> observable with finite sigma."""
    import math
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    g.add_between(0, 1, (1.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)   # only relative -> gauge-free
    out = g.optimize_with_cov()
    assert out["observable"] is False
    assert math.isinf(out["xy_sigma"][0]) and math.isinf(out["yaw_sigma"][1])
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)        # anchor -> observable
    out2 = g.optimize_with_cov()
    assert out2["observable"] is True and math.isfinite(out2["xy_sigma"][1])
