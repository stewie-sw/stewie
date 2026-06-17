"""#145 perception egress: pack stereo world-points into a sensor_msgs/PointCloud2 for Nav2/Autoware.
``pack_xyz`` is pure + tested here; the live node + the upstream collect_world_points (a real render
egress) are gated on a ROS2 host / GPU render and run-verified on the container, not here.

Run: <venv>/bin/python -m pytest stewie/bridge/test_points_egress.py -q
"""
import struct

import pytest

from stewie.bridge import points_egress as PE


def test_pack_xyz_is_12_bytes_per_point_xyz_f32le():
    pts = [(1.0, 2.0, 3.0), (-4.5, 0.0, 7.25)]
    data = PE.pack_xyz(pts)
    assert len(data) == 2 * 12                              # PointCloud2 point_step
    assert struct.unpack("<fff", data[0:12]) == pytest.approx((1.0, 2.0, 3.0))
    assert struct.unpack("<fff", data[12:24]) == pytest.approx((-4.5, 0.0, 7.25))


def test_pack_xyz_empty_is_empty():
    assert PE.pack_xyz([]) == b""                           # an unobserved frame -> empty cloud, never fabricated


def test_points_node_gated_without_rclpy():
    try:
        import rclpy  # noqa: F401
    except ImportError:
        with pytest.raises(RuntimeError, match="rclpy|sensor_msgs"):
            PE.make_points_node(lambda: [])
