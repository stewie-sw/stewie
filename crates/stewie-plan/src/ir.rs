//! The executable plan IR (Python `lode.planner_views.plan_ir`, RW-33d2b): the versioned machine artifact a rover
//! or ROS executive runs, lowered from one computed [`Plan`]. Each trip becomes a terrain-following `GoTo` and a
//! typed work action (`CutHaulFill`, `Excavate`, `Import`, or `Work` for a waypoint) with its expected energy and
//! duration, a model-error band, and preconditions: the battery to finish the action and still drive home, and for
//! a dig the drum cap and the survey-coverage gate. Recharges are not actions; an executive recharges when a
//! precondition fails. Each rover's legs start from its own last position. A leg with no safe route, or an action
//! end with no safe route home, makes the IR infeasible rather than drawing a straight line through the hazard.
//! `plan_id` is the Python's content hash (SHA-1 of the sorted JSON of body, request, orders and action sites).
//!
//! An action one charge cannot finish and still drive home is split into equal per-charge parts tagged
//! `part: [k, n]`, so every precondition is satisfiable from a full battery (Aaron, D-R96); a trip precedence edge
//! runs from the earlier trip's last part to the later trip's first. With no split the IR equals the Python's.
//!
//! Drive legs and the reserve are priced with the mission vehicle's context; the Python prices them with the IPEx
//! constants whatever the vehicle (D-R95). The DEM is required: there is no straight-line plan IR. The Python's
//! `provenance` block hashes its own object dump; the Rust plan identity is RW-33f.

use serde_json::{Value, json};
use sha1::{Digest, Sha1};
use stewie_traverse::route::Dem;
use stewie_twin::numpy::round;

use crate::assemble::Plan;
use crate::mission::Mission;
use crate::trips::{Context, TripKind, leg, trip_precedence};

pub const PLAN_IR_VERSION: &str = "1.0";
/// The per-action energy and time tolerance (the plan's a-priori model error, 1 sigma).
const MODEL_ERR_FRAC: f64 = 0.12;
/// Survey coverage a site needs before digging (Python `dart.map_channel.COVERAGE_DIG_GATE`).
const COVERAGE_DIG_GATE: f64 = 0.6;

fn xy3(p: (f64, f64)) -> Value {
    json!([round(p.0, 3), round(p.1, 3)])
}

fn dist(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

/// The executable IR of `plan`, routed over `dem` at the traverse cap.
///
/// # Errors
/// A DEM that is not real terrain (empty, misshapen or holed), a routing refusal, or a footprint the boundary should
/// already have refused.
#[allow(clippy::too_many_lines)] // one lowering pass, field by field as the Python emits it
pub fn plan_ir(
    m: &Mission,
    plan: &Plan,
    ctx: &Context,
    dem: Dem<'_>,
    max_traverse_slope_deg: f64,
) -> Result<Value, String> {
    // no executable plan without real terrain (assessment #3): no flat or holed stand-in
    if dem.width == 0
        || dem.height == 0
        || dem.z.len() != dem.width * dem.height
        || !(dem.cell_m.is_finite() && dem.cell_m > 0.0)
        || dem.z.iter().any(|h| !h.is_finite())
    {
        return Err(
            "no executable plan IR without real terrain: the DEM is empty, misshapen or has a non-finite height"
                .to_owned(),
        );
    }
    // the bare survival floor, from the mission vehicle's reserve
    let survival_floor = ctx.reserve_j();
    let floor_j = round(survival_floor, 1);
    let charger = m.charger;
    let mut feasible = plan.totals.feasible;
    let mut actions: Vec<Value> = Vec::with_capacity(2 * plan.trips.len());
    let mut work_aid = Vec::with_capacity(plan.trips.len());
    let mut prev_by_vehicle: Vec<(usize, (f64, f64))> = Vec::new();
    for (tr, &veh) in plan.trips.iter().zip(&plan.vehicle) {
        let site = tr.site;
        let prev = prev_by_vehicle
            .iter()
            .find(|(v, _)| *v == veh)
            .map_or(charger, |(_, p)| *p);
        let go = leg(dem, prev, site, max_traverse_slope_deg, m)?;
        let (d, waypoints) = if go.reached {
            (go.routed_m, go.waypoints.iter().map(|&w| xy3(w)).collect())
        } else {
            (dist(prev, site), Vec::new())
        };
        feasible &= go.reached;
        actions.push(json!({
            "id": actions.len(), "op": "GoTo", "vehicle": veh, "to": xy3(site),
            "waypoints": waypoints, "reached": go.reached,
            "expect": {"distance_m": round(d, 2), "duration_s": round(d / ctx.drive_speed_ms, 1),
                       "energy_J": round(d * ctx.drive_j_per_m, 1)},
            "tol": {"energy_frac": MODEL_ERR_FRAC}, "pre": {"battery_J_min": floor_j},
        }));
        let op = match tr.kind {
            TripKind::CutFill => "CutHaulFill",
            TripKind::Dig => "Excavate",
            TripKind::Import => "Import",
            TripKind::Goto => "Work",
        };
        let work_e = tr.dig_e + tr.offload_e + tr.haul_e + tr.lift_e;
        let work_t = tr.dig_t + tr.offload_t + tr.haul_m / ctx.drive_speed_ms;
        let footprint = match &tr.shape {
            Some(Value::Object(shape)) => {
                let mut view = shape.clone();
                let area =
                    crate::mission::footprint_shape_area_m2(shape).map_err(|e| e.to_string())?;
                view.insert("area_m2".into(), json!(round(area, 6)));
                Some(Value::Object(view))
            }
            _ => None,
        };
        // enough to finish the action AND drive home from where it ends
        let mut safe_d = dist(tr.dest, charger);
        if safe_d > 1e-9 {
            let home = leg(dem, tr.dest, charger, max_traverse_slope_deg, m)?;
            if home.reached {
                safe_d = home.routed_m;
            } else {
                feasible = false;
            }
        }
        let to_safe = round(safe_d * ctx.drive_j_per_m, 1);
        // D-R96: an action one charge cannot finish (and still drive home) is split into equal per-charge parts
        let cap = ctx.battery_j - floor_j - to_safe;
        let parts: u32 = if work_e <= cap {
            1
        } else if cap > 0.0 {
            // a ratio above 1 of finite energies; the part count is small
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            let n = (work_e / cap).ceil() as u32;
            n
        } else {
            feasible = false;
            1
        };
        let n = f64::from(parts);
        let (part_e, part_t, part_kg) = (work_e / n, work_t / n, tr.mass_kg / n);
        let first = actions.len();
        for k in 1..=parts {
            let mut pre = json!({
                "battery_J_min": round(floor_j + part_e + to_safe, 1), "reserve_J": floor_j,
                "action_energy_J": round(part_e, 1), "route_to_safe_J": to_safe,
            });
            if matches!(tr.kind, TripKind::CutFill | TripKind::Dig) {
                pre["drum_kg_max"] = json!(round(ctx.drum_kg, 1));
                pre["map_coverage_min"] = json!(COVERAGE_DIG_GATE);
            }
            let loads = if tr.kind == TripKind::CutFill {
                // whole drum loads; the mass and drum are positive, so the ceiling is a small count
                #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
                let l = (part_kg / ctx.drum_kg).ceil().max(1.0) as u64;
                l
            } else {
                0
            };
            let mut act = json!({
                "id": actions.len(), "op": op, "vehicle": veh, "site": xy3(site), "dest": xy3(tr.dest),
                "mass_kg": round(part_kg, 1), "loads": loads, "haul_m": round(tr.haul_m / n, 1),
                "actions": tr.actions.iter().collect::<Vec<_>>(),
                "expect": {"energy_J": round(part_e, 1), "duration_s": round(part_t, 1)},
                "tol": {"energy_frac": MODEL_ERR_FRAC}, "pre": pre,
            });
            if parts > 1 {
                act["part"] = json!([k, parts]);
            }
            if let Some(view) = &footprint {
                act["footprint"] = view.clone();
            }
            actions.push(act);
        }
        work_aid.push((first, actions.len() - 1));
        match prev_by_vehicle.iter_mut().find(|(v, _)| *v == veh) {
            Some((_, p)) => *p = tr.dest,
            None => prev_by_vehicle.push((veh, tr.dest)),
        }
    }
    let mut precedence: Vec<(usize, usize)> = trip_precedence(&plan.trips, m)
        .into_iter()
        .map(|(i, j)| (work_aid[i].1, work_aid[j].0))
        .collect();
    precedence.sort_unstable();
    precedence.dedup();
    let t = &plan.totals;
    let key = json!({
        "body": m.body, "algorithm": t.algorithm, "objective": t.objective, "vehicles": t.vehicles,
        "orders": m.orders.iter().map(|o| json!([o.action, o.kind.name(), o.x, o.y, o.footprint_m2, o.depth_m]))
            .collect::<Vec<_>>(),
        "ops": actions.iter().map(|a| json!([a["op"], a.get("site"), a.get("to")])).collect::<Vec<_>>(),
    });
    let canon = stewie_twin::pyjson::dumps(&key).map_err(|e| e.to_string())?;
    let digest = Sha1::digest(canon.as_bytes());
    // the first 16 hex digits
    let plan_id = digest[..8].iter().fold(String::new(), |mut s, b| {
        use std::fmt::Write as _;
        let _ = write!(s, "{b:02x}");
        s
    });
    let crs = if m.body == "moon" {
        "IAU_2015:30135"
    } else {
        "local"
    };
    Ok(json!({
        "schema_version": PLAN_IR_VERSION, "plan_id": plan_id, "body": m.body,
        "mode": "DEM_KNOWN_POSE_MISSION_SIM",
        "feasible": feasible, "blocked_legs": plan.meta.blocked_legs,
        "vehicles": t.vehicles, "objective": t.objective, "algorithm": t.resolved_algorithm,
        "frame": {"origin_m": xy3(dem.origin), "charger": [charger.0, charger.1], "crs": crs},
        "actions": actions,
        "precedence": precedence.iter().map(|&(a, b)| json!([a, b])).collect::<Vec<_>>(),
        "expect": {"duration_s": round(t.time_s, 1), "energy_J": round(t.energy_j, 1),
                   "distance_m": round(t.distance_m, 1), "charges": t.charges,
                   "makespan_s": round(t.makespan_s, 1)},
        "acceptance": {"as_built_tol_m": 0.02, "recharge_is_precondition_driven": true},
    }))
}
