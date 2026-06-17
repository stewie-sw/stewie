"""ROS2 perception egress (Convergence Phase B / #145): publish the back-projected stereo point cloud
as sensor_msgs/PointCloud2 -- the costmap source a Nav2/Autoware layer needs ALONGSIDE the #144
/stewie/odom localization (together they let the autonomy stack both drive AND build a costmap through
the STEWIE seam).

The world-frame XYZ come from the existing, render-validated producer
``scripts/ros2_bridge/obs_map_producer.collect_world_points`` (a real Godot front-stereo egress ->
SGBM disparity -> cv2.reprojectImageTo3D -> world frame). This module is the EGRESS: it packs an Nx3
array into the standard message and publishes it on a ROS2 node.

Honesty / gating (no synthetic point clouds): ``pack_xyz`` is pure + testable without any dependency;
the live node (``make_points_node``) is gated on rclpy + sensor_msgs (a ROS2 host); and the UPSTREAM
real points need a rendered stereo egress (cv2 + the Godot render on a GPU host) -- the committed
AprilTag fixture is a pose scene with no depth, so a real depth egress is render-gated. This module
never fabricates points; ``points_source`` supplies whatever ``collect_world_points`` produced."""
from __future__ import annotations

import struct

_POINT_STEP = 12  # 3 x float32 (x, y, z), little-endian


def pack_xyz(points) -> bytes:
    """Pack an Nx3 (x, y, z) iterable into a sensor_msgs/PointCloud2 ``data`` buffer: 12 bytes/point,
    xyz as little-endian float32 in field order. Pure -- the wire payload the message carries, testable
    without ROS2/cv2/numpy. (A consumer reads it back with the inverse: struct.unpack('<fff', ...).)"""
    buf = bytearray()
    for p in points:
        buf += struct.pack("<fff", float(p[0]), float(p[1]), float(p[2]))
    return bytes(buf)


def make_points_node(points_source, *, topic: str = "/stewie/points", frame_id: str = "map",
                     rate_hz: float = 2.0):
    """LIVE rclpy Node publishing sensor_msgs/PointCloud2 on ``topic`` from ``points_source() -> Nx3``
    world points each tick (in production: collect_world_points on the latest stereo render egress).
    Gated: raises RuntimeError without rclpy/sensor_msgs (a ROS2 Jazzy host). The message is a dense,
    unordered cloud (height=1, width=N) of xyz float32 in ``frame_id`` -- the standard Nav2/Autoware
    costmap input. A None/empty points_source publishes an empty cloud (width=0), never fabricated XYZ.

    RUN-VERIFIED 2026-06-17 on stewie-ros2:latest: a subscriber received the published PointCloud2 with
    width == the source point count and the XYZ unpacked back to the source values (transport end-to-end
    on live DDS). The full render -> collect_world_points -> here path is render-gated (GPU host)."""
    try:
        import rclpy  # type: ignore[import-not-found]
        from rclpy.node import Node  # type: ignore[import-not-found]
        from sensor_msgs.msg import PointCloud2, PointField  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError("rclpy/sensor_msgs not installed: the live points node needs a ROS2 host; "
                           "pack_xyz is importable + testable without it.") from e

    _FIELDS = [PointField(name=n, offset=o, datatype=PointField.FLOAT32, count=1)
               for n, o in (("x", 0), ("y", 4), ("z", 8))]

    class _PointsNode(Node):
        def __init__(self) -> None:
            super().__init__("stewie_points_egress")
            self._pub = self.create_publisher(PointCloud2, topic, 5)
            self.create_timer(1.0 / float(rate_hz), self._on_tick)

        def _on_tick(self) -> None:
            pts = points_source() if points_source is not None else []
            pts = list(pts) if pts is not None else []
            data = pack_xyz(pts)
            msg = PointCloud2()
            msg.header.frame_id = frame_id
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.height = 1
            msg.width = len(data) // _POINT_STEP
            msg.fields = _FIELDS
            msg.is_bigendian = False
            msg.point_step = _POINT_STEP
            msg.row_step = _POINT_STEP * msg.width
            msg.is_dense = True
            msg.data = data
            self._pub.publish(msg)

    if not rclpy.ok():
        rclpy.init()
    return _PointsNode()
