//! Plan assembly (Python `lode.planner_assembly.plan_and_simulate` / `plan_multi`, RW-33d2a): build the trips
//! once, choose the visit order, simulate, and total. One rover is sequenced over every trip; a fleet is
//! allocated site-exclusively, each rover sequenced and simulated alone, a rover that strands has its reachable
//! work reassigned to the healthy rovers (when no precedence spans the fleet), and every shared-charger,
//! resource, crowding, precedence and vantage wait is folded into the makespan.
//!
//! The report-only totals (uncertainty, relocalization, return-to-lander, the energy ledger) are RW-33d2c.
//! Unlike the Python, a fleet with a stranded rover or a dropped trip is infeasible (D-R94); the Python's
//! fleet aggregate carries no simulation verdict, so it reports such a fleet feasible.

use stewie_contracts::fleet::Fleet;

use crate::balance::{Flow, Routes};
use crate::fleet::{
    Health, VehiclePlan, allocate_trips, charger_conflicts, haul_path_conflicts,
    resolve_cross_vehicle_precedence, resolve_joint_resources, resolve_observation_vantages,
    resolve_spacetime_crowding, rover_health, temporal_conflicts, vehicle_conflicts,
};
use crate::mission::Mission;
use crate::optimize::{
    BRUTE_MAX_TRIPS, HELD_KARP_MAX_TRIPS, Sequencing, effective_algorithm, objective_optimality,
    optimize_sequence, parse_objective,
};
use crate::sim::{Core, Span, TripTimes, simulate};
use crate::trips::{
    BuildInputs, Context, Trip, TripsMeta, build_trips, context, precedence_is_feasible,
    trip_precedence,
};

/// The planner's choices.
#[derive(Debug, Clone, Copy)]
pub struct PlanConfig<'a> {
    pub algorithm: &'a str,
    pub objective: &'a str,
    pub vehicles: usize,
    /// Continuous survival draw over the mission [W]; 0 leaves it unmodelled.
    pub idle_power_w: f64,
    /// Reassign a stranded rover's reachable work to the healthy rovers.
    pub reallocate_stranded: bool,
}

/// The per-rover breakdown of a fleet plan.
#[derive(Debug, Clone, PartialEq)]
pub struct VehicleDetail {
    pub vehicle: usize,
    pub n_trips: usize,
    pub time_s: f64,
    pub energy_j: f64,
    pub distance_m: f64,
    pub charges: u64,
    pub charger_wait_s: f64,
    pub crowd_wait_s: f64,
    pub precedence_wait_s: f64,
    pub resource_wait_s: f64,
    pub observation_wait_s: f64,
    /// The charger, then each visited site.
    pub track: Vec<(f64, f64)>,
    pub health: Health,
}

/// What only a fleet plan reports.
#[derive(Debug, Clone, PartialEq)]
pub struct FleetTotals {
    /// The makespan with unlimited chargers and no waits.
    pub makespan_parallel_s: f64,
    pub charger_wait_s: f64,
    pub resource_wait_s: f64,
    pub resource_waits: Vec<(String, f64)>,
    pub crowd_wait_s: f64,
    pub precedence_wait_s: f64,
    pub observation_wait_s: f64,
    pub observation_vantages: Vec<(String, Vec<usize>)>,
    pub temporal_conflicts: usize,
    pub haul_path_conflicts: usize,
    pub fleet_needs_replan: bool,
    pub fleet_replanned: bool,
    pub unreallocatable_trips: usize,
    pub detail: Vec<VehicleDetail>,
}

/// The plan's headline figures.
#[derive(Debug, Clone, PartialEq)]
pub struct Totals {
    /// Mission time; the makespan for a fleet [s].
    pub time_s: f64,
    pub mass_kg: f64,
    /// Consumed energy including any survival draw [J].
    pub energy_j: f64,
    pub charges: u64,
    pub distance_m: f64,
    pub avg_power_w: f64,
    pub survival_energy_j: f64,
    pub feasible: bool,
    pub infeasible_reasons: Vec<String>,
    pub algorithm: String,
    pub resolved_algorithm: String,
    pub optimality: String,
    pub objective_exact: bool,
    pub solved_metric: &'static str,
    pub n_precedence: usize,
    pub objective: String,
    pub vehicles: usize,
    pub makespan_s: f64,
    pub vehicle_conflicts: usize,
    pub charger_conflicts: usize,
    pub fleet: Option<FleetTotals>,
}

/// One computed plan.
#[derive(Debug, Clone, PartialEq)]
pub struct Plan {
    /// Trips in visit order, rover by rover.
    pub trips: Vec<Trip>,
    /// Each trip's rover.
    pub vehicle: Vec<usize>,
    pub flows: Vec<Flow>,
    pub surplus_kg: f64,
    pub meta: TripsMeta,
    /// Every rover's timeline, concatenated.
    pub tl: Vec<Span>,
    /// Trip windows; `trip` indexes [`Plan::trips`].
    pub times: Vec<TripTimes>,
    pub totals: Totals,
    /// A requested exact solver that degraded, or a heuristic order past the exact cap.
    pub warnings: Vec<String>,
}

fn route_reasons(meta: &TripsMeta) -> Vec<String> {
    if meta.blocked_legs > 0 {
        vec![format!(
            "{} route leg(s) have no safe corridor",
            meta.blocked_legs
        )]
    } else {
        Vec::new()
    }
}

/// Plan the mission (Python `plan_and_simulate`; `vehicles > 1` is the fleet planner).
///
/// # Errors
/// No vehicles, cyclic precedence, a bad objective or algorithm, or a trip-build or routing refusal.
#[allow(clippy::too_many_lines)] // the Python's single-rover planner and its fleet dispatch, in its order
pub fn plan_and_simulate(
    m: &Mission,
    fleet: &Fleet,
    inp: &BuildInputs<'_>,
    cfg: &PlanConfig<'_>,
) -> Result<Plan, String> {
    if cfg.vehicles < 1 {
        return Err(format!("vehicles must be >= 1 (got {})", cfg.vehicles));
    }
    let (trips, flows, surplus_kg, meta) = build_trips(m, fleet, inp)?;
    let ctx = context(m, fleet, inp.params)?;
    let mut routes = Routes::new(inp.dem, inp.max_traverse_slope_deg, &m.keepouts);
    let prec = trip_precedence(&trips, m);
    let weights = parse_objective(cfg.objective)?;
    if cfg.vehicles == 1 {
        if !precedence_is_feasible(trips.len(), &prec) {
            return Err("infeasible precedence: the mission's precedence constraints form a cycle, so no \
                        build sequence can satisfy them. Check `mission.precedence` for a loop (e.g. A->B \
                        and B->A)."
                .to_owned());
        }
        let order = optimize_sequence(
            &mut Sequencing {
                mission: m,
                trips: &trips,
                ctx: &ctx,
                routes: &mut routes,
                precedence: &prec,
            },
            cfg.algorithm,
            &weights,
        )?;
        let trips: Vec<Trip> = order.iter().map(|&i| trips[i].clone()).collect();
        let ident: Vec<usize> = (0..trips.len()).collect();
        let (tl, times, core) = simulate(m, &trips, &ident, &ctx, &mut routes)?;
        let n = trips.len();
        let resolved = effective_algorithm(cfg.algorithm, n).to_owned();
        let (optimality, objective_exact) = objective_optimality(&resolved, &weights);
        let mut warnings = Vec::new();
        if resolved != cfg.algorithm && cfg.algorithm != "auto" {
            warnings.push(format!(
                "plan visit order: '{}' was requested but {n} trips exceed its exact cap \
                 (BRUTE_MAX_TRIPS={BRUTE_MAX_TRIPS}, HELD_KARP_MAX_TRIPS={HELD_KARP_MAX_TRIPS}); \
                 '{resolved}' ran instead and has no optimality bound.",
                cfg.algorithm
            ));
        } else if optimality == "heuristic" && n > HELD_KARP_MAX_TRIPS {
            warnings.push(format!(
                "plan visit order is heuristic: {n} trips exceed the exact cap \
                 (HELD_KARP_MAX_TRIPS={HELD_KARP_MAX_TRIPS}); algorithm '{resolved}' has no optimality bound."
            ));
        }
        let survival = cfg.idle_power_w * core.time_s;
        let mut infeasible_reasons = route_reasons(&meta);
        infeasible_reasons.extend(core.infeasible_reasons.iter().cloned());
        let solved_metric = match resolved.as_str() {
            "held_karp" | "held_karp_lk" => "distance",
            "brute" => "objective",
            _ => "none",
        };
        let totals = Totals {
            time_s: core.time_s,
            mass_kg: core.mass_kg,
            energy_j: if survival > 0.0 {
                core.energy_j + survival
            } else {
                core.energy_j
            },
            charges: core.charges,
            distance_m: core.distance_m,
            avg_power_w: avg_power(&core, survival),
            survival_energy_j: survival,
            feasible: meta.feasible && core.feasible,
            infeasible_reasons,
            algorithm: cfg.algorithm.to_owned(),
            resolved_algorithm: resolved,
            optimality,
            objective_exact,
            solved_metric,
            n_precedence: prec.len(),
            objective: cfg.objective.to_owned(),
            vehicles: 1,
            makespan_s: core.time_s,
            vehicle_conflicts: 0,
            charger_conflicts: 0,
            fleet: None,
        };
        return Ok(Plan {
            vehicle: vec![0; trips.len()],
            trips,
            flows,
            surplus_kg,
            meta,
            tl,
            times,
            totals,
            warnings,
        });
    }
    if !prec.is_empty() && !precedence_is_feasible(trips.len(), &prec) {
        return Err(
            "precedence is infeasible (cyclic / unsatisfiable): no valid build ordering exists"
                .to_owned(),
        );
    }
    let fl = FleetRun {
        m,
        trips: &trips,
        ctx: &ctx,
        algorithm: cfg.algorithm,
        weights: &weights,
    };
    let alloc = allocate_trips(&trips, cfg.vehicles);
    let mut per = Vec::with_capacity(cfg.vehicles);
    for (v, idxs) in alloc.iter().enumerate() {
        let local: Vec<(usize, usize)> = prec
            .iter()
            .filter_map(|&(i, j)| {
                Some((
                    idxs.iter().position(|&g| g == i)?,
                    idxs.iter().position(|&g| g == j)?,
                ))
            })
            .collect();
        per.push(fl.rover(v, idxs, &local, &mut routes)?);
    }
    let (mut unreallocatable, mut replanned) = (0, false);
    if cfg.reallocate_stranded
        && prec.is_empty()
        && per.iter().any(|p| !p.core.feasible)
        && let Some((np, unreached)) = fl.reallocate(&per, &mut routes)?
    {
        per = np;
        unreallocatable = unreached;
        replanned = true;
    }
    fl.aggregate(
        &per,
        &prec,
        (flows, surplus_kg, meta),
        cfg,
        (replanned, unreallocatable),
    )
}

fn avg_power(core: &Core, survival: f64) -> f64 {
    if survival > 0.0 {
        if core.time_s > 1e-9 {
            (core.energy_j + survival) / core.time_s
        } else {
            0.0
        }
    } else {
        core.avg_power_w
    }
}

/// What every rover of a fleet shares.
struct FleetRun<'a> {
    m: &'a Mission,
    trips: &'a [Trip],
    ctx: &'a Context,
    algorithm: &'a str,
    weights: &'a [(String, f64)],
}

impl FleetRun<'_> {
    /// Sequence (honouring `local` precedence among these trips) and simulate one rover's share.
    fn rover(
        &self,
        v: usize,
        idxs: &[usize],
        local: &[(usize, usize)],
        routes: &mut Routes<'_>,
    ) -> Result<VehiclePlan, String> {
        let vtrips: Vec<Trip> = idxs.iter().map(|&i| self.trips[i].clone()).collect();
        let order = if vtrips.is_empty() {
            Vec::new()
        } else {
            optimize_sequence(
                &mut Sequencing {
                    mission: self.m,
                    trips: &vtrips,
                    ctx: self.ctx,
                    routes,
                    precedence: local,
                },
                self.algorithm,
                self.weights,
            )?
        };
        let global: Vec<usize> = order.iter().map(|&k| idxs[k]).collect();
        let (tl, times, core) = simulate(self.m, self.trips, &global, self.ctx, routes)?;
        Ok(VehiclePlan {
            vehicle: v,
            trips: global,
            tl,
            times,
            core,
        })
    }

    /// Reassign the reachable work (each trip a lone rover can finish) to the healthy rovers; a stranded rover
    /// is taken out of service. None when no rover is healthy or no work is reachable.
    fn reallocate(
        &self,
        per: &[VehiclePlan],
        routes: &mut Routes<'_>,
    ) -> Result<Option<(Vec<VehiclePlan>, usize)>, String> {
        let healthy: Vec<usize> = per
            .iter()
            .filter(|p| p.core.feasible)
            .map(|p| p.vehicle)
            .collect();
        if healthy.is_empty() {
            return Ok(None);
        }
        let (mut reachable, mut unreachable) = (Vec::new(), 0);
        for &g in per.iter().flat_map(|p| &p.trips) {
            if simulate(self.m, self.trips, &[g], self.ctx, routes)?
                .2
                .feasible
            {
                reachable.push(g);
            } else {
                unreachable += 1;
            }
        }
        if reachable.is_empty() {
            return Ok(None);
        }
        let sub: Vec<Trip> = reachable.iter().map(|&g| self.trips[g].clone()).collect();
        let shares = allocate_trips(&sub, healthy.len());
        let mut out = Vec::with_capacity(per.len());
        for p in per {
            let idxs: Vec<usize> = healthy
                .iter()
                .position(|&h| h == p.vehicle)
                .map(|k| shares[k].iter().map(|&i| reachable[i]).collect())
                .unwrap_or_default();
            out.push(self.rover(p.vehicle, &idxs, &[], routes)?);
        }
        Ok(Some((out, unreachable)))
    }

    #[allow(clippy::too_many_lines)] // the Python aggregate, field by field
    fn aggregate(
        &self,
        per: &[VehiclePlan],
        prec: &[(usize, usize)],
        (flows, surplus_kg, meta): (Vec<Flow>, f64, TripsMeta),
        cfg: &PlanConfig<'_>,
        (replanned, unreallocatable): (bool, usize),
    ) -> Result<Plan, String> {
        let m = self.m;
        let conflicts = vehicle_conflicts(per, self.trips);
        let parallel = per.iter().map(|p| p.core.time_s).fold(0.0, f64::max);
        let joint = resolve_joint_resources(
            per,
            self.trips,
            m.charger_capacity,
            &m.shared_resources,
            0.5,
        );
        let charger_wait: f64 = joint.charger_delay.iter().fold(0.0, |a, b| a + b);
        let resource_wait: f64 = joint.resource_delay.iter().fold(0.0, |a, b| a + b);
        let crowd = resolve_spacetime_crowding(per, 10.0, 64);
        let crowd_wait: f64 = crowd.iter().fold(0.0, |a, b| a + b);
        let pdelay = resolve_cross_vehicle_precedence(per, prec);
        let prec_wait: f64 = pdelay.iter().fold(0.0, |a, b| a + b);
        let obs = resolve_observation_vantages(per.len(), &m.observations, 10.0)?;
        let obs_wait: f64 = obs.delay.iter().fold(0.0, |a, b| a + b);
        let makespan = per
            .iter()
            .enumerate()
            .map(|(i, p)| p.core.time_s + joint.delay[i] + crowd[i] + pdelay[i] + obs.delay[i])
            .fold(0.0, f64::max);
        let energy: f64 = per.iter().map(|p| p.core.energy_j).fold(0.0, |a, b| a + b);
        let busy: f64 = per.iter().map(|p| p.core.time_s).fold(0.0, |a, b| a + b);
        let survival = cfg.idle_power_w
            * (busy + charger_wait + resource_wait + prec_wait + obs_wait + crowd_wait);
        let total_energy = if survival > 0.0 {
            energy + survival
        } else {
            energy
        };
        let detail: Vec<VehicleDetail> = per
            .iter()
            .map(|p| VehicleDetail {
                vehicle: p.vehicle,
                n_trips: p.trips.len(),
                time_s: p.core.time_s,
                energy_j: p.core.energy_j,
                distance_m: p.core.distance_m,
                charges: p.core.charges,
                charger_wait_s: joint.charger_delay[p.vehicle],
                crowd_wait_s: crowd[p.vehicle],
                precedence_wait_s: pdelay[p.vehicle],
                resource_wait_s: joint.resource_delay[p.vehicle],
                observation_wait_s: obs.delay[p.vehicle],
                track: std::iter::once(m.charger)
                    .chain(p.trips.iter().map(|&g| self.trips[g].site))
                    .collect(),
                health: rover_health(p),
            })
            .collect();
        let mut infeasible_reasons = route_reasons(&meta);
        for p in per {
            infeasible_reasons.extend(
                p.core
                    .infeasible_reasons
                    .iter()
                    .map(|r| format!("rover {}: {r}", p.vehicle)),
            );
        }
        if unreallocatable > 0 {
            infeasible_reasons.push(format!(
                "{unreallocatable} trip(s) no single rover can complete were dropped"
            ));
        }
        let feasible = meta.feasible && per.iter().all(|p| p.core.feasible) && unreallocatable == 0;
        // the plan's trips, rover by rover, and their windows re-keyed to that order
        let (mut trips, mut vehicle, mut tl, mut times) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for p in per {
            for w in &p.times {
                times.push(TripTimes {
                    trip: trips.len()
                        + p.trips
                            .iter()
                            .position(|&g| g == w.trip)
                            .expect("a window's trip is the rover's own"),
                    ..*w
                });
            }
            trips.extend(p.trips.iter().map(|&g| self.trips[g].clone()));
            vehicle.extend(std::iter::repeat_n(p.vehicle, p.trips.len()));
            tl.extend(p.tl.iter().copied());
        }
        let totals = Totals {
            time_s: makespan,
            mass_kg: per.iter().map(|p| p.core.mass_kg).sum(),
            energy_j: total_energy,
            charges: per.iter().map(|p| p.core.charges).sum(),
            distance_m: per.iter().map(|p| p.core.distance_m).sum(),
            avg_power_w: if makespan > 1e-9 {
                total_energy / makespan
            } else {
                0.0
            },
            survival_energy_j: survival,
            feasible,
            infeasible_reasons,
            algorithm: cfg.algorithm.to_owned(),
            resolved_algorithm: cfg.algorithm.to_owned(),
            optimality: "heuristic".to_owned(),
            objective_exact: false,
            solved_metric: "none",
            n_precedence: prec.len(),
            objective: cfg.objective.to_owned(),
            vehicles: cfg.vehicles,
            makespan_s: makespan,
            vehicle_conflicts: conflicts,
            charger_conflicts: charger_conflicts(per),
            fleet: Some(FleetTotals {
                makespan_parallel_s: parallel,
                charger_wait_s: charger_wait,
                resource_wait_s: resource_wait,
                resource_waits: joint.resource_waits.clone(),
                crowd_wait_s: crowd_wait,
                precedence_wait_s: prec_wait,
                observation_wait_s: obs_wait,
                observation_vantages: obs.vantages,
                temporal_conflicts: temporal_conflicts(per, 10.0),
                haul_path_conflicts: haul_path_conflicts(per, 10.0),
                fleet_needs_replan: detail.iter().any(|d| d.health.health == "stranded"),
                fleet_replanned: replanned,
                unreallocatable_trips: unreallocatable,
                detail,
            }),
        };
        Ok(Plan {
            trips,
            vehicle,
            flows,
            surplus_kg,
            meta,
            tl,
            times,
            totals,
            warnings: Vec::new(),
        })
    }
}
