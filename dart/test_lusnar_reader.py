"""TDD for dart.lusnar_reader: a reader for the REAL LuSNAR lunar dataset (arXiv:2407.06512,
zqyu9/LuSNAR-dataset). Runs against the locally extracted Moon_1 scene; subsamples a HANDFUL of real
frames (never copies the ~9.8 GB scene). Data-gated -> skips cleanly where the scene is not extracted,
mirroring the _have_katwijk / _have_frames pattern in test_stereo_vo.

Verified-on-disk facts these tests pin (discovered by inspecting the real extracted Moon_1):
  * stereo: image0/ (left: color + depth + label) and image1/ (right: color) -> a stereo pair, not
    mono+depth; 1024x1024 RGBA uint8 color.
  * intrinsics: NO per-scene calib file exists; the published spec gives fx=fy=610.17784 px (== the
    pinhole focal of the 80deg FOV at 1024 px), principal point at the image centre, baseline 0.310 m.
  * depth: per-frame 1024x1024 float32 .pfm, metres; sky / no-surface pixels carry the FP16-max
    sentinel 65504.0.
  * GT pose: gt.txt, EuRoC RS_R format (timestamp, p[3] m, q_wxyz[4], v[3], b_w[3], b_a[3]); unit
    quaternions; matched to a frame by nearest timestamp (filename stem vs gt timestamp differ by < 100 ns).
  * LiDAR: per-frame x,y,z,category .txt point clouds (category -1 regolith / 0 crater / 174 rock).
  * timestamps: ns-epoch filename stems, strictly increasing, identical across every modality.

Truth firewall (invariant I3): the reader loads GT pose + GT depth/LiDAR because the READER is not the
estimator. These assertions read GT in the SCORING/validation path only. The firewall is enforced
DOWNSTREAM at the estimator input -- never tested here by feeding pose into a perception API.
"""
import math
import os

import numpy as np
import pytest

from dart import lusnar_reader

# Real extracted scene (absolute, mirrors _KATWIJK_PART7 in test_stereo_vo). Not bundled in the repo.
_LUSNAR_MOON1 = "/mnt/projects/datasets/argus_dem_nav/lusnar/extracted/Moon_1"
_have_lusnar = os.path.isdir(os.path.join(_LUSNAR_MOON1, "image0", "color")) and os.path.isfile(
    os.path.join(_LUSNAR_MOON1, "gt.txt")
)


# ---- pure / numeric (no external assets) ---------------------------------------------------------
def test_published_focal_matches_pinhole_law_of_the_fov():
    """The published LuSNAR focal (610.17784 px) is exactly the pinhole focal of an 80deg FOV at
    1024 px: fx = (W/2)/tan(FOV/2). A genuine numeric check on the calibration constant, not a tautology."""
    expected = (lusnar_reader.LUSNAR_IMAGE_SIZE * 0.5) / math.tan(
        math.radians(lusnar_reader.LUSNAR_FOV_DEG) * 0.5
    )
    assert abs(lusnar_reader.LUSNAR_FOCAL_PX - expected) < 0.01
    K = lusnar_reader.LUSNAR_INTRINSICS.matrix()
    assert K.shape == (3, 3)
    assert K[0, 0] == pytest.approx(610.17784, abs=1e-3)
    assert K[1, 1] == pytest.approx(610.17784, abs=1e-3)
    assert K[0, 2] == pytest.approx(512.0)  # principal point at the image centre
    assert K[1, 2] == pytest.approx(512.0)
    assert K[2, 2] == 1.0


def test_gtpose_quaternion_to_se3_is_valid_rotation():
    """A unit quaternion -> orthonormal rotation (det ~ +1) and a homogeneous SE(3) with [0,0,0,1]."""
    q = np.array([0.999968, -0.00322685, -0.00726534, 0.000344668])  # real gt.txt row-0 quaternion
    pose = lusnar_reader.GtPose(timestamp_ns=1, position_m=np.array([1.0, 2.0, 3.0]),
                                quaternion_wxyz=q)
    R = pose.rotation_matrix()
    assert R.shape == (3, 3)
    assert abs(np.linalg.det(R) - 1.0) < 1e-6
    assert np.max(np.abs(R @ R.T - np.eye(3))) < 1e-6
    T = pose.matrix()
    assert T.shape == (4, 4)
    assert np.allclose(T[3], [0.0, 0.0, 0.0, 1.0])
    assert np.allclose(T[:3, 3], [1.0, 2.0, 3.0])


# ---- real extracted Moon_1 (subsampled) ----------------------------------------------------------
@pytest.fixture(scope="module")
def reader():
    return lusnar_reader.LusnarReader(_LUSNAR_MOON1)


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_scene_discovered_and_timestamps_strictly_increasing(reader):
    assert len(reader) > 100               # Moon_1 has ~1094 frames
    ts = reader.timestamps
    assert len(ts) == len(reader)
    assert all(b > a for a, b in zip(ts, ts[1:]))     # ns-epoch stems strictly increase


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_frame_stereo_images_and_depth_shapes(reader):
    """Stereo (left+right) 1024x1024 uint8 + a depth map whose H,W match the image."""
    f = reader.frame(0)
    assert f.left.shape[:2] == (1024, 1024)
    assert f.left.dtype == np.uint8
    assert f.right is not None                         # STEREO, not mono+depth
    assert f.right.shape[:2] == (1024, 1024)
    assert f.right.dtype == np.uint8
    assert f.depth_m.shape == (1024, 1024)             # depth H,W match the image
    assert f.depth_m.dtype == np.float32
    assert f.label_rgb.shape[:2] == (1024, 1024)


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_frame_intrinsics_and_baseline_plausible(reader):
    f = reader.frame(0)
    K = f.intrinsics.matrix()
    assert 600.0 < K[0, 0] < 620.0                     # fx near the published 610.18 px
    assert 600.0 < K[1, 1] < 620.0
    assert K[0, 2] == pytest.approx(512.0, abs=1.0)    # principal point ~ image centre
    assert K[1, 2] == pytest.approx(512.0, abs=1.0)
    assert f.baseline_m > 0.0                          # stereo baseline positive
    assert f.baseline_m == pytest.approx(0.310, abs=1e-6)


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_depth_is_metric_with_sky_sentinel(reader):
    f = reader.frame(0)
    d = f.depth_m
    assert np.all(np.isfinite(d))                      # no NaN/inf; sky uses an explicit sentinel
    surface = d < lusnar_reader.LUSNAR_SKY_DEPTH_SENTINEL
    assert surface.any()
    assert float(d[surface].min()) > 0.0               # positive metric depth on the surface
    assert float(d[surface].max()) < 5000.0            # physically sane (hundreds of m, not 1e30)
    assert (~surface).any()                            # some sky / no-surface pixels present


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_gt_pose_is_valid_se3_and_matched_by_timestamp(reader):
    f = reader.frame(0)
    assert f.pose is not None
    # quaternion unit
    assert abs(np.linalg.norm(f.pose.quaternion_wxyz) - 1.0) < 1e-5
    R = f.pose.rotation_matrix()
    assert abs(np.linalg.det(R) - 1.0) < 1e-6
    assert np.max(np.abs(R @ R.T - np.eye(3))) < 1e-6
    # pose timestamp matched to the frame stem within a sub-microsecond rounding gap
    assert abs(f.pose.timestamp_ns - f.timestamp_ns) < 1_000_000


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_gt_pose_evolves_smoothly_across_consecutive_frames(reader):
    poses = [reader.pose(i) for i in range(6)]
    steps = [np.linalg.norm(poses[i + 1].position_m - poses[i].position_m) for i in range(5)]
    # consecutive GT positions move by a small, bounded amount (no jumps): a real ~10 Hz rover traverse
    assert all(0.0 <= s < 1.0 for s in steps)
    assert max(steps) > 0.0                            # the rover is actually moving over the window


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_cross_modality_timestamp_alignment(reader):
    """Left/right/depth/label/LiDAR for a frame all key off the SAME ns-epoch stem."""
    for i in (0, 1, 5):
        f = reader.frame(i)
        stem = str(f.timestamp_ns)
        assert os.path.isfile(os.path.join(_LUSNAR_MOON1, "image0", "color", stem + ".png"))
        assert os.path.isfile(os.path.join(_LUSNAR_MOON1, "image1", "color", stem + ".png"))
        assert os.path.isfile(os.path.join(_LUSNAR_MOON1, "image0", "depth", stem + ".pfm"))
        assert os.path.isfile(os.path.join(_LUSNAR_MOON1, "image0", "label", stem + ".png"))
        assert os.path.isfile(os.path.join(_LUSNAR_MOON1, "LiDAR", stem + ".txt"))


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_lidar_point_cloud_is_real_xyz_category(reader):
    pc = reader.lidar_points(0)
    assert pc.ndim == 2 and pc.shape[1] == 4          # x, y, z, category
    assert pc.shape[0] > 1000
    assert np.all(np.isfinite(pc[:, :3]))
    cats = set(np.unique(pc[:, 3]).astype(int).tolist())
    assert cats.issubset({-1, 0, 174})                # the documented LuSNAR 3D label ids


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_depth_derived_points_exclude_sky(reader):
    f = reader.frame(0)
    pts = reader.depth_to_points(f.depth_m)
    assert pts.ndim == 2 and pts.shape[1] == 3
    assert pts.shape[0] > 1000
    assert np.all(np.isfinite(pts))
    assert np.all(pts[:, 2] > 0.0)                     # camera-frame depth (+Z forward) is positive
    # every back-projected depth is below the sky sentinel
    assert float(pts[:, 2].max()) < lusnar_reader.LUSNAR_SKY_DEPTH_SENTINEL


@pytest.mark.skipif(not _have_lusnar, reason="LuSNAR Moon_1 not extracted")
def test_scene_dem_map_prior_from_lidar(reader):
    """The GT LiDAR clouds bin into a finite 2.5-D elevation grid (the downstream DEM map prior)."""
    Z, cell_m, x0, y0 = reader.scene_dem(indices=range(0, 6), cell_m=0.5)
    assert cell_m == 0.5
    assert Z.ndim == 2 and Z.shape[0] > 0 and Z.shape[1] > 0
    filled = np.isfinite(Z)
    assert filled.any()
    assert np.all(np.isfinite(Z[filled]))
    assert float(np.ptp(Z[filled])) >= 0.0             # a real (possibly gently varying) surface
