"""Depth-truth ray-cast geometry."""
import numpy as np

from dart.depth_truth import camera_ray_world, raycast_range


def test_raycast_flat_ground_matches_geometry():
    """A camera at height h looking down at depression theta hits flat ground at range h/sin(theta)."""
    Z = np.zeros((300, 300), dtype="<f4")            # flat ground at y=0, cell 0.02 m -> 6 m patch
    cell = 0.02
    h = 1.0
    origin = np.array([3.0, h, 3.0])                 # 1 m up, mid-patch
    theta = np.radians(30.0)                          # look 30 deg below horizontal, +z
    direction = np.array([0.0, -np.sin(theta), np.cos(theta)])
    R = raycast_range(origin, direction, Z, cell, t_max=10, step=0.005)
    assert R is not None
    assert abs(R - h / np.sin(theta)) < 0.05         # h/sin(theta) = 2.0 m


def test_camera_ray_points_into_scene():
    o, d = camera_ray_world(512, 600, fx=679.57, fy=679.57, cx=512, cy=384,
                            cam_pos=[2.86, 0.1, 2.6], cam_quat=[0.0, -0.7071, 0.0, 0.7071])
    assert abs(np.linalg.norm(d) - 1.0) < 1e-6        # unit ray
