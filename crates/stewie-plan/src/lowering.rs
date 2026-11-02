//! NV-11: a plan IR lowered to ROS2-shaped messages (Python `stewie.bridge.plan_lowering.lower_plan_ir`) with the
//! AM-01 posture state machine it drives (Python `stewie.specs.posture_machine`). Pure translation into plain
//! message-shaped JSON: a `nav_msgs/Path` and a `PoseStamped` motion goal per `GoTo` (order-frame `(x, y)` to the
//! REP-103 map frame `(x, -y)`), an arm/drum goal per work op, an observation goal per `Observe`, a replan event
//! per blocked leg and for an infeasible plan, and the FSM-legal posture transitions each action needs.

use serde_json::{Map, Value, json};

const TRANSIT: &str = "TRANSIT";
const BRAKED_HOLD: &str = "BRAKED_HOLD";
const SELF_RIGHT: &str = "SELF_RIGHT";
const IRON_CROSS: &str = "IRON_CROSS";

/// The legal transitions out of each posture; the safe stop `BRAKED_HOLD` is reachable from every one.
fn legal(from: &str, to: &str) -> bool {
    if to == BRAKED_HOLD {
        return true;
    }
    let next: &[&str] = match from {
        TRANSIT => &["DIG", "DUMP_Z", "MEERKAT", "DRUM_WALK"],
        "DIG" => &[TRANSIT, "DUMP_Z"],
        "DUMP_Z" => &[TRANSIT, "DIG"],
        "MEERKAT" | "DRUM_WALK" => &[TRANSIT],
        BRAKED_HOLD => &[TRANSIT, SELF_RIGHT, IRON_CROSS],
        SELF_RIGHT => &[BRAKED_HOLD, TRANSIT],
        _ => &[],
    };
    next.contains(&to)
}

/// The posture each lowered action requires the executive to hold.
fn op_posture(op: &str) -> Option<&'static str> {
    match op {
        "GoTo" => Some(TRANSIT),
        "Excavate" | "CutHaulFill" | "Sinter" => Some("DIG"),
        "Import" => Some("DUMP_Z"),
        "Observe" => Some("MEERKAT"),
        _ => None,
    }
}

/// Step the machine at `state` to `target` by legal transitions only, through the mobile `TRANSIT` hub, else
/// the universal safe path `BRAKED_HOLD -> TRANSIT -> target`; the postures entered, in order.
fn drive_to(state: &mut &'static str, target: &'static str) -> Vec<&'static str> {
    if *state == target {
        return Vec::new();
    }
    let step = |s: &mut &'static str, to: &'static str| {
        let ok = *s == to || legal(s, to);
        if ok {
            *s = to;
        }
        ok
    };
    if step(state, target) {
        return vec![target];
    }
    let mut entered = Vec::new();
    if *state != TRANSIT && step(state, TRANSIT) {
        entered.push(TRANSIT);
        if step(state, target) {
            entered.push(target);
            return entered;
        }
    }
    *state = BRAKED_HOLD;
    entered.push(BRAKED_HOLD);
    if step(state, TRANSIT) {
        entered.push(TRANSIT);
    }
    if step(state, target) {
        entered.push(target);
    }
    entered
}

fn pose_stamped(x: f64, y: f64, frame_id: &str) -> Map<String, Value> {
    let mut m = Map::new();
    m.insert("header".into(), json!({"frame_id": frame_id}));
    m.insert(
        "pose".into(),
        json!({"position": {"x": x, "y": y, "z": 0.0}, "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}),
    );
    m
}

fn xy(v: &Value) -> (f64, f64) {
    (v[0].as_f64().unwrap_or(0.0), v[1].as_f64().unwrap_or(0.0))
}

fn get(a: &Value, k: &str) -> Value {
    a.get(k).cloned().unwrap_or(Value::Null)
}

/// Lower `ir` to the ROS2-shaped commands, carrying its `plan_id` and schema version.
#[must_use]
#[allow(clippy::too_many_lines)] // one arm per IR op, as the Python
pub fn lower_plan_ir(ir: &Value, frame_id: &str) -> Value {
    let (mut paths, mut motion, mut work, mut observe, mut replan, mut postures) = (
        Vec::new(),
        Vec::new(),
        Vec::new(),
        Vec::new(),
        Vec::new(),
        Vec::new(),
    );
    let mut state: &'static str = BRAKED_HOLD;
    for a in ir["actions"].as_array().into_iter().flatten() {
        let op = a["op"].as_str().unwrap_or("");
        let veh = a.get("vehicle").and_then(Value::as_i64).unwrap_or(0);
        let mut goal: Option<Map<String, Value>> = None;
        match op {
            "GoTo" => {
                let poses: Vec<Value> = a["waypoints"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .map(|p| {
                        let (x, y) = xy(p);
                        Value::Object(pose_stamped(x, -y, frame_id))
                    })
                    .collect();
                paths.push(json!({"header": {"frame_id": frame_id}, "action_id": get(a, "id"), "vehicle": veh,
                                  "poses": poses}));
                let to = get(a, "to");
                if !to.is_null() {
                    let (x, y) = xy(&to);
                    let mut g = pose_stamped(x, -y, frame_id);
                    g.insert("action_id".into(), get(a, "id"));
                    g.insert("vehicle".into(), json!(veh));
                    goal = Some(g);
                }
                if a.get("reached") == Some(&Value::Bool(false)) {
                    replan.push(json!({"action_id": get(a, "id"), "vehicle": veh, "reason": "leg_unreachable",
                                       "to": to}));
                }
            }
            "Excavate" | "CutHaulFill" | "Import" | "Sinter" => {
                let g = json!({"action_id": get(a, "id"), "op": op, "vehicle": veh, "site": get(a, "site"),
                               "dest": get(a, "dest"), "mass_kg": get(a, "mass_kg"), "haul_m": get(a, "haul_m"),
                               "expect": get(a, "expect")});
                goal = g.as_object().cloned();
            }
            "Observe" => {
                let at = match get(a, "to") {
                    Value::Null => get(a, "site"),
                    to => to,
                };
                let g =
                    json!({"action_id": get(a, "id"), "op": "Observe", "vehicle": veh, "at": at});
                goal = g.as_object().cloned();
            }
            _ => {}
        }
        if let Some(target) = op_posture(op) {
            let entered = drive_to(&mut state, target);
            postures.push(
                json!({"action_id": get(a, "id"), "op": op, "target_posture": target,
                                 "entered": entered}),
            );
            if let Some(g) = goal.as_mut() {
                g.insert("posture".into(), json!(target));
            }
        }
        if let Some(g) = goal {
            match op {
                "GoTo" => motion.push(Value::Object(g)),
                "Observe" => observe.push(Value::Object(g)),
                _ => work.push(Value::Object(g)),
            }
        }
    }
    if ir.get("feasible") == Some(&Value::Bool(false)) {
        replan.push(json!({"reason": "plan_infeasible",
                           "blocked_legs": ir.get("blocked_legs").and_then(Value::as_i64).unwrap_or(0)}));
    }
    json!({"plan_id": get(ir, "plan_id"), "ir_version": get(ir, "schema_version"), "frame_id": frame_id,
           "paths": paths, "motion_goals": motion, "work_goals": work, "observation_goals": observe,
           "replan_events": replan, "posture_plan": postures})
}
