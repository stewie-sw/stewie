//! The plan's report totals and energy ledger (Python `lode.planner_assembly._mission_totals` and `_energy_ledger`,
//! RW-33d2c): the material, haul, keep-out and drum figures, the dig-rate band, the one plan-uncertainty block, the
//! return-to-lander check, the scheduled relocalization stops, and one separable ledger whose terms sum to the
//! plan's energy (the terms the vehicle model lacks are explicit, documented zeros).
//!
//! The dig band scales the plan's own dig energy (the vehicle's, times the operator's factor) and the relocalization
//! fix lifts the vehicle's own mass; the Python uses the IPEx constants for both whatever the vehicle and factor
//! (D-R97). The report constants are configuration, given in [`ReportParams`].

use serde_json::{Value, json};
use stewie_twin::numpy::round;

use crate::assemble::Plan;
use crate::balance::{Profile, cut_bank_density, order_mass_kg};
use crate::mission::{Mission, OrderKind};
use crate::sim::SpanKind;
use crate::trips::{Context, TripKind};

/// The report's sourced and tagged constants.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ReportParams {
    /// Rated over maximum drum rate: the low end of the dig-energy band (T2.4).
    pub drum_rate_ratio: f64,
    /// Cut depth one pass takes [m] (T2.3).
    pub max_cut_per_pass_m: f64,
    /// Drum-fill sensor error above half full (FDC MPE).
    pub fill_mpe_frac: f64,
    /// Localization corridor margin [m].
    pub localization_margin_m: f64,
    /// DEM per-cell height sigma [m].
    pub dem_cell_sigma_m: f64,
    /// Dead-reckoning drift allowed before a relocalization fix [m].
    pub relocalize_drift_tol_m: f64,
    /// Along-track drift per metre driven.
    pub drift_frac: f64,
    /// Standstill time of one fix [s].
    pub fix_maneuver_s: f64,
    pub arm_lift_height_m: f64,
    pub arm_lift_efficiency: f64,
    /// Body gravity [m/s^2].
    pub gravity_ms2: f64,
    /// Return-to-lander buffer over the bare return energy when the mission sets none.
    pub default_return_buffer_frac: f64,
}

fn dist(a: (f64, f64), b: (f64, f64)) -> f64 {
    (a.0 - b.0).hypot(a.1 - b.1)
}

/// Whole drum loads for `mass` (at least one).
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // a positive ratio of finite masses
fn loads(mass: f64, drum: f64) -> u64 {
    (mass / drum).ceil().max(1.0) as u64
}

/// The report totals of `plan` (Python `_mission_totals` beyond the core figures).
#[must_use]
#[allow(clippy::too_many_lines)] // the Python's report dict, field by field
pub fn report_totals(
    m: &Mission,
    plan: &Plan,
    ctx: &Context,
    body_density: f64,
    profile: &Profile,
    p: &ReportParams,
) -> Value {
    let digs = |k: TripKind| matches!(k, TripKind::CutFill | TripKind::Dig);
    let dug: f64 = plan
        .trips
        .iter()
        .filter(|t| digs(t.kind))
        .map(|t| t.mass_kg)
        .sum();
    let band = [
        round(ctx.dig_j_per_kg * p.drum_rate_ratio * dug / 1e6, 1),
        round(ctx.dig_j_per_kg * dug / 1e6, 1),
    ];
    let drum_cycles: u64 = plan
        .trips
        .iter()
        .filter(|t| digs(t.kind))
        .map(|t| loads(t.mass_kg, ctx.drum_kg))
        .sum();
    let sum_kind = |k: OrderKind, rho: &dyn Fn(&crate::mission::BuildOrder) -> f64| -> f64 {
        m.orders
            .iter()
            .filter(|o| o.kind == k)
            .map(|o| order_mass_kg(o, rho(o)))
            .sum()
    };
    let imported: f64 = plan
        .flows
        .iter()
        .filter(|f| f.cut.is_none())
        .map(|f| f.mass_kg)
        .sum();
    // cast: a positive pass count
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let cut_passes = m
        .orders
        .iter()
        .filter(|o| o.kind == OrderKind::Cut)
        .map(|o| (o.depth_m / p.max_cut_per_pass_m).ceil() as u64)
        .fold(1, u64::max);
    #[allow(clippy::cast_precision_loss)] // a drum-load count
    let nc = drum_cycles as f64;
    let drum_fill = if drum_cycles > 0 {
        json!({"quantified": true, "into": "time", "mpe_frac": p.fill_mpe_frac, "cycles": nc,
               "cycles_band": [round(nc * (1.0 - p.fill_mpe_frac), 2), round(nc * (1.0 + p.fill_mpe_frac), 2)],
               "source": "DrumSensor FDC MPE, ICE-RASSOR NTRS 20210022781"})
    } else {
        json!({"quantified": false, "into": "time", "note": "no drum cycles in this plan -> no fill-driven band"})
    };
    let factor = m.dig_energy_factor.unwrap_or(1.0);
    let uncertainty = json!({
        "energy_MJ_band": band,
        "sources": {
            "dig_rate": {"quantified": true, "into": "energy", "band_MJ": band},
            "material": {"quantified": (factor - 1.0).abs() > 0.0, "into": "energy", "dig_energy_factor": factor},
            "localization": {"quantified": true, "into": "feasibility", "corridor_margin_m": p.localization_margin_m},
            "dem": {"quantified": true, "into": "feasibility", "cell_sigma_m": p.dem_cell_sigma_m},
            "drum_fill": drum_fill,
            "slip": {"quantified": false, "into": "time/energy",
                     "note": "slip moduli are [CALIB]; plan band oracle-gated (FIX-1/2)"},
            "power_window": {"quantified": !m.mission_windows.is_empty(), "into": "time",
                             "note": "EP-04 mission-clock windows gate timing"},
        },
    });
    let meta = &plan.meta;
    json!({
        "cut_kg": sum_kind(OrderKind::Cut, &|o| cut_bank_density(o, body_density, profile)),
        "fill_kg": sum_kind(OrderKind::Fill, &|_| body_density),
        "sinter_kg": sum_kind(OrderKind::Sinter, &|_| body_density),
        "surplus_kg": plan.surplus_kg,
        "waypoint_sequence": plan.trips.iter().filter(|t| t.kind == TripKind::Goto)
            .filter_map(|t| t.actions.iter().next()).collect::<Vec<_>>(),
        "deficit_kg": imported,
        "import_kg": imported,
        "offload_energy_J": plan.trips.iter().map(|t| t.offload_e).sum::<f64>(),
        "drum_cycles": drum_cycles,
        "cut_passes": cut_passes,
        "dig_energy_bounds_MJ": band,
        "plan_uncertainty": uncertainty,
        "lift_energy_J": plan.trips.iter().map(|t| t.lift_e).sum::<f64>(),
        "routed_haul": true,
        "traverse_cap_deg": meta.traverse_cap_deg,
        "haul_detour_frac": if meta.straight_haul_m > 1e-9 {
            meta.routed_haul_m / meta.straight_haul_m - 1.0
        } else {
            0.0
        },
        "n_keepouts": m.keepouts.len(),
        "keepout_conflicts": m.orders.iter()
            .map(|o| m.keepouts.iter().filter(|k| k.contains(o.x, o.y)).count()).sum::<usize>(),
        "return_to_lander": return_to_lander(m, ctx, p),
        "relocalization": relocalization(plan.totals.distance_m, ctx.rover_mass_kg, p),
    })
}

/// At the plan's furthest point from the lander (the charger when none is given), does a full usable charge
/// cover the buffered drive back?
fn return_to_lander(m: &Mission, ctx: &Context, p: &ReportParams) -> Value {
    let lander = m.lander.unwrap_or(m.charger);
    let reach = m
        .orders
        .iter()
        .map(|o| (o.x, o.y))
        .chain([m.charger])
        .map(|q| dist(lander, q))
        .fold(0.0, f64::max);
    let buffer = m.return_buffer_frac.unwrap_or(p.default_return_buffer_frac);
    let energy = reach * ctx.drive_j_per_m;
    let with_buffer = energy * (1.0 + buffer);
    let remaining = ctx.usable_j();
    let margin = remaining - with_buffer;
    json!({
        "feasible": margin >= 0.0, "return_distance_m": round(reach, 2), "return_energy_J": round(energy, 1),
        "buffer_frac": buffer, "reserve_with_buffer_J": round(with_buffer, 1), "remaining_J": round(remaining, 1),
        "margin_J": round(margin, 1), "lander_xy": [round(lander.0, 1), round(lander.1, 1)],
    })
}

/// Fix stops so dead-reckoning drift over `traverse_m` never exceeds the tolerance; each fix is a standstill
/// arm raise of the rover's own mass at the body's gravity.
fn relocalization(traverse_m: f64, mass_kg: f64, p: &ReportParams) -> Value {
    let per_fix = mass_kg * p.gravity_ms2 * p.arm_lift_height_m / p.arm_lift_efficiency;
    let max_run = p.relocalize_drift_tol_m / p.drift_frac;
    // fixes strictly within the traverse
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let n = ((traverse_m - 1e-9) / max_run).floor().max(0.0) as u64;
    #[allow(clippy::cast_precision_loss)] // a fix count
    let nf = n as f64;
    #[allow(clippy::cast_precision_loss)]
    let at: Vec<f64> = (1..=n).map(|i| round(i as f64 * max_run, 3)).collect();
    let max_drift = p.drift_frac * if n >= 1 { max_run } else { traverse_m };
    json!({
        "n_fixes": n, "fix_distances_m": at, "max_run_m": round(max_run, 3),
        "total_time_s": round(nf * p.fix_maneuver_s, 1), "total_energy_J": round(nf * per_fix, 1),
        "per_fix_energy_J": round(per_fix, 2), "max_drift_m": round(max_drift, 4),
    })
}

/// One separable energy ledger over the plan's headline energy; `matches_total` is false when a stranded plan
/// credits only part of the planned work.
#[must_use]
pub fn energy_ledger(plan: &Plan, ctx: &Context) -> Value {
    let t = &plan.totals;
    let sum = |f: fn(&crate::trips::Trip) -> f64| plan.trips.iter().map(f).sum::<f64>();
    let haul_m = sum(|t| t.haul_m);
    let terms = [
        (
            "drive",
            (t.distance_m - haul_m).max(0.0) * ctx.drive_j_per_m + sum(|t| t.drive_e),
        ),
        ("slope_slip", sum(|t| t.slip_e)),
        ("payload_lift", sum(|t| t.lift_e)),
        ("dig", sum(|t| t.dig_e)),
        ("offload", sum(|t| t.offload_e)),
        ("sinter", 0.0),
        ("arm_drum", 0.0),
        ("observation", 0.0),
        ("led", 0.0),
        ("thermal", 0.0),
        ("comms", 0.0),
        ("compute", 0.0),
        ("survival", t.survival_energy_j),
    ];
    let total: f64 = terms.iter().map(|(_, v)| v).sum();
    let recharge: f64 = plan
        .tl
        .iter()
        .filter(|s| s.kind == SpanKind::Charge)
        .map(|s| (s.batt1 - s.batt0).max(0.0))
        .sum();
    // Python math.isclose(rel_tol=1e-9, abs_tol=1e-6)
    let close = (total - t.energy_j).abs() <= (1e-9 * total.abs().max(t.energy_j.abs())).max(1e-6);
    json!({
        "terms_J": terms.iter().map(|(k, v)| ((*k).to_owned(), json!(v))).collect::<serde_json::Map<_, _>>(),
        "recharge_J": recharge,
        "sum_J": total,
        "matches_total": close,
        "unmodeled": {
            "arm_drum": "not separately metered: bucket-drum excavation work is inside `dig` (the drum IS the dig \
                         implement, ipex_specs); discrete arm-raise relocalization fixes are scheduled + priced in \
                         totals['relocalization'] (#96), not folded into energy_J",
            "observation": "sensing/camera draw is not modeled (no sourced per-sensor power for IPEx)",
            "led": "no LED/illumination load in the modeled IPEx TRL-5 power budget",
            "thermal": "heater draw is not separately metered: the K11c survival idle draw (IDLE_POWER_W) carries \
                        the whole idle/heater load when set; cold-pack capacity loss enters as the EP-05 thermal \
                        derate (capacity, not consumption)",
            "comms": "radio/telemetry draw is not modeled (no sourced comms power for IPEx)",
            "compute": "avionics/compute draw is not modeled (no sourced compute power for IPEx)",
        },
    })
}
