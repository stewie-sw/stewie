"""stewie_vehicle_interface (vehicle_interface) -- AS-02 Phase-1 skeleton node. Conforms to the AS-01 boundary contract
(stewie/bridge/autonomy_contract.py); full domain logic lands in the later AS phases. rclpy-optional so
the package imports on a non-ROS host (the live node needs the ROS2 container, AS-04)."""
ROLE = "vehicle_interface"
try:
    import rclpy
    from rclpy.node import Node
    _HAVE_RCLPY = True
except ImportError:                       # non-ROS host: import-safe, run-gated
    _HAVE_RCLPY = False
    Node = object


def main(args=None):
    if not _HAVE_RCLPY:
        raise SystemExit("stewie_vehicle_interface requires a ROS2 (rclpy) runtime -- run inside the ROS2 container (AS-04).")
    rclpy.init(args=args)
    node = Node("vehicle_interface")
    node.get_logger().info("stewie_vehicle_interface up (AS-02 skeleton; role=vehicle_interface)")
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
