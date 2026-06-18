"""NV-11: lowering a plan IR to ROS2-shaped messages (paths / motion goals / arm-drum goals / observation
goals / replan events). The main path uses a REAL plan_ir from a real mission; the Observe + replan
branches are unit-tested with minimal IR action dicts (the rclpy-optional translation, like the bridge's
twist_to_command tests)."""
from lode import mission_planner as MP
from lode import planner_views as PV
from stewie.bridge.plan_lowering import lower_plan_ir


def _ir():
    m = MP.mission_from_dict({"name": "S", "body": "moon", "charger": [0, 0],
                              "orders": [{"action": "borrow", "kind": "cut", "x": 20.0, "y": 0.0,
                                          "footprint_m2": 16.0, "depth_m": 0.3},
                                         {"action": "pad", "kind": "fill", "x": 40.0, "y": 0.0,
                                          "footprint_m2": 16.0, "depth_m": 0.3}]})
    return PV.plan_ir(m)


def test_lowers_real_ir_to_paths_motion_and_work_goals():  # [REQ:NV-11]
    out = lower_plan_ir(_ir())
    # the real IR is GoTo, CutHaulFill, GoTo, Excavate -> 2 GoTo (paths+motion) + 2 work goals
    assert len(out["paths"]) == 2 and len(out["motion_goals"]) == 2
    assert {g["op"] for g in out["work_goals"]} == {"CutHaulFill", "Excavate"}
    assert out["plan_id"] and out["ir_version"]                  # correlates to the source plan
    assert out["replan_events"] == []                            # a feasible plan needs no replan


def test_path_and_goal_are_ros_shaped():
    out = lower_plan_ir(_ir())
    p = out["paths"][0]
    assert p["header"]["frame_id"] == "map" and isinstance(p["poses"], list) and p["poses"]
    pose = p["poses"][0]["pose"]["position"]
    assert set(pose) == {"x", "y", "z"} and pose["z"] == 0.0     # geometry_msgs/Point on the surface plane
    g = out["motion_goals"][0]
    assert g["header"]["frame_id"] == "map" and "x" in g["pose"]["position"]


def test_work_goal_carries_arm_drum_payload():
    wg = next(g for g in lower_plan_ir(_ir())["work_goals"] if g["op"] == "Excavate")
    assert wg["site"] is not None and wg["mass_kg"] is not None and "energy_J" in wg["expect"]


def test_observe_action_lowers_to_an_observation_goal():
    ir = {"plan_id": "x", "schema_version": "1.0", "feasible": True,
          "actions": [{"id": 7, "op": "Observe", "vehicle": 0, "to": [3.0, 4.0]}]}
    out = lower_plan_ir(ir)
    assert len(out["observation_goals"]) == 1
    assert out["observation_goals"][0]["at"] == [3.0, 4.0] and out["observation_goals"][0]["action_id"] == 7


def test_blocked_leg_and_infeasible_plan_emit_replan_events():
    ir = {"plan_id": "y", "schema_version": "1.0", "feasible": False, "blocked_legs": 1,
          "actions": [{"id": 0, "op": "GoTo", "vehicle": 0, "to": [9.0, 9.0], "waypoints": [], "reached": False}]}
    out = lower_plan_ir(ir)
    reasons = {e["reason"] for e in out["replan_events"]}
    assert reasons == {"leg_unreachable", "plan_infeasible"}
    assert out["paths"] == [{"header": {"frame_id": "map"}, "action_id": 0, "vehicle": 0, "poses": []}]


def test_posture_plan_assigns_and_legally_sequences_postures():  # [REQ:AM-01]
    # AM-01 X: the lowering drives the posture FSM, so each action declares the posture the executive must
    # command and every realized transition is legal under stewie.specs.posture_machine (the FSM is no island).
    from stewie.specs.posture_machine import PostureMachine, can_transition
    out = lower_plan_ir(_ir())
    # the real IR is GoTo, CutHaulFill, GoTo, Excavate -> TRANSIT, DIG, TRANSIT, DIG
    assert [s["target_posture"] for s in out["posture_plan"]] == ["TRANSIT", "DIG", "TRANSIT", "DIG"]
    # replaying every entered posture through a fresh machine (starts BRAKED_HOLD) is legal end-to-end
    m = PostureMachine()
    for step in out["posture_plan"]:
        for p in step["entered"]:
            ok, why = can_transition(m.state, p)
            assert ok, (m.state, p, why)
            assert m.transition(p)
    # the per-action goals carry the posture the executive holds for that action
    assert all(g.get("posture") == "TRANSIT" for g in out["motion_goals"])
    assert {g["op"]: g.get("posture") for g in out["work_goals"]} == {"CutHaulFill": "DIG", "Excavate": "DIG"}


def test_illegal_direct_posture_inserts_legal_intermediate():  # [REQ:AM-01]
    # Observe (MEERKAT) then Excavate (DIG): MEERKAT->DIG is illegal -> the FSM must pass through TRANSIT.
    ir = {"plan_id": "z", "schema_version": "1.0", "feasible": True, "actions": [
        {"id": 1, "op": "Observe", "vehicle": 0, "to": [1.0, 1.0]},
        {"id": 2, "op": "Excavate", "vehicle": 0, "site": [2.0, 2.0], "mass_kg": 5.0,
         "expect": {"energy_J": 1.0}},
    ]}
    out = lower_plan_ir(ir)
    obs = next(s for s in out["posture_plan"] if s["action_id"] == 1)
    exc = next(s for s in out["posture_plan"] if s["action_id"] == 2)
    assert obs["target_posture"] == "MEERKAT" and obs["entered"] == ["TRANSIT", "MEERKAT"]  # from BRAKED_HOLD
    assert exc["target_posture"] == "DIG" and "TRANSIT" in exc["entered"] and exc["entered"][-1] == "DIG"
    assert out["observation_goals"][0]["posture"] == "MEERKAT"
