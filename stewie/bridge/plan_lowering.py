"""NV-11: lower a plan IR (``lode.planner_views.plan_ir``) to ROS2-shaped messages a Space ROS / Nav2 /
MoveIt executive consumes.

PURE translation -- rclpy-OPTIONAL, the same pattern as ``ros2_bridge`` (``twist_to_command`` /
``pose_to_odom``): the function returns plain message-shaped dicts, fully testable without ROS2; the live
node turns them into real ``nav_msgs`` / ``geometry_msgs`` messages. Frame convention matches the bridge:
``frame_id=map``, ground plane with position col->x, row->y (REP-103 surface frame, z-up yaw).

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
"""
from __future__ import annotations

_WORK_OPS = ("Excavate", "CutHaulFill", "Import", "Sinter")


def _pose_stamped(x: float, y: float, frame_id: str) -> dict:
    """A geometry_msgs/PoseStamped-shaped dict (flat surface: z=0, identity orientation)."""
    return {"header": {"frame_id": frame_id},
            "pose": {"position": {"x": float(x), "y": float(y), "z": 0.0},
                     "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}}


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
    for a in actions:
        op = a.get("op")
        veh = int(a.get("vehicle", 0))
        if op == "GoTo":
            wps = a.get("waypoints") or []
            paths.append({"header": {"frame_id": frame_id}, "action_id": a.get("id"), "vehicle": veh,
                          "poses": [_pose_stamped(p[0], p[1], frame_id) for p in wps]})
            to = a.get("to")
            if to is not None:
                g = _pose_stamped(to[0], to[1], frame_id)
                g["action_id"] = a.get("id")
                g["vehicle"] = veh
                motion_goals.append(g)
            if a.get("reached") is False:                  # a blocked leg -> the executive must replan
                replan_events.append({"action_id": a.get("id"), "vehicle": veh,
                                      "reason": "leg_unreachable", "to": to})
        elif op in _WORK_OPS:                              # arm/drum goal (excavation / haul-fill / import / sinter)
            work_goals.append({"action_id": a.get("id"), "op": op, "vehicle": veh,
                               "site": a.get("site"), "dest": a.get("dest"),
                               "mass_kg": a.get("mass_kg"), "haul_m": a.get("haul_m"),
                               "expect": a.get("expect")})
        elif op == "Observe":                              # observation action (lowered when the IR carries one)
            observation_goals.append({"action_id": a.get("id"), "op": "Observe", "vehicle": veh,
                                      "at": a.get("to") or a.get("site")})
    if ir.get("feasible") is False:                        # the plan itself is infeasible -> replan
        replan_events.append({"reason": "plan_infeasible", "blocked_legs": int(ir.get("blocked_legs", 0) or 0)})
    return {"plan_id": ir.get("plan_id"), "ir_version": ir.get("schema_version"), "frame_id": frame_id,
            "paths": paths, "motion_goals": motion_goals, "work_goals": work_goals,
            "observation_goals": observation_goals, "replan_events": replan_events}
