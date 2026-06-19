"""stewie_mapping (mapping) -- AS-02 Phase-1 skeleton node. Conforms to the AS-01 boundary contract
(stewie/bridge/autonomy_contract.py); full domain logic lands in the later AS phases. rclpy-optional so
the package imports on a non-ROS host (the live node needs the ROS2 container, AS-04)."""
ROLE = "mapping"
try:
    import rclpy
    from rclpy.node import Node
    _HAVE_RCLPY = True
except ImportError:                       # non-ROS host: import-safe, run-gated
    _HAVE_RCLPY = False
    Node = object


def main(args=None):
    if not _HAVE_RCLPY:
        raise SystemExit("stewie_mapping requires a ROS2 (rclpy) runtime -- run inside the ROS2 container (AS-04).")
    rclpy.init(args=args)
    node = Node("mapping")
    node.get_logger().info("stewie_mapping up (AS-02 skeleton; role=mapping)")
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
