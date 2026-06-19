"""[REQ:AS-01] / [REQ:AS-15] — the frozen STEWIE-native autonomy boundary contract (§25 Phase 0).

This is the single authoritative definition of the ROS2 autonomy seam that AS-02..AS-17 must conform to.
It is Autoware-SHAPED — sensing -> perception -> localization -> mapping -> planning -> control ->
vehicle_interface, plus diagnostics and a mission_executive — but it deliberately carries NO road/lanelet
behavior planning (no lanelet2, route, traffic-light, crosswalk, behavior-velocity modules). It freezes:
the node graph (roles + pub/sub), the topic contract (names + types + QoS class), REP-103 frame names,
node lifecycle, command authority (AG-08 + SF-01), the SAFE path, and the TRUTH-DENIAL policy (estimator
nodes may never subscribe an evaluation-truth topic).

PURE DATA + a validator. No rclpy import: the live runtime is container-gated (AS-02/AS-04). This module
+ its test ARE the Phase-0 gate — `validate_contract()` must reject a missing node/topic, a road/lanelet
dependency, and a truth-topic input to an estimator node. Grounded in the existing seam: the `/cmd_vel`
(Twist) ingress + `/stewie/odom` (Odometry) egress (ros2_bridge.py), the truth/runtime channel split
(sensor_io._FORBIDDEN_RUNTIME_KEYS), and the SF-01 SAFE reasons (rc_contract.SAFE_REASON_*).
"""
from __future__ import annotations

from dataclasses import dataclass

# REP-103 frames (right-handed, x-forward / z-up). The estimator chain is map -> odom -> base_link.
FRAMES = ("map", "odom", "base_link", "imu_link",
          "camera_front_left", "camera_front_right", "camera_rear_left", "camera_rear_right")

# Evaluation-truth topics: published only on the truth channel, NEVER subscribable by an estimator node
# (the ROS2 expression of sensor_io's runtime/truth split). A node in an ESTIMATOR_ROLE that lists any of
# these as a subscription is a truth-denial violation.
TRUTH_TOPICS = ("/stewie/truth/pose", "/stewie/truth/dem", "/stewie/truth/clasts",
                "/stewie/truth/excavation")

# Autoware road/behavior modules that must NOT appear as a node role or dependency (STEWIE is off-road
# surface autonomy; importing lanelet/route/traffic behavior would drag in road semantics we reject).
FORBIDDEN_DEPENDENCIES = ("lanelet2", "autoware_behavior_velocity_planner", "autoware_route_planning",
                          "mission_planner_lanelet", "traffic_light", "crosswalk", "behavior_path_planner")

ESTIMATOR_ROLES = frozenset({"perception", "localization", "mapping"})

# QoS classes (the expectation, not a live profile): sensor = best-effort/volatile; command/state =
# reliable/transient-local; default = reliable/volatile.
QOS_SENSOR, QOS_COMMAND, QOS_STATE, QOS_DEFAULT = "sensor", "command", "state", "default"


@dataclass(frozen=True)
class Topic:
    name: str
    msg: str                 # ROS2 message type (shape contract; the concrete .msg lands in AS-02 stewie_msgs)
    qos: str = QOS_DEFAULT


@dataclass(frozen=True)
class Node:
    name: str
    role: str                # sensing|perception|localization|mapping|planning|control|vehicle_interface|diagnostics|mission_executive
    publishes: tuple = ()
    subscribes: tuple = ()
    lifecycle: bool = True    # managed lifecycle node (configure/activate/deactivate)
    dependencies: tuple = ()  # ROS package deps (checked against FORBIDDEN_DEPENDENCIES)


# Command topics: the actuation seam. Emission is gated (AG-08 live-namespace + operator+ + SF-01); the
# bridge already enforces this (rc_contract.SafingWatchdog + routers/rc.py). Listed so the contract test
# asserts they exist + are gated.
COMMAND_TOPICS = ("/cmd_vel", "/stewie/plan/action_goal")
SAFE_STATE_TOPIC = "/stewie/safe_state"

TOPICS: dict[str, Topic] = {t.name: t for t in (
    Topic("/clock", "rosgraph_msgs/Clock", QOS_SENSOR),
    Topic("/tf", "tf2_msgs/TFMessage", QOS_DEFAULT),
    Topic("/tf_static", "tf2_msgs/TFMessage", QOS_STATE),
    Topic("/joint_states", "sensor_msgs/JointState", QOS_SENSOR),
    Topic("/stewie/imu", "sensor_msgs/Imu", QOS_SENSOR),
    Topic("/stewie/wheel_odom", "nav_msgs/Odometry", QOS_SENSOR),
    Topic("/stewie/camera/front_left/image", "sensor_msgs/Image", QOS_SENSOR),
    Topic("/stewie/camera/front_right/image", "sensor_msgs/Image", QOS_SENSOR),
    Topic("/stewie/perception/points", "sensor_msgs/PointCloud2", QOS_SENSOR),
    Topic("/stewie/perception/rocks", "stewie_msgs/RockArray", QOS_DEFAULT),
    Topic("/stewie/odom", "nav_msgs/Odometry", QOS_DEFAULT),
    Topic("/stewie/argus/factors", "stewie_msgs/ArgusFactorArray", QOS_DEFAULT),
    Topic("/stewie/localization/cov", "geometry_msgs/PoseWithCovarianceStamped", QOS_DEFAULT),
    Topic("/stewie/map/dem", "grid_map_msgs/GridMap", QOS_STATE),
    Topic("/stewie/map/occupancy", "nav_msgs/OccupancyGrid", QOS_STATE),
    Topic("/stewie/map/excavation_state", "grid_map_msgs/GridMap", QOS_STATE),
    Topic("/stewie/costmap", "nav_msgs/OccupancyGrid", QOS_STATE),
    Topic("/stewie/plan/path", "nav_msgs/Path", QOS_DEFAULT),
    Topic("/stewie/plan/local_traj", "stewie_msgs/Trajectory", QOS_DEFAULT),
    Topic("/stewie/plan/action_goal", "stewie_msgs/WorkGoal", QOS_COMMAND),
    Topic("/cmd_vel", "geometry_msgs/Twist", QOS_COMMAND),
    Topic("/diagnostics", "diagnostic_msgs/DiagnosticArray", QOS_DEFAULT),
    Topic(SAFE_STATE_TOPIC, "stewie_msgs/SafeState", QOS_STATE),
    Topic("/stewie/exec/decision", "stewie_msgs/ExecutiveDecision", QOS_DEFAULT),
)}

NODES: dict[str, Node] = {n.name: n for n in (
    Node("sensing", "sensing",
         publishes=("/clock", "/tf", "/tf_static", "/joint_states", "/stewie/imu", "/stewie/wheel_odom",
                    "/stewie/camera/front_left/image", "/stewie/camera/front_right/image")),
    Node("perception", "perception",
         subscribes=("/stewie/camera/front_left/image", "/stewie/camera/front_right/image"),
         publishes=("/stewie/perception/points", "/stewie/perception/rocks")),
    Node("localization", "localization",
         subscribes=("/stewie/wheel_odom", "/stewie/imu", "/stewie/perception/points", "/tf"),
         publishes=("/stewie/odom", "/stewie/argus/factors", "/stewie/localization/cov")),
    Node("mapping", "mapping",
         subscribes=("/stewie/perception/points", "/stewie/perception/rocks", "/stewie/odom"),
         publishes=("/stewie/map/dem", "/stewie/map/occupancy", "/stewie/map/excavation_state")),
    Node("planning", "planning",
         subscribes=("/stewie/map/dem", "/stewie/map/occupancy", "/stewie/costmap", "/stewie/odom"),
         publishes=("/stewie/plan/path", "/stewie/plan/local_traj", "/stewie/costmap")),
    Node("control", "control",
         subscribes=("/stewie/plan/local_traj", "/stewie/odom"),
         publishes=("/cmd_vel",)),
    Node("vehicle_interface", "vehicle_interface",
         subscribes=("/cmd_vel",), publishes=("/stewie/odom",)),
    Node("diagnostics", "diagnostics",
         subscribes=("/diagnostics",), publishes=(SAFE_STATE_TOPIC,), lifecycle=False),
    Node("mission_executive", "mission_executive",
         subscribes=("/stewie/odom", "/stewie/localization/cov", "/diagnostics", "/stewie/map/dem"),
         publishes=("/stewie/exec/decision", "/stewie/plan/action_goal", SAFE_STATE_TOPIC)),
)}

REQUIRED_ROLES = ("sensing", "perception", "localization", "mapping", "planning", "control",
                  "vehicle_interface", "diagnostics", "mission_executive")


def validate_contract(nodes: dict | None = None, topics: dict | None = None) -> list[str]:
    """Return a list of contract violations (empty = the boundary is well-formed). The Phase-0 gate.

    Checks: (1) every required Autoware-shaped role has a node; (2) NO node depends on a forbidden
    road/lanelet/behavior module; (3) NO estimator-role node subscribes an evaluation-truth topic
    (truth-denial); (4) the command + SAFE topics exist and the command topics are QoS_COMMAND-classed;
    (5) the topic graph is closed (every pub/sub names a defined topic); (6) REP-103 map/odom/base_link
    frames are present.
    """
    nodes = NODES if nodes is None else nodes
    topics = TOPICS if topics is None else topics
    errs: list[str] = []

    roles = {n.role for n in nodes.values()}
    for r in REQUIRED_ROLES:
        if r not in roles:
            errs.append(f"missing required node role: {r}")

    for n in nodes.values():
        for dep in n.dependencies:
            if any(bad in dep for bad in FORBIDDEN_DEPENDENCIES):
                errs.append(f"node {n.name!r} pulls a forbidden road/lanelet dependency: {dep!r}")
        if n.role in ESTIMATOR_ROLES:
            for sub in n.subscribes:
                if sub in TRUTH_TOPICS:
                    errs.append(f"truth-denial violation: estimator node {n.name!r} subscribes truth topic {sub!r}")
        for t in (*n.publishes, *n.subscribes):
            if t not in topics:
                errs.append(f"node {n.name!r} references undefined topic {t!r}")

    for ct in COMMAND_TOPICS:
        if ct not in topics:
            errs.append(f"missing command topic: {ct}")
        elif topics[ct].qos != QOS_COMMAND:
            errs.append(f"command topic {ct} must be QoS_COMMAND (got {topics[ct].qos})")
    if SAFE_STATE_TOPIC not in topics:
        errs.append("missing SAFE-state topic")
    if not any(SAFE_STATE_TOPIC in n.publishes for n in nodes.values()):
        errs.append("no node publishes the SAFE-state topic")

    for f in ("map", "odom", "base_link"):
        if f not in FRAMES:
            errs.append(f"missing REP-103 frame: {f}")
    return errs
