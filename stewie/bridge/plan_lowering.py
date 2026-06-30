"""NV-11: lower a plan IR (``lode.planner_views.plan_ir``) to ROS2-shaped messages a Space ROS / Nav2 /
MoveIt executive consumes.

PURE translation -- rclpy-OPTIONAL, the same pattern as ``ros2_bridge`` (``twist_to_command`` /
``pose_to_odom``): the function returns plain message-shaped dicts, fully testable without ROS2; the live
node turns them into real ``nav_msgs`` / ``geometry_msgs`` messages. Frame convention matches the bridge:
``frame_id=map``, REP-103 surface frame (col->x, row->-y, z-up yaw) -- the planner ORDER-frame (x,y) is
converted via frames.local_xy_to_rep103 at the seam (#308), so a lowered goal shares ONE frame with
pose_to_odom (NOT the prior row->+y, which mirrored every goal across the x-axis from the rover's odometry).

Space ROS is a HARDENED, API-compatible distribution of ROS 2 (NPR-7150.2-aligned: memory safety,
deterministic performance, static analysis) -- so the standard ``nav_msgs/Path`` + ``geometry_msgs/
PoseStamped`` + action-goal shapes emitted here are exactly what a Space ROS executive consumes; no
Space-ROS-specific message types are required at this seam.

Emits, from the IR's typed actions:
  - ``GoTo``                                   -> a ``nav_msgs/Path`` (waypoint polyline) + a
                                                  ``geometry_msgs/PoseStamped`` motion goal;
  - ``Excavate`` / ``CutHaulFill`` / ``Import`` / ``Sinter`` -> an arm/drum action goal (op, site, dest,
                                                  mass, expected energy/duration);
  - ``Observe`` (when the IR carries one)      -> an observation goal;
  - a blocked ``GoTo`` (``reached`` False) or an infeasible plan -> a replan event.

AM-01 (posture) is consumed here: every action declares the posture the executive must hold (``posture`` on
its goal) and a ``stewie.specs.posture_machine.PostureMachine`` is driven through the action sequence, so the
``posture_plan`` carries the ordered, FSM-legal posture transitions (inserting TRANSIT / the BRAKED_HOLD safe
stance where a direct transition is illegal). This is the posture FSM's product-path consumer; only structural
transition legality is enforced at this seam (the per-posture stability margin is the gated Q geometry tier).
"""
from __future__ import annotations

from stewie.bridge import frames as FR              # #308: THE frame conversion site (planner-local -> REP-103)
from stewie.specs import posture_machine as PM

_WORK_OPS = ("Excavate", "CutHaulFill", "Import", "Sinter")

#: the posture each lowered action requires the executive to hold (AM-01 product-path consumer). Driving =
#: TRANSIT; an observation is a raised MEERKAT vantage; excavation/haul-cut work DIGs; importing/placing
#: material DUMPs. Composite ops (CutHaulFill) declare their PRIMARY working posture (the cut); the FSM only
#: enforces structural transition legality here -- the per-posture stability MARGIN is the gated Q tier and
#: is supplied by the on-host posture geometry, not this seam.
_OP_POSTURE = {
    "GoTo": PM.TRANSIT,
    "Excavate": PM.DIG,
    "CutHaulFill": PM.DIG,
    "Import": PM.DUMP_Z,
    "Sinter": PM.DIG,
    "Observe": PM.MEERKAT,
}


def _pose_stamped(x: float, y: float, frame_id: str) -> dict:
    """A geometry_msgs/PoseStamped-shaped dict (flat surface: z=0, identity orientation)."""
    return {"header": {"frame_id": frame_id},
            "pose": {"position": {"x": float(x), "y": float(y), "z": 0.0},
                     "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}


def _drive_to(machine: PM.PostureMachine, target: str) -> list:
    """Step ``machine`` from its current posture to ``target`` using ONLY legal FSM transitions, inserting
    the minimal legal intermediate when a direct transition is illegal. Returns the ordered postures
    actually entered ([] if already there). The universal fallback (BRAKED_HOLD -> TRANSIT -> target) always
    succeeds for the reachable work/observe/drive postures, since BRAKED_HOLD (the SF-01 safe stop) is
    reachable from every state and TRANSIT is reachable from BRAKED_HOLD."""
    if machine.state == target:
        return []
    if machine.transition(target):                       # direct legal transition
        return [target]
    entered: list = []
    if machine.state != PM.TRANSIT and machine.transition(PM.TRANSIT):   # via the mobile TRANSIT hub
        entered.append(PM.TRANSIT)
        if machine.transition(target):
            entered.append(target)
            return entered
    machine.safe_stop()                                  # universal safe path: BRAKED_HOLD -> TRANSIT -> target
    entered.append(PM.BRAKED_HOLD)
    if machine.transition(PM.TRANSIT):
        entered.append(PM.TRANSIT)
    if machine.transition(target):
        entered.append(target)
    return entered


def lower_plan_ir(ir: dict, *, frame_id: str = "map") -> dict:
    """Lower a plan IR to ROS2-shaped command messages. Returns a dict with ``paths`` (nav_msgs/Path per
    GoTo), ``motion_goals`` (PoseStamped per GoTo), ``work_goals`` (arm/drum goals per work op),
    ``observation_goals``, and ``replan_events`` (blocked legs + an infeasible-plan event), carrying the
    deterministic ``plan_id`` + IR ``schema_version`` so an executive can correlate to the source plan."""
    actions = ir.get("actions", []) or []
    paths: list = []
    motion_goals: list = []
    work_goals: list = []
    observation_goals: list = []
    replan_events: list = []
    posture_plan: list = []
    machine = PM.PostureMachine()                          # starts at BRAKED_HOLD (the SF-01 safe stance)
    for a in actions:
        op = a.get("op")
        veh = int(a.get("vehicle", 0))
        goal: dict | None = None
        if op == "GoTo":
            wps = a.get("waypoints") or []
            # #308: the IR waypoints/goal are in the planner ORDER frame (y=+row); convert to the REP-103
            # map frame (y=-row, FR.local_xy_to_rep103) so a lowered goal shares ONE frame with the rover's
            # odometry (pose_to_odom). Previously emitted verbatim -> every goal mirrored across the x-axis.
            paths.append({"header": {"frame_id": frame_id}, "action_id": a.get("id"), "vehicle": veh,
                          "poses": [_pose_stamped(*FR.local_xy_to_rep103(p[0], p[1]), frame_id) for p in wps]})
            to = a.get("to")
            if to is not None:
                goal = _pose_stamped(*FR.local_xy_to_rep103(to[0], to[1]), frame_id)
                goal["action_id"] = a.get("id")
                goal["vehicle"] = veh
                motion_goals.append(goal)
            if a.get("reached") is False:                  # a blocked leg -> the executive must replan
                replan_events.append({"action_id": a.get("id"), "vehicle": veh,
                                      "reason": "leg_unreachable", "to": to})
        elif op in _WORK_OPS:                              # arm/drum goal (excavation / haul-fill / import / sinter)
            goal = {"action_id": a.get("id"), "op": op, "vehicle": veh,
                    "site": a.get("site"), "dest": a.get("dest"),
                    "mass_kg": a.get("mass_kg"), "haul_m": a.get("haul_m"),
                    "expect": a.get("expect")}
            work_goals.append(goal)
        elif op == "Observe":                              # observation action (lowered when the IR carries one)
            goal = {"action_id": a.get("id"), "op": "Observe", "vehicle": veh,
                    "at": a.get("to") or a.get("site")}
            observation_goals.append(goal)
        # AM-01: declare the posture the executive must hold for this action and realize it through the FSM
        target = _OP_POSTURE.get(op)
        if target is not None:
            entered = _drive_to(machine, target)
            posture_plan.append({"action_id": a.get("id"), "op": op, "target_posture": target,
                                 "entered": entered})
            if goal is not None:
                goal["posture"] = target
    if ir.get("feasible") is False:                        # the plan itself is infeasible -> replan
        replan_events.append({"reason": "plan_infeasible", "blocked_legs": int(ir.get("blocked_legs", 0) or 0)})
    return {"plan_id": ir.get("plan_id"), "ir_version": ir.get("schema_version"), "frame_id": frame_id,
            "paths": paths, "motion_goals": motion_goals, "work_goals": work_goals,
            "observation_goals": observation_goals, "replan_events": replan_events,
            "posture_plan": posture_plan}
