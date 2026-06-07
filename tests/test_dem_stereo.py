import os

import numpy as np
import pytest

from solnav.geometry import dem
from solnav.perception import stereo_depth

HERE = os.path.dirname(__file__)
DEM_DIR = os.path.join(HERE, "fixtures", "dem")        # committed REAL Haworth subsample
PAIR = os.path.join(HERE, "fixtures", "frame")         # committed REAL stereo crops
_dem = os.path.isdir(DEM_DIR)
_pair = os.path.exists(PAIR + "/front_left.png")


# ---- stereo depth (pure + real) ----
def test_disparity_to_depth_known():
    z = stereo_depth.disparity_to_depth(np.array([[10.0, 0.0]]), 1000.0, 0.2)
    assert abs(z[0, 0] - 20.0) < 1e-9 and np.isnan(z[0, 1])


def test_pointcloud_shape():
    depth = np.full((20, 20), 5.0)
    pc = stereo_depth.depth_pointcloud(depth, 100, 100, 10, 10, stride=2)
    assert pc.shape[1] == 3 and pc.shape[0] == 100


@pytest.mark.skipif(not _pair, reason="rendered stereo pair not present")
def test_real_stereo_produces_some_depth():
    from imageio.v3 import imread
    L = np.asarray(imread(PAIR + "/front_left.png"))
    R = np.asarray(imread(PAIR + "/front_right.png"))
    disp = stereo_depth.compute_disparity(L, R)
    vf = stereo_depth.valid_fraction(disp)
    # honestly low on low-texture lunar imagery, but nonzero
    assert 0.0 < vf < 0.6


# ---- DEM (real Haworth) ----
@pytest.mark.skipif(not _dem, reason="Haworth DEM not present")
def test_load_and_crop_real_dem():
    H, posting, meta = dem.load_dem(DEM_DIR)
    assert H.shape[0] == H.shape[1] >= 40       # committed 60x60 real subsample
    patch, origin, n = dem.crop_meters(H, posting, 100.0)
    assert n == round(100.0 / posting) and patch.shape == (n, n)


@pytest.mark.skipif(not _dem, reason="Haworth DEM not present")
def test_register_recovers_known_shift():
    H, posting, _ = dem.load_dem(DEM_DIR)
    patch, _, _ = dem.crop_meters(H, posting, 120.0)
    sub = patch[4:-4, 4:-4]
    shifted = np.roll(np.roll(patch, 2, 0), -1, 1)
    dr, dc, rmse = dem.register_to_dem(sub, shifted, search_radius_cells=5)
    assert (dr, dc) == (2, -1) and rmse < 1e-6
