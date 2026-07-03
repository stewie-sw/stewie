"""stewie_localization (localization) -- [REQ:AS-09] publishes the standstill-relocalization factors as an
RViz MarkerArray so accepted articulation-parallax fixes are visible in RViz (they are already in the
cockpit via navplot). The pure `RelocMarkers` core turns ACCEPTED factors (matched landmark points + the
reduced posterior covariance from dart.relocalization.standstill_fix) into MarkerArray-shaped markers;
REJECTED factors produce NO markers (they are not inserted into the pose graph, so they must not appear as
accepted evidence). rclpy-optional: host-testable; the live node needs the ROS2 container (AS-04)."""
from __future__ import annotations

import math

import numpy as np

ROLE = "localization"
RELOC_MARKERS_TOPIC = "/stewie/localization/relocalization_markers"

try:
    import rclpy
    from rclpy.node import Node
    _HAVE_RCLPY = True
except ImportError:                       # non-ROS host: import-safe, run-gated
    _HAVE_RCLPY = False
    Node = object


def _cov_ellipse(cov) -> tuple[float, float, float]:
    """1-sigma ellipse (semi-axis x, semi-axis y, yaw rad) of a 2x2 covariance -- eigen-decomposition."""
    c = np.asarray(cov, dtype=float).reshape(2, 2)
    vals, vecs = np.linalg.eigh(c)
    vals = np.clip(vals, 0.0, None)
    yaw = float(math.atan2(vecs[1, np.argmax(vals)], vecs[0, np.argmax(vals)]))
    return float(math.sqrt(vals[1])), float(math.sqrt(vals[0])), yaw


class RelocMarkers:
    """[REQ:AS-09] Turn accepted standstill relocalization factors into RViz MarkerArray-shaped markers."""

    @staticmethod
    def factors_to_markers(fixes, *, frame_id: str = "map") -> list[dict]:
        """For each ACCEPTED fix: a SPHERE_LIST of the matched landmark points + a CYLINDER 1-sigma
        covariance ellipse at the fix position. Rejected fixes -> nothing (the graph-insertion contract)."""
        markers: list[dict] = []
        mid = 0
        for f in fixes:
            if not f.get("accepted"):
                continue
            lm = [(float(x), float(y), 0.0) for x, y in f["landmarks_xy"]]
            markers.append({"id": mid, "ns": "reloc_landmarks", "type": "SPHERE_LIST", "frame_id": frame_id,
                            "points": lm, "scale": 0.3, "color": (0.1, 0.9, 0.2, 1.0)})
            mid += 1
            sx, sy, yaw = _cov_ellipse(f["cov_post"])
            px, py = f["position_xy"]
            markers.append({"id": mid, "ns": "reloc_covariance", "type": "CYLINDER", "frame_id": frame_id,
                            "position": (float(px), float(py), 0.0),
                            "scale": (max(2.0 * sx, 1e-3), max(2.0 * sy, 1e-3), 0.05),
                            "yaw": yaw, "color": (0.2, 0.6, 1.0, 0.5)})
            mid += 1
        return markers


def _to_marker_msg(m: dict):
    from geometry_msgs.msg import Point
    from visualization_msgs.msg import Marker
    msg = Marker()
    msg.header.frame_id = m["frame_id"]
    msg.ns, msg.id = m["ns"], m["id"]
    msg.type = getattr(Marker, m["type"])
    msg.action = Marker.ADD
    r, g, b, a = m["color"]
    msg.color.r, msg.color.g, msg.color.b, msg.color.a = r, g, b, a
    if m["type"] == "SPHERE_LIST":
        msg.scale.x = msg.scale.y = msg.scale.z = m["scale"]
        msg.points = [Point(x=p[0], y=p[1], z=p[2]) for p in m["points"]]
    else:
        msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = m["position"]
        yaw = m["yaw"]
        msg.pose.orientation.z, msg.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        msg.scale.x, msg.scale.y, msg.scale.z = m["scale"]
    return msg


def main(args=None):
    if not _HAVE_RCLPY:
        raise SystemExit("stewie_localization requires a ROS2 (rclpy) runtime -- run inside the ROS2 container (AS-04).")
    from visualization_msgs.msg import MarkerArray

    rclpy.init(args=args)
    node = Node("localization")
    pub = node.create_publisher(MarkerArray, RELOC_MARKERS_TOPIC, 10)
    node._reloc_pub = pub                      # noqa: SLF001 -- exposed for introspection

    def publish_factors(fixes) -> int:
        arr = MarkerArray()
        arr.markers = [_to_marker_msg(m) for m in RelocMarkers.factors_to_markers(fixes)]
        pub.publish(arr)
        return len(arr.markers)

    node.publish_factors = publish_factors      # the relocalization pipeline calls this on each accepted fix
    node.get_logger().info(
        f"stewie_localization up (AS-09; role=localization); publishing relocalization factors on {RELOC_MARKERS_TOPIC}")
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
