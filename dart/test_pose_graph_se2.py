"""#78: the SE(2)+IMU pose-graph upgrade (orientation state + gyro-preintegrated yaw factors).

The 2-D PoseGraph estimates position only; Navigation needs heading too (the shadow/stereo factors are
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


def test_h30_anisotropic_absolute_factor_keeps_the_gdop_direction():
    """Audit H-30 (2026-06-13): an absolute (x,y) factor must keep its ANISOTROPIC covariance (the GDOP
    direction), not collapse to one scalar sigma. A factor tight in x but loose in y pulls the x error in
    hard while leaving y near the prior -- the directional information a scalar factor would average away."""
    import numpy as np
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    g.add_prior(0, (2.0, 2.0, 0.0), sigma_xy=5.0, sigma_yaw=5.0)        # a weak, drifted prior at (2, 2)
    g.add_absolute_cov(0, (0.0, 0.0), np.diag([0.01, 100.0]))           # observe origin: tight x, loose y
    est = g.optimize()
    assert abs(est[0][0]) < 0.3                                         # x pulled almost to 0 (tight axis)
    assert abs(est[0][1] - 2.0) < 0.7                                   # y stays near the prior (loose axis)
    assert g.optimize_with_cov()["observable"] is True                 # the cov factor anchors translation


def test_m01_robust_loss_rejects_a_gross_outlier_absolute_fix():
    """Audit M-01 (2026-06-14): one gross outlier absolute (x,y) fix on a node that ALSO has good
    redundant fixes must NOT drag that node off truth. With a robust kernel (Huber) the lone outlier is
    down-weighted to a fraction of its squared influence and the good consensus wins; a non-robust
    Gauss-Newton (the old code) averages the outlier in and is pulled metres off. We compare
    robust-vs-naive head-to-head on the SAME graph so a plausible-but-non-robust implementation fails."""
    import numpy as np
    from dart.pose_graph_se2 import PoseGraphSE2

    def build(robust):
        g = PoseGraphSE2(robust=robust)
        g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.05, sigma_yaw=0.05)
        # a straight 5-node odometry chain, 1 m steps along +x
        for k in range(1, 6):
            g.add_between(k - 1, k, (1.0, 0.0, 0.0), sigma_xy=0.30, sigma_yaw=0.30)
        # good absolute fixes near truth on EVERY node (the consensus)
        for k, x in ((1, 1.0), (2, 2.0), (3, 3.0), (4, 4.0), (5, 5.0)):
            g.add_absolute(k, (x, 0.0), sigma=0.10)
        # ONE gross outlier added to node 3 (same sigma as the good fixes, so only the robust kernel
        # -- not a looser sigma -- can reject it): truth is (3, 0) but this fix says (3, 12)
        g.add_absolute(3, (3.0, 12.0), sigma=0.10)
        return g.optimize()

    robust = build(robust=True)
    naive = build(robust=False)
    truth3 = np.array([3.0, 0.0])
    err_robust = np.hypot(robust[3][0] - truth3[0], robust[3][1] - truth3[1])
    err_naive = np.hypot(naive[3][0] - truth3[0], naive[3][1] - truth3[1])
    assert err_robust < 1.0                       # robust kernel keeps node 3 on the good consensus
    assert err_naive > 4.0                         # the squared-loss solve averages the outlier in
    assert err_robust < err_naive                  # the robust kernel is the improvement


def test_m01_reports_convergence_and_conditioning_status():
    """Audit M-01: the solver must expose explicit convergence + conditioning diagnostics, not silently
    return a pose from an unconverged/ill-conditioned solve. A well-anchored graph converges and is
    well-conditioned; the status fields are present and truthful."""
    import math
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.05, sigma_yaw=0.05)
    g.add_between(0, 1, (1.0, 0.0, math.pi / 4), sigma_xy=0.1, sigma_yaw=0.1)
    g.add_between(1, 2, (1.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
    status = g.solve_status()
    assert status["converged"] is True
    assert status["iterations"] >= 1
    assert math.isfinite(status["condition_number"]) and status["condition_number"] > 0.0
    assert status["final_gradient_norm"] < 1e-4    # a real stationary point, not an early stop


def test_m01_singular_unanchored_graph_is_flagged_ill_conditioned_not_silently_returned():
    """Audit M-01: a gauge-free (prior-less) graph is rank-deficient in the global pose. The damped solve
    stays numerically solvable, but the status must FLAG it (well_conditioned False / huge condition
    number), so a caller does not trust a pose the data cannot determine."""
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    g.add_between(0, 1, (1.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)   # only relative -> gauge-free
    status = g.solve_status()
    assert status["well_conditioned"] is False                          # the rank deficiency is reported
    assert status["condition_number"] > 1e6                             # near-singular information matrix


def test_m04_rejects_non_finite_and_non_positive_sigma_inputs():
    """Audit M-04 (2026-06-14): a non-finite or non-positive sigma is NOT a valid measurement
    uncertainty. The old code silently clamped sigma<=0 to 1e-12 (an enormous, fabricated information
    weight); now every factor that takes a sigma must REJECT a non-finite or non-positive value rather
    than fabricate confidence."""
    import math
    import pytest
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    for bad in (0.0, -1.0, math.inf, math.nan):
        with pytest.raises(ValueError):
            g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=bad, sigma_yaw=0.1)
        with pytest.raises(ValueError):
            g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=bad)
        with pytest.raises(ValueError):
            g.add_between(0, 1, (1.0, 0.0, 0.0), sigma_xy=bad, sigma_yaw=0.1)
        with pytest.raises(ValueError):
            g.add_imu_yaw(0, 1, 0.0, sigma=bad)
        with pytest.raises(ValueError):
            g.add_shadow_yaw(0, 0.0, sigma=bad)
        with pytest.raises(ValueError):
            g.add_absolute(0, (0.0, 0.0), sigma=bad)


def test_m04_rejects_invalid_absolute_covariance_inputs():
    """Audit M-04: an anisotropic absolute-fix covariance must be finite and positive-definite. A
    NaN/Inf entry, a negative variance, or a non-symmetric/indefinite matrix is not a covariance and
    must be rejected, not Cholesky-factored into garbage information."""
    import numpy as np
    import pytest
    from dart.pose_graph_se2 import PoseGraphSE2
    g = PoseGraphSE2()
    with pytest.raises(ValueError):
        g.add_absolute_cov(0, (0.0, 0.0), np.array([[np.nan, 0.0], [0.0, 1.0]]))
    with pytest.raises(ValueError):
        g.add_absolute_cov(0, (0.0, 0.0), np.array([[np.inf, 0.0], [0.0, 1.0]]))
    with pytest.raises(ValueError):
        g.add_absolute_cov(0, (0.0, 0.0), np.array([[-1.0, 0.0], [0.0, 1.0]]))   # negative variance
    with pytest.raises(ValueError):
        g.add_absolute_cov(0, (0.0, 0.0), np.array([[1.0, 5.0], [5.0, 1.0]]))    # indefinite
    # a valid PD covariance is accepted
    g.add_absolute_cov(0, (0.0, 0.0), np.diag([0.04, 0.09]))
    assert len(g._abs_cov) == 1


def test_m01_outlier_does_not_corrupt_a_long_loop_closure():
    """Audit M-01: on a longer trajectory with a loop closure, a single bad between-factor must not
    blow up the global solution under the robust kernel. The robust estimate's worst-node error stays
    bounded while the naive solve smears the outlier around the loop."""
    import numpy as np
    from dart.pose_graph_se2 import PoseGraphSE2

    def build(robust):
        g = PoseGraphSE2(robust=robust)
        g.add_prior(0, (0.0, 0.0, 0.0), sigma_xy=0.02, sigma_yaw=0.02)
        # a square loop: 4 corners, 2 m sides, 90 deg turns -> returns to start
        steps = [(2.0, 0.0, math.pi / 2)] * 4
        for k, (dx, dy, dth) in enumerate(steps):
            g.add_between(k, k + 1, (dx, dy, dth), sigma_xy=0.1, sigma_yaw=0.1)
        # loop closure: node 4 should coincide with node 0
        g.add_between(4, 0, (0.0, 0.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
        # a GROSS outlier on one mid-loop edge (claims a 5 m jump that did not happen)
        g.add_between(1, 2, (2.0, 5.0, 0.0), sigma_xy=0.1, sigma_yaw=0.1)
        return g.optimize()

    truth = {0: (0.0, 0.0), 1: (2.0, 0.0), 2: (2.0, 2.0), 3: (0.0, 2.0)}
    robust = build(robust=True)
    naive = build(robust=False)
    worst_robust = max(np.hypot(robust[k][0] - tx, robust[k][1] - ty)
                       for k, (tx, ty) in truth.items())
    worst_naive = max(np.hypot(naive[k][0] - tx, naive[k][1] - ty)
                      for k, (tx, ty) in truth.items())
    assert worst_robust < 1.5                      # robust: the outlier edge is down-weighted
    assert worst_robust < worst_naive              # strictly better than squared-loss
