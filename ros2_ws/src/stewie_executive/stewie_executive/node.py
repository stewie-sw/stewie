"""stewie_executive (mission_executive) -- AS-13 Phase-11 skeleton node. Conforms to the AS-01 boundary
contract (stewie/bridge/autonomy_contract.py): it monitors the rover's preconditions, acknowledgements,
localization covariance, resource reservations, faults, acceptance state, and safing, then emits a
continue|pause|replan|relocalize|reverse|safe decision on /stewie/exec/decision. The decision precedence
lives ONCE in lode.executive (executive_step / to_executive_decision); this node is the ROS2 seam around
it, not a re-derivation. rclpy-optional so the package imports on a non-ROS host (the live spin + real
topic subscriptions need the ROS2 container, AS-04)."""
from stewie.bridge.autonomy_contract import NODES
from lode.executive import executive_step, to_executive_decision

ROLE = "mission_executive"
# Pull the pub/sub sets straight from the frozen contract so the node can never drift from AS-01.
SUBSCRIBES = NODES[ROLE].subscribes
PUBLISHES = NODES[ROLE].publishes

try:
    import rclpy
    from rclpy.node import Node
    _HAVE_RCLPY = True
except ImportError:                       # non-ROS host: import-safe, run-gated
    _HAVE_RCLPY = False
    Node = object


def decide(**signals) -> dict:
    """Map the monitored signals to an ExecutiveDecision (decision, reason) via the shared precedence
    ladder in lode.executive -- so the ROS seam and the host-side gate agree by construction. Accepts the
    same keyword signals as lode.executive.executive_step (faults, command_acked, plan_accepted,
    covariance_ok, reservation_conflict, recovery, reactive)."""
    return to_executive_decision(executive_step(**signals))


def main(args=None):
    if not _HAVE_RCLPY:
        raise SystemExit("stewie_executive requires a ROS2 (rclpy) runtime -- run inside the ROS2 container (AS-04).")
    rclpy.init(args=args)
    node = Node("mission_executive")
    node.get_logger().info("stewie_executive up (AS-13 skeleton; role=mission_executive)")
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
