import numpy as np

from dart.geometry import stereo
from stewie.specs.system_profile import IPEX


def test_depth_from_disparity_known():
    assert abs(stereo.depth_from_disparity(10.0, 1000.0, 0.2) - 20.0) < 1e-9


def test_depth_with_real_ipex_intrinsics():
    # fx and baseline from a real LAC-twin sensors.json
    z = stereo.depth_from_disparity(34.0, IPEX.fx_px, IPEX.stereo_baseline_m)
    assert abs(z - (IPEX.fx_px * IPEX.stereo_baseline_m / 34.0)) < 1e-9
    assert 1.0 < z < 2.0


def test_disparity_depth_roundtrip():
    d = stereo.disparity_from_depth(20.0, 1000.0, 0.2)
    z = stereo.depth_from_disparity(d, 1000.0, 0.2)
    assert abs(z - 20.0) < 1e-9


def test_nonpositive_disparity_is_inf():
    assert np.isinf(stereo.depth_from_disparity(0.0, 1000.0, 0.2))


def test_depth_uncertainty_grows_quadratically():
    s10 = stereo.depth_uncertainty_m(10.0, 1000.0, 0.2, 0.5)
    s20 = stereo.depth_uncertainty_m(20.0, 1000.0, 0.2, 0.5)
    assert abs(s20 / s10 - 4.0) < 1e-6   # Z^2 dependence


def test_vertical_parallax_baseline():
    assert abs(stereo.vertical_parallax_baseline_m(0.3, 0.9) - 0.6) < 1e-9


def test_triangulate_known_intersection():
    p = stereo.triangulate_bearings(np.array([0., 0, 0]), np.array([1., 0, 0]),
                                    np.array([2., 1, 0]), np.array([0., -1, 0]))
    assert np.allclose(p, [2., 0, 0], atol=1e-9)


def test_backproject():
    pt = stereo.backproject(512, 384, 10.0, 1000, 1000, 512, 384)
    assert np.allclose(pt, [0, 0, 10.0])
