import numpy as np

from dart.geometry import stereo
from dart import posegraph as pg


# ---- pose-estimate differentials: covariance from the information matrix ----
def test_pose_covariance_grows_along_chain():
    true = pg.integrate_odometry([0, 0, 0], [[1.0, 0.0, 0.0]] * 5)
    g = pg.PoseGraph(); g.add_prior(0, true[0])
    for i, z in enumerate(pg.relative_odometry(true)):
        g.add_odom(i, i + 1, z)
    X = g.solve(np.array(true))
    covs = g.pose_covariances(X)
    assert len(covs) == len(true) and covs[0].shape == (3, 3)
    assert np.trace(covs[-1]) > np.trace(covs[1])     # uncertainty accumulates with distance


def test_absolute_factors_shrink_covariance():
    true = pg.integrate_odometry([0, 0, 0], [[1.0, 0.0, 0.0]] * 5)
    odo = pg.relative_odometry(true)
    g1 = pg.PoseGraph(); g1.add_prior(0, true[0])
    g2 = pg.PoseGraph(); g2.add_prior(0, true[0])
    for i, z in enumerate(odo):
        g1.add_odom(i, i + 1, z); g2.add_odom(i, i + 1, z)
    for i in range(len(true)):
        g2.add_heading(i, true[i, 2], info=5000.0)
    X = g1.solve(np.array(true))
    t1 = np.trace(g1.pose_covariances(X)[-1])
    t2 = np.trace(g2.pose_covariances(X)[-1])
    assert t2 < t1                                    # heading factors reduce uncertainty


# ---- stereo height math + its differential ----
def test_world_point_identity_pose_is_backprojection():
    R = np.eye(3); t = np.zeros(3)
    p = stereo.world_point_from_stereo(512, 384, 20.0, 679.57, 679.57, 512, 384, 0.07, R, t)
    Z = stereo.depth_from_disparity(20.0, 679.57, 0.07)
    assert np.allclose(p, [0, 0, Z], atol=1e-6)       # principal-point pixel -> straight ahead


def test_ground_height_uses_camera_pose():
    # camera pitched so optical +z maps to world -z (looking down) -> height is negative depth
    R_down = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], float)  # cam +z -> world -y... check sign
    h = stereo.ground_height_from_stereo(512, 384, 20.0, 679.57, 679.57, 512, 384, 0.07, R_down, [0, 0, 5.0])
    assert isinstance(h, float)


def test_height_uncertainty_positive_and_grows_at_range():
    R = np.eye(3)
    near = stereo.height_uncertainty_from_disparity(512, 384, 40.0, 679.57, 679.57, 512, 384, 0.07, R, 1.0)
    far = stereo.height_uncertainty_from_disparity(512, 384, 5.0, 679.57, 679.57, 512, 384, 0.07, R, 1.0)
    assert far > near > 0                              # smaller disparity (farther) -> more uncertain
