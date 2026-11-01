//! Order-independent trip construction (Python `lode.planner_trips`, RW-33c1): the balance's flows become trips
//! carrying their own dig, haul, lift and offload energy, so any visit order can be simulated and scored.
//!
//! A cut-to-fill trip shuttles the drum `ceil(mass / drum)` times over the routed leg; its haul energy is
//! integrated segment by segment along the route, loaded out and empty back, each segment paying
//! `length x J/m / (1 - slip)` with slip from the conserved slip-sinkage equilibrium at that grade and weight; its
//! lift is the cumulative positive ascent along the route. An import is offloaded at the drum's rate; surplus
//! cut mass is still dug. Waypoints are zero-mass visits. Sinter orders are refused: the sinter energy and head
//! power are uncalibrated and the gate is off, as in the Python.

use std::collections::BTreeSet;

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_physics::terra::{self, DriveCase};
use stewie_traverse::costmap::CostmapOptions;
use stewie_traverse::haul;
use stewie_traverse::route::{Dem, route_leg};

use crate::balance::{Flow, Profile, Routes, balance};
use crate::mission::{Mission, OrderKind};

/// Planner inputs with no published value or that belong to the mission (D-R85): each must be given.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlannerParams {
    /// Battery fraction held back from planning [0, 1).
    pub reserve_frac: f64,
    /// Recharge power at the charger [W] ([CALIB]).
    pub charge_w: f64,
    /// Drum dig and deposit throughput [kg/s].
    pub dig_rate_kg_s: f64,
    /// Drive speed [m/s] (the rover profile's).
    pub drive_speed_ms: f64,
    /// Rolling-resistance coefficient for the flat drive power (the rover profile's, [ASSUMPTION]).
    pub rolling_resistance: f64,
    /// Drivetrain efficiency (the rover profile's, [CALIB]).
    pub drivetrain_efficiency: f64,
    /// Body gravity [m/s^2] (the registry's).
    pub gravity_ms2: f64,
}

/// The wheel model the planner's per-leg slip is solved with.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SlipModel {
    pub n_wheels: u32,
    pub contact_len_m: f64,
    pub contact_width_m: f64,
    /// Sinkage at which the slip loop is a runaway [m].
    pub z_entrap_m: f64,
}

/// The selected vehicle's planning figures (Python `PlanningContext`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Context {
    pub dig_j_per_kg: f64,
    /// Flat drive energy [J/m]: the tractive draw at the body's gravity over the drive speed.
    pub drive_j_per_m: f64,
    pub battery_j: f64,
    pub drum_kg: f64,
    pub rover_mass_kg: f64,
    /// The vehicle's rated drive power [W] (offload handling energy uses it).
    pub drive_power_w: f64,
    pub drive_speed_ms: f64,
    pub reserve_frac: f64,
    pub charge_w: f64,
}

impl Context {
    #[must_use]
    pub fn reserve_j(&self) -> f64 {
        self.reserve_frac * self.battery_j
    }

    #[must_use]
    pub fn usable_j(&self) -> f64 {
        self.battery_j * (1.0 - self.reserve_frac)
    }
}

/// Steady drive electrical power [W] at a slope: `m g (crr cos|th| + sin|th|) v / efficiency`, never negative.
#[must_use]
pub fn drive_power_w(slope_deg: f64, mass_kg: f64, p: &PlannerParams) -> f64 {
    let th = slope_deg.abs().to_radians();
    let force = (mass_kg * p.gravity_ms2 * (p.rolling_resistance * th.cos() + th.sin())).max(0.0);
    force * p.drive_speed_ms / p.drivetrain_efficiency
}

/// The mission's vehicle as a planning context.
///
/// # Errors
/// A vehicle the fleet does not register.
pub fn context(m: &Mission, fleet: &Fleet, p: &PlannerParams) -> Result<Context, String> {
    let veh = fleet
        .vehicles
        .get(&m.vehicle)
        .or_else(|| fleet.vehicles.get(&m.vehicle.trim().to_lowercase()))
        .ok_or_else(|| format!("unknown vehicle {:?}", m.vehicle))?;
    let onboard: f64 = veh
        .onboard_power
        .iter()
        .filter_map(|s| fleet.power_sources.get(s.as_str()))
        .map(|s| s.capacity_j)
        .filter(|&c| c > 0.0)
        .sum();
    if onboard <= 0.0 {
        return Err(format!(
            "vehicle {:?} carries no onboard battery",
            m.vehicle
        ));
    }
    Ok(Context {
        dig_j_per_kg: veh.dig_energy_j_per_kg * m.dig_energy_factor.unwrap_or(1.0),
        drive_j_per_m: drive_power_w(0.0, veh.dry_mass_kg, p) / p.drive_speed_ms,
        battery_j: onboard,
        drum_kg: veh.drum_capacity_kg,
        rover_mass_kg: veh.dry_mass_kg,
        drive_power_w: veh.drive_power_w,
        drive_speed_ms: p.drive_speed_ms,
        reserve_frac: p.reserve_frac,
        charge_w: p.charge_w,
    })
}

/// Wheel slip on a grade with a payload: the conserved slip-sinkage equilibrium for the laden weight, clamped to
/// [0, 0.95] (Python `slip_alpha_to_slip`).
///
/// # Errors
/// The equilibrium's refusal of its inputs.
pub fn slip_at(
    slope_deg: f64,
    payload_kg: f64,
    rover_mass_kg: f64,
    gravity_ms2: f64,
    soil: &SoilParams,
    w: &SlipModel,
) -> Result<f64, String> {
    let eq = terra::slip_sinkage_equilibrium(
        &DriveCase {
            total_weight_n: (rover_mass_kg + payload_kg.max(0.0)) * gravity_ms2,
            slope_rad: slope_deg.max(0.0).to_radians(),
            n_wheels: w.n_wheels,
            contact_len_m: w.contact_len_m,
            contact_width_m: w.contact_width_m,
            density: None,
            demand_frac: 1.0,
            extra_demand_n: 0.0,
            s_entrap: 0.95,
            z_entrap_m: w.z_entrap_m,
        },
        soil,
    )
    .map_err(|e| e.to_string())?;
    Ok(eq.slip.clamp(0.0, 0.95))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TripKind {
    Goto,
    Import,
    Dig,
    CutFill,
}

/// One trip with its order-independent costs.
#[derive(Debug, Clone, PartialEq)]
pub struct Trip {
    pub kind: TripKind,
    /// Where the work happens (the cut for a haul; the fill for an import).
    pub site: (f64, f64),
    /// Where the rover ends (the fill for a haul).
    pub dest: (f64, f64),
    pub label: String,
    pub mass_kg: f64,
    pub dig_e: f64,
    pub dig_t: f64,
    pub haul_m: f64,
    /// Total haul energy (flat drive plus slip surcharge) [J].
    pub haul_e: f64,
    pub drive_e: f64,
    pub slip_e: f64,
    pub lift_e: f64,
    pub offload_e: f64,
    pub offload_t: f64,
    pub actions: BTreeSet<String>,
    pub shape: Option<Value>,
}

impl Trip {
    fn new(
        kind: TripKind,
        site: (f64, f64),
        dest: (f64, f64),
        label: String,
        actions: &[&str],
    ) -> Self {
        Self {
            kind,
            site,
            dest,
            label,
            mass_kg: 0.0,
            dig_e: 0.0,
            dig_t: 0.0,
            haul_m: 0.0,
            haul_e: 0.0,
            drive_e: 0.0,
            slip_e: 0.0,
            lift_e: 0.0,
            offload_e: 0.0,
            offload_t: 0.0,
            actions: actions.iter().map(|a| (*a).to_owned()).collect(),
            shape: None,
        }
    }
}

/// A routed haul leg kept for the plan's route geometry.
#[derive(Debug, Clone, PartialEq)]
pub struct LegRoute {
    pub from: (f64, f64),
    pub to: (f64, f64),
    pub waypoints: Vec<(f64, f64)>,
    pub reached: bool,
}

/// The routing summary of a trip build.
#[derive(Debug, Clone, PartialEq)]
pub struct TripsMeta {
    pub straight_haul_m: f64,
    pub routed_haul_m: f64,
    pub blocked_legs: usize,
    pub traverse_cap_deg: f64,
    pub routes: Vec<LegRoute>,
    pub feasible: bool,
}

/// Height at a local point: the nearest DEM node, or `None` off the grid (Python `_z`).
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // a rounded, range-checked grid index
fn node_height(dem: &Dem<'_>, (x, y): (f64, f64)) -> Option<f64> {
    let index = |v: f64, n: usize| {
        let k = v.round_ties_even();
        (k >= 0.0 && k < f64::from(u32::try_from(n).unwrap_or(u32::MAX))).then_some(k as usize)
    };
    let col = index((dem.origin.0 + x) / dem.cell_m, dem.width)?;
    let row = index((dem.origin.1 + y) / dem.cell_m, dem.height)?;
    Some(dem.z[row * dem.width + col])
}

/// Round-trip haul energy and its flat baseline over a routed polyline, `loads` shuttles (Python
/// `_segmented_haul_energy`); `None` when fewer than two waypoints lie on the grid.
///
/// # Errors
/// The slip solve's refusal.
#[allow(clippy::too_many_arguments)] // the polyline, the shuttle count and the vehicle and soil it is driven with
pub fn segmented_haul_energy(
    dem: &Dem<'_>,
    waypoints: &[(f64, f64)],
    loads: f64,
    ctx: &Context,
    gravity_ms2: f64,
    soil: &SoilParams,
    w: &SlipModel,
) -> Result<Option<(f64, f64)>, String> {
    let pts: Vec<(f64, f64, f64)> = waypoints
        .iter()
        .filter_map(|&(x, y)| node_height(dem, (x, y)).map(|z| (x, y, z)))
        .collect();
    if pts.len() < 2 {
        return Ok(None);
    }
    let pass = |seq: &[(f64, f64, f64)], payload: f64| -> Result<(f64, f64), String> {
        let (mut e, mut flat) = (0.0, 0.0);
        for s in seq.windows(2) {
            let ((x0, y0, z0), (x1, y1, z1)) = (s[0], s[1]);
            let len = (x1 - x0).hypot(y1 - y0);
            if len <= 1e-9 {
                continue;
            }
            let slope = (z1 - z0).abs().atan2(len).to_degrees();
            let slip = slip_at(slope, payload, ctx.rover_mass_kg, gravity_ms2, soil, w)?;
            e += len * ctx.drive_j_per_m / (1.0 - slip);
            flat += len * ctx.drive_j_per_m;
        }
        Ok((e, flat))
    };
    let (out_e, out_flat) = pass(&pts, ctx.drum_kg)?;
    let back: Vec<(f64, f64, f64)> = pts.iter().rev().copied().collect();
    let (back_e, back_flat) = pass(&back, 0.0)?;
    Ok(Some((
        (out_e + back_e) * loads,
        (out_flat + back_flat) * loads,
    )))
}

/// Everything a trip build reads besides the mission.
#[derive(Debug, Clone, Copy)]
pub struct BuildInputs<'a> {
    pub dem: Dem<'a>,
    pub max_traverse_slope_deg: f64,
    pub body_density: f64,
    pub profile: &'a Profile,
    pub soil: &'a SoilParams,
    pub slip: &'a SlipModel,
    pub params: &'a PlannerParams,
}

pub(crate) fn leg(
    dem: Dem<'_>,
    a: (f64, f64),
    b: (f64, f64),
    cap: f64,
    m: &Mission,
) -> Result<stewie_traverse::route::Leg, String> {
    let opts = CostmapOptions {
        max_slope_deg: cap,
        slip_alpha: 2.0,
        max_drop_m: None,
        illumination: None,
        map_uncertainty: None,
    };
    route_leg(dem, a, b, &opts, 20.0, &m.keepouts)
}

/// Lower the mission's orders into trips (Python `_build_trips`). Returns the trips, the balance flows, the
/// surplus spoil [kg] and the routing summary.
///
/// # Errors
/// A sinter order (gated off), an unknown vehicle, or a routing or slip refusal.
#[allow(clippy::too_many_lines, clippy::many_single_char_names)] // one pass over the flows, in the Python's order
pub fn build_trips(
    m: &Mission,
    fleet: &Fleet,
    inp: &BuildInputs<'_>,
) -> Result<(Vec<Trip>, Vec<Flow>, f64, TripsMeta), String> {
    let sinters = m
        .orders
        .iter()
        .filter(|o| o.kind == OrderKind::Sinter)
        .count();
    if sinters > 0 {
        return Err(format!(
            "{sinters} sinter order(s) present but sinter is GATED OFF: its energy and head power are uncalibrated"
        ));
    }
    let p = inp.params;
    let ctx = context(m, fleet, p)?;
    let mut routes = Routes::new(inp.dem, inp.max_traverse_slope_deg, &m.keepouts);
    let (flows, surplus) = balance(m, inp.body_density, inp.profile, &mut routes)?;
    let mut trips: Vec<Trip> = m
        .orders
        .iter()
        .filter(|o| o.kind == OrderKind::Goto)
        .map(|o| {
            Trip::new(
                TripKind::Goto,
                (o.x, o.y),
                (o.x, o.y),
                format!("Waypoint: {}", o.action),
                &[&o.action],
            )
        })
        .collect();
    let (mut straight_haul, mut routed_haul, mut blocked) = (0.0, 0.0, 0usize);
    let mut leg_routes = Vec::new();
    let offload_e_per_kg = ctx.drive_power_w / p.dig_rate_kg_s;
    let charger = m.charger;
    for fl in &flows {
        match (fl.cut, fl.fill) {
            (None, Some(j)) => {
                let fo = &m.orders[j];
                let delivered = leg(
                    inp.dem,
                    charger,
                    (fo.x, fo.y),
                    inp.max_traverse_slope_deg,
                    m,
                )?;
                if !delivered.reached {
                    blocked += 1;
                    leg_routes.push(LegRoute {
                        from: charger,
                        to: (fo.x, fo.y),
                        waypoints: Vec::new(),
                        reached: false,
                    });
                }
                let mut t = Trip::new(
                    TripKind::Import,
                    (fo.x, fo.y),
                    (fo.x, fo.y),
                    format!("Import fill: {}", fo.action),
                    &[&fo.action],
                );
                t.mass_kg = fl.mass_kg;
                t.offload_e = fl.mass_kg * offload_e_per_kg;
                t.offload_t = fl.mass_kg / p.dig_rate_kg_s;
                t.shape.clone_from(&fo.shape);
                trips.push(t);
            }
            (Some(i), None) => {
                let co = &m.orders[i];
                let mut t = Trip::new(
                    TripKind::Dig,
                    (co.x, co.y),
                    (co.x, co.y),
                    format!("Excavate spoil: {}", co.action),
                    &[&co.action],
                );
                t.mass_kg = fl.mass_kg;
                t.dig_e = fl.mass_kg * ctx.dig_j_per_kg;
                t.dig_t = fl.mass_kg / p.dig_rate_kg_s;
                t.shape.clone_from(&co.shape);
                trips.push(t);
            }
            (Some(i), Some(j)) => {
                let (co, fo) = (&m.orders[i], &m.orders[j]);
                let (a, b) = ((co.x, co.y), (fo.x, fo.y));
                let loads = (fl.mass_kg / ctx.drum_kg).ceil().max(1.0);
                let path = leg(inp.dem, a, b, inp.max_traverse_slope_deg, m)?;
                let (route_m, base_m, reached) =
                    (path.routed_m, path.grid_straight_m, path.reached);
                let waypoints = if reached { path.waypoints } else { Vec::new() };
                if !reached {
                    blocked += 1;
                }
                leg_routes.push(LegRoute {
                    from: a,
                    to: b,
                    waypoints: waypoints.clone(),
                    reached,
                });
                straight_haul += base_m;
                routed_haul += route_m;
                // an off-DEM endpoint has no known gain; it cannot have routed either, so the plan is infeasible
                let dh = haul::elevation_gain_m(&inp.dem, a, b).unwrap_or(0.0);
                let ascent = if reached && waypoints.len() >= 2 {
                    haul::cumulative_ascent_m(&inp.dem, &waypoints).unwrap_or(0.0)
                } else {
                    dh.max(0.0)
                };
                let seg = if reached && waypoints.len() >= 2 {
                    segmented_haul_energy(
                        &inp.dem,
                        &waypoints,
                        loads,
                        &ctx,
                        p.gravity_ms2,
                        inp.soil,
                        inp.slip,
                    )?
                } else {
                    None
                };
                let (haul_e, drive_e) = if let Some(e) = seg {
                    e
                } else {
                    let slope = if route_m > 1e-9 {
                        dh.abs().atan2(route_m).to_degrees()
                    } else {
                        0.0
                    };
                    let one_way = route_m * loads;
                    let loaded = slip_at(
                        slope,
                        ctx.drum_kg,
                        ctx.rover_mass_kg,
                        p.gravity_ms2,
                        inp.soil,
                        inp.slip,
                    )?;
                    let empty = slip_at(
                        slope,
                        0.0,
                        ctx.rover_mass_kg,
                        p.gravity_ms2,
                        inp.soil,
                        inp.slip,
                    )?;
                    (
                        one_way * ctx.drive_j_per_m / (1.0 - loaded)
                            + one_way * ctx.drive_j_per_m / (1.0 - empty),
                        (one_way + one_way) * ctx.drive_j_per_m,
                    )
                };
                let mut t = Trip::new(
                    TripKind::CutFill,
                    a,
                    b,
                    format!("{} \u{2192} {}", co.action, fo.action),
                    &[&co.action, &fo.action],
                );
                t.mass_kg = fl.mass_kg;
                t.dig_e = fl.mass_kg * ctx.dig_j_per_kg;
                t.dig_t = fl.mass_kg / p.dig_rate_kg_s;
                t.haul_m = 2.0 * route_m * loads;
                t.haul_e = haul_e;
                t.drive_e = drive_e;
                t.slip_e = haul_e - drive_e;
                t.lift_e = fl.mass_kg * p.gravity_ms2 * ascent;
                t.shape.clone_from(&co.shape);
                trips.push(t);
            }
            (None, None) => {}
        }
    }
    let meta = TripsMeta {
        straight_haul_m: straight_haul,
        routed_haul_m: routed_haul,
        blocked_legs: blocked,
        traverse_cap_deg: inp.max_traverse_slope_deg,
        routes: leg_routes,
        feasible: blocked == 0,
    };
    Ok((trips, flows, surplus, meta))
}

/// Order-level precedence lifted to trip indices: `(i, j)` when trip `i` touches a `before` action and trip `j`
/// an `after` one (self-edges dropped), sorted and deduplicated.
#[must_use]
pub fn trip_precedence(trips: &[Trip], m: &Mission) -> Vec<(usize, usize)> {
    let mut pairs = BTreeSet::new();
    for (before, after) in &m.precedence {
        for (i, _) in trips
            .iter()
            .enumerate()
            .filter(|(_, t)| t.actions.contains(before))
        {
            for (j, _) in trips
                .iter()
                .enumerate()
                .filter(|(j, t)| *j != i && t.actions.contains(after))
            {
                pairs.insert((i, j));
            }
        }
    }
    pairs.into_iter().collect()
}

/// Whether trip-order constraints admit any ordering (Kahn's topological sort; a cycle does not).
#[must_use]
pub fn precedence_is_feasible(n: usize, pairs: &[(usize, usize)]) -> bool {
    let mut indeg = vec![0usize; n];
    let mut succ = vec![Vec::new(); n];
    for &(i, j) in pairs {
        succ[i].push(j);
        indeg[j] += 1;
    }
    let mut queue: Vec<usize> = (0..n).filter(|&k| indeg[k] == 0).collect();
    let mut emitted = 0;
    while let Some(u) = queue.pop() {
        emitted += 1;
        for &v in &succ[u] {
            indeg[v] -= 1;
            if indeg[v] == 0 {
                queue.push(v);
            }
        }
    }
    emitted == n
}

/// When an action of `class` may start at mission time `t` (Python `_window_gate`): unconstrained without
/// windows for the class; inside an interval now; else idle to the next interval's open; past the last close,
/// the reason it cannot run. Returns `(start, wait, reason)`.
#[must_use]
pub fn window_gate(
    windows: &std::collections::BTreeMap<String, Vec<(f64, f64)>>,
    class: &str,
    t: f64,
) -> (f64, f64, Option<String>) {
    let Some(intervals) = windows.get(class).filter(|v| !v.is_empty()) else {
        return (t, 0.0, None);
    };
    let mut sorted = intervals.clone();
    sorted.sort_by(|a, b| a.0.total_cmp(&b.0).then(a.1.total_cmp(&b.1)));
    for (open, close) in sorted {
        if t <= close {
            return if t < open {
                (open, open - t, None)
            } else {
                (t, 0.0, None)
            };
        }
    }
    (
        t,
        0.0,
        Some(format!(
            "{class} window closed (no allowed interval at or after t={t:.0}s)"
        )),
    )
}
