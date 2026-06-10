import numpy as np

from dissertation.eval import metrics
from dissertation import posegraph as pg


def test_two_pose_odometry_recovers():
    g = pg.PoseGraph()
    g.add_prior(0, [0, 0, 0])
    g.add_odom(0, 1, [1.0, 0.0, 0.0])
    X = g.solve(np.zeros((2, 3)))
    assert np.allclose(X[0], [0, 0, 0], atol=1e-6)
    assert np.allclose(X[1], [1, 0, 0], atol=1e-6)


def test_integrate_relative_roundtrip():
    true = np.array([[0, 0, 0], [1, 0, 0.3], [1.8, 0.5, 0.6], [2.0, 1.4, 1.2]], float)
    odo = pg.relative_odometry(true)
    rec = pg.integrate_odometry(true[0], odo)
    assert np.allclose(rec, true, atol=1e-9)


def test_odom_only_graph_equals_dead_reckoning():
    true = np.array([[0, 0, 0], [1, 0, 0.2], [2, 0.3, 0.4]], float)
    odo = pg.relative_odometry(true)
    g = pg.PoseGraph(); g.add_prior(0, true[0])
    for i, z in enumerate(odo):
        g.add_odom(i, i + 1, z)
    X = g.solve(np.zeros((3, 3)))
    assert np.allclose(X, true, atol=1e-5)


def test_solar_heading_factor_reduces_drift():
    # true arc; odometry with a small per-step heading bias -> dead reckoning drifts
    n = 40
    true = pg.integrate_odometry([0, 0, 0], [[0.5, 0.0, 0.05]] * n)
    odo = pg.relative_odometry(true)
    biased = [z + np.array([0, 0, 0.01]) for z in odo]   # 0.01 rad/step heading bias
    dr = pg.integrate_odometry(true[0], biased)           # dead reckoning (drifts)
    # graph with biased odom only
    g1 = pg.PoseGraph(); g1.add_prior(0, true[0])
    for i, z in enumerate(biased):
        g1.add_odom(i, i + 1, z)
    X_odom = g1.solve(np.array(dr))
    # graph with biased odom + solar heading factors (true heading, absolute)
    g2 = pg.PoseGraph(); g2.add_prior(0, true[0])
    for i, z in enumerate(biased):
        g2.add_odom(i, i + 1, z)
    for i in range(0, n + 1, 5):
        g2.add_heading(i, true[i, 2], info=5000.0)
    X_solar = g2.solve(np.array(dr))
    ate_odom = metrics.ate_rmse(X_odom, true)
    ate_solar = metrics.ate_rmse(X_solar, true)
    assert ate_solar < 0.5 * ate_odom        # solar factor materially bounds drift
    assert metrics.heading_error_deg(X_solar[:, 2], true[:, 2]) < metrics.heading_error_deg(X_odom[:, 2], true[:, 2])


def test_multirover_inter_rover_factor_links_frames():
    # two rovers packed into one array (A: 0..2, B: 3..5); inter-rover relative obs ties them
    true = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0],
                     [0, 5, 0], [1, 5, 0], [2, 5, 0]], float)
    g = pg.PoseGraph()
    g.add_prior(0, true[0])
    for i in (0, 1):
        g.add_odom(i, i + 1, pg.relative_odometry(true[0:3])[i])
    for i in (3, 4):
        g.add_odom(i, i + 1, pg.relative_odometry(true[3:6])[i - 3])
    # rover B observed from rover A: relative pose A0->B0 (inter-rover factor)
    z = pg.relative_odometry(np.array([true[0], true[3]]))[0]
    g.add_odom(0, 3, z)
    X = g.solve(np.zeros((6, 3)))
    assert metrics.ate_rmse(X, true) < 1e-4   # B's frame is pinned via A
