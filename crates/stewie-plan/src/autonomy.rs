//! The closed-loop autonomy overlay `/plan` reports (RW-55b14c; Python `lode.autonomy.run_closed_loop` and
//! `routers.plan._autonomy_perception`, with `lode.adaptive_planner`'s learned slip pricing). The loop walks the one
//! canonical plan's trips: it gates digs on pose confidence and on the worksite's map coverage, executes each leg on
//! the real DEM (slope from the elevation gain, weight-coupled slip, the gravity climb), dead-reckons the believed
//! pose with odometry drift, and fuses real fixes: a DEM scan-match of the terrain under the rover (Python
//! `dart.localization.register_to_dem` via `slam_seam.dem_position_fix`, the slice of RW-41 this needs) or, on flat
//! ground, the lander's `AprilTag` beacon; the dock at the charger closes it. What the Python computes but `/plan`
//! never reports (the per-leg fault records, the built-terrain hazard checks, the dense-render gate, which is off on
//! this path) is not ported here.

use serde::Deserialize;
use serde_json::{Value, json};
use stewie_physics::soil::SoilParams;
use stewie_traverse::haul::elevation_gain_m;
use stewie_traverse::route::Dem;
use stewie_twin::numpy::round;

use crate::assemble::Plan;
use crate::mission::Mission;
use crate::trips::{Context, SlipModel, slip_at};

/// Along-track odometry drift per metre [ASSUMPTION] (Python `ODOM_DRIFT_FRAC`).
const ODOM_DRIFT_FRAC: f64 = 0.05;
/// The map-relative fix precision `/plan` runs the loop with (Python `perception_sigma_m=0.10`).
const PERCEPTION_SIGMA_M: f64 = 0.10;
/// Pose sigma above which a dig waits for more observations (Python `dig_sigma_gate_m`).
const DIG_SIGMA_GATE_M: f64 = 0.20;
/// A-priori energy-model error per leg (Python's `0.12`).
const ENERGY_MODEL_SIGMA_FRAC: f64 = 0.12;
/// The FDC drum-fill mass-inference MPE `/plan` reports [%] (Python's literal `7.4`).
const DRUM_FILL_UNCERTAINTY_PCT: f64 = 7.4;

/// The map channel's sourced constants (Python `dart.map_channel`).
#[derive(Debug, Clone, Copy, Deserialize, PartialEq)]
pub struct MapChannel {
    pub onboard_stereo_sigma_m: f64,
    pub prior_sigma_m: f64,
    pub sensor_radius_m: f64,
    pub coverage_dig_gate: f64,
    pub observe_dwell_s: f64,
    pub worksite_margin_m: f64,
}

/// The learned slip-energy inflation model (Python `adaptive_planner.learned_model()`, trained once from controlled
/// drives; its fitted form).
#[derive(Debug, Clone, Copy, Deserialize, PartialEq)]
pub struct LearnedModel {
    /// `polyval` order: `a s^2 + b s + c`.
    pub coef: [f64; 3],
    pub x_min: f64,
    pub x_max: f64,
    pub distinct_slopes: usize,
    /// The lowest training slope that entrapped; at or beyond it the model predicts infinity.
    pub entrap_slope: Option<f64>,
}

impl LearnedModel {
    /// The predicted true-over-flat energy inflation at `slope_deg` (Python `InflationModel.predict`).
    #[must_use]
    pub fn predict(&self, slope_deg: f64) -> f64 {
        if self.entrap_slope.is_some_and(|e| slope_deg >= e) {
            return f64::INFINITY;
        }
        if self.distinct_slopes < 3 {
            return 1.0;
        }
        let s = slope_deg.clamp(self.x_min, self.x_max);
        // numpy `polyval`: Horner from zero, each step a separate multiply and add
        let mut y = 0.0;
        for c in self.coef {
            y = y * s + c;
        }
        y.max(1.0)
    }
}

/// The overlay's tables (`autonomy.json`).
#[derive(Debug, Clone, Copy, Deserialize, PartialEq)]
pub struct Tables {
    pub map_channel: MapChannel,
    pub learned_model: LearnedModel,
}

/// What the loop needs beyond the plan.
#[derive(Debug, Clone, Copy)]
pub struct Inputs<'a> {
    pub ctx: &'a Context,
    pub gravity_ms2: f64,
    pub soil: &'a SoilParams,
    pub slip: &'a SlipModel,
    pub map: &'a MapChannel,
    pub model: &'a LearnedModel,
}

/// The believed state (Python `Belief`), only what `/plan` reports.
#[derive(Debug, Clone, Copy)]
struct Belief {
    x: f64,
    y: f64,
    pos_sigma_m: f64,
    energy_sigma_j: f64,
}

/// Scalar Kalman fusion of a prior with a measurement of variance `r` (Python `_kf_update`).
fn kf(mu: f64, var: f64, z: f64, r: f64) -> (f64, f64) {
    if !var.is_finite() {
        return (z, r);
    }
    if r <= 0.0 {
        return (z, 0.0);
    }
    if var <= 0.0 {
        return (mu, 0.0);
    }
    let k = var / (var + r);
    (mu + k * (z - mu), (1.0 - k) * var)
}

/// Fuse a pose fix (Python `update_pose`).
fn update_pose(b: &mut Belief, (fx, fy): (f64, f64), sigma: f64) {
    let (x, vx) = kf(b.x, b.pos_sigma_m.powi(2), fx, sigma.powi(2));
    let (y, vy) = kf(b.y, b.pos_sigma_m.powi(2), fy, sigma.powi(2));
    b.x = x;
    b.y = y;
    b.pos_sigma_m = vx.max(vy).max(0.0).sqrt();
}

/// Dead-reckon to `to` after driving `drive_m` (Python `predict` with no energy spend).
fn predict(b: &mut Belief, to: (f64, f64), drive_m: f64) {
    b.x = to.0;
    b.y = to.1;
    b.pos_sigma_m = (b.pos_sigma_m.powi(2) + (ODOM_DRIFT_FRAC * drive_m).powi(2)).sqrt();
}

/// A grid index of `v / cell` the Python's `int(round(...))` way (ties to even).
#[allow(clippy::cast_possible_truncation)] // a rounded grid coordinate
fn grid(v: f64) -> i64 {
    v.round_ties_even() as i64
}

/// numpy's `mean` of a `side x side` window of `z` starting at `(r0, c0)`: a strided view reduces row by row, each
/// row's pairwise sum added in turn.
#[allow(clippy::cast_precision_loss)] // a window count
fn view_mean(z: &[f64], width: usize, (r0, c0): (usize, usize), side: usize) -> f64 {
    let mut acc = 0.0;
    for r in r0..r0 + side {
        acc += stewie_twin::numpy::sum(&z[r * width + c0..r * width + c0 + side]);
    }
    acc / (side * side) as f64
}

/// The window, copied row-major.
fn window(z: &[f64], width: usize, (r0, c0): (usize, usize), side: usize) -> Vec<f64> {
    (r0..r0 + side)
        .flat_map(|r| z[r * width + c0..r * width + c0 + side].iter().copied())
        .collect()
}

/// Register the terrain under the rover onto the prior DEM near a dead-reckoned guess (Python `register_to_dem` with
/// `dem_position_fix`): the mean-removed SSD over integer shifts within five cells, the best shift preferring the
/// smaller `|shift|` on a tie, confidence against the best rival outside the best's neighbourhood. `None` when no
/// candidate lies fully inside the map or the match is too ambiguous (confidence below 0.05).
fn dem_fix(
    dem: &Dem<'_>,
    true_pose: (f64, f64),
    guess: (f64, f64),
    base_sigma_m: f64,
) -> Option<((f64, f64), f64)> {
    dem_position_fix(dem, true_pose, guess, base_sigma_m).map(|f| (f.xy, f.sigma))
}

/// A terrain-relative position fix.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DemFix {
    /// The recovered position in the order frame [m].
    pub xy: (f64, f64),
    pub sigma: f64,
    pub confidence: f64,
    pub residual_rmse_m: f64,
    pub shift_cells: (i64, i64),
}

/// The DEM scan-match fix of the terrain under `true_pose` near the dead-reckoned `guess` (Python
/// `autonomy._dem_terrain_fix`); see [`dem_fix`].
#[must_use]
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_wrap,
    clippy::cast_sign_loss,
    clippy::cast_possible_truncation,
    clippy::many_single_char_names,
    clippy::float_cmp
)] // grid arithmetic in the Python's names; the Python's exact SSD tie test
pub fn dem_position_fix(
    dem: &Dem<'_>,
    true_pose: (f64, f64),
    guess: (f64, f64),
    base_sigma_m: f64,
) -> Option<DemFix> {
    const HALF: i64 = 16;
    const SEARCH: i64 = 5;
    const MIN_CONFIDENCE: f64 = 0.05;
    let (ox, oy, cell) = (dem.origin.0, dem.origin.1, dem.cell_m);
    let (h, w) = (dem.height as i64, dem.width as i64);
    let (tr, tc) = (
        grid((oy + true_pose.1) / cell),
        grid((ox + true_pose.0) / cell),
    );
    if !(HALF <= tr && tr < h - HALF && HALF <= tc && tc < w - HALF) {
        return None;
    }
    let side = (2 * HALF + 1) as usize;
    let at = |r: i64, c: i64| ((r - HALF) as usize, (c - HALF) as usize);
    // the observed patch is an in-bounds view: numpy reduces its mean row by row
    let obs_mean = view_mean(dem.z, dem.width, at(tr, tc), side);
    let observed = window(dem.z, dem.width, at(tr, tc), side);
    let (gr, gc) = (grid((oy + guess.1) / cell), grid((ox + guess.0) / cell));
    let g = stewie_perceive::slam_seam::Grid {
        z: dem.z,
        rows: dem.height,
        cols: dem.width,
        cell_m: cell,
    };
    let reg = stewie_perceive::slam_seam::register_to_dem(
        &g,
        &observed,
        obs_mean,
        HALF,
        (gr, gc),
        SEARCH,
    )?;
    let (confidence, (br, bc)) = (reg.confidence, reg.shift_cells);
    if confidence < MIN_CONFIDENCE {
        return None;
    }
    let (r, c) = ((gr + br) as f64, (gc + bc) as f64);
    Some(DemFix {
        xy: ((c - ox / cell) * cell, (r - oy / cell) * cell),
        sigma: base_sigma_m / MIN_CONFIDENCE.max(confidence),
        confidence,
        residual_rmse_m: reg.residual_rmse_m,
        shift_cells: (br, bc),
    })
}

/// The lander or charger `AprilTag` beacon fix (Python `_beacon_fix`): bearing and range quantized to the camera's
/// pixel grid, the sigma growing with range; `None` at the beacon or beyond 60 m.
fn beacon_fix(beacon: (f64, f64), true_pose: (f64, f64)) -> Option<((f64, f64), f64)> {
    const MAX_RANGE_M: f64 = 60.0;
    const FX_PX: f64 = 900.0;
    const SIGMA_PX: f64 = 1.0;
    const TAG_SIZE_M: f64 = 0.5;
    let (dx, dy) = (true_pose.0 - beacon.0, true_pose.1 - beacon.1);
    let rng = dx.hypot(dy);
    if !(1e-3..=MAX_RANGE_M).contains(&rng) {
        return None;
    }
    let bearing_res = SIGMA_PX / FX_PX;
    let px_size = (TAG_SIZE_M * FX_PX / rng).max(1e-6);
    let range_res = rng / px_size * SIGMA_PX;
    let b_q = (dy.atan2(dx) / bearing_res).round_ties_even() * bearing_res;
    let r_q = if range_res > 0.0 {
        (rng / range_res).round_ties_even() * range_res
    } else {
        rng
    };
    let xy = (beacon.0 + r_q * b_q.cos(), beacon.1 + r_q * b_q.sin());
    Some((xy, (bearing_res * rng).hypot(range_res).max(1e-3)))
}

/// The worksite box the map channel scores (Python `worksite_bbox`): every order footprint plus the margin.
fn worksite_bbox(m: &Mission, margin: f64) -> (f64, f64, f64, f64) {
    if m.orders.is_empty() {
        return (0.0, 0.0, 1.0, 1.0);
    }
    let (mut x0, mut y0, mut x1, mut y1) = (
        f64::INFINITY,
        f64::INFINITY,
        f64::NEG_INFINITY,
        f64::NEG_INFINITY,
    );
    for o in &m.orders {
        let h = o.footprint_m2.powf(0.5) / 2.0;
        x0 = x0.min(o.x - h);
        x1 = x1.max(o.x + h);
        y0 = y0.min(o.y - h);
        y1 = y1.max(o.y + h);
    }
    (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
}

/// The cell centres of a 1 m grid over `bbox` (Python `_grid`).
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid counts
fn grid_centres((x0, y0, x1, y1): (f64, f64, f64, f64), cell: f64) -> (Vec<f64>, Vec<f64>) {
    let w = (((x1 - x0) / cell).ceil() as usize).max(1);
    let h = (((y1 - y0) / cell).ceil() as usize).max(1);
    let cx = (0..w).map(|i| x0 + (i as f64 + 0.5) * cell).collect();
    let cy = (0..h).map(|j| y0 + (j as f64 + 0.5) * cell).collect();
    (cx, cy)
}

fn observed(x: f64, y: f64, stations: &[(f64, f64)], r: f64) -> bool {
    stations
        .iter()
        .any(|&(sx, sy)| (x - sx).powi(2) + (y - sy).powi(2) <= r.powi(2))
}

/// The fraction of a disk around `site` already observed from `stations` (Python `local_coverage`); zero when the
/// disk holds no cell (fail closed).
#[allow(clippy::cast_precision_loss)] // cell counts
fn local_coverage(stations: &[(f64, f64)], site: (f64, f64), r: f64) -> f64 {
    let (cx, cy) = grid_centres((site.0 - r, site.1 - r, site.0 + r, site.1 + r), 1.0);
    let (mut inside, mut seen) = (0_usize, 0_usize);
    for &y in &cy {
        for &x in &cx {
            if (x - site.0).powi(2) + (y - site.1).powi(2) <= r.powi(2) {
                inside += 1;
                seen += usize::from(observed(x, y, stations, r));
            }
        }
    }
    if inside == 0 {
        0.0
    } else {
        seen as f64 / inside as f64
    }
}

/// The executed route's map-channel reward (Python `map_channel_score`): the worksite's observed fraction and
/// residual mean uncertainty, with its counts and the constants it used.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct MapScore {
    pub coverage: f64,
    pub observed_cells: usize,
    pub total_cells: usize,
    pub mean_uncertainty_m: f64,
    pub onboard_sigma_m: f64,
    pub sensor_radius_m: f64,
    pub n_stations: usize,
}

impl MapScore {
    /// The Python's dict (its cell is 1 m; the dense render tier is not available here).
    #[must_use]
    pub fn to_value(&self) -> Value {
        json!({"coverage": self.coverage, "observed_cells": self.observed_cells, "total_cells": self.total_cells,
               "mean_uncertainty_m": self.mean_uncertainty_m, "observed_uncertainty_m": self.onboard_sigma_m,
               "sensor_radius_m": self.sensor_radius_m, "cell_m": 1.0, "n_stations": self.n_stations,
               "dense_rmse_available": false})
    }
}

#[allow(clippy::cast_precision_loss)] // cell counts
fn map_channel(m: &Mission, stations: &[(f64, f64)], mc: &MapChannel) -> MapScore {
    let (cx, cy) = grid_centres(worksite_bbox(m, mc.worksite_margin_m), 1.0);
    let mut sigma = Vec::with_capacity(cx.len() * cy.len());
    let mut seen = 0_usize;
    for &y in &cy {
        for &x in &cx {
            let o = observed(x, y, stations, mc.sensor_radius_m);
            seen += usize::from(o);
            sigma.push(if o {
                mc.onboard_stereo_sigma_m
            } else {
                mc.prior_sigma_m
            });
        }
    }
    let n = sigma.len() as f64;
    MapScore {
        coverage: seen as f64 / n,
        observed_cells: seen,
        total_cells: sigma.len(),
        mean_uncertainty_m: stewie_twin::numpy::sum(&sigma) / n,
        onboard_sigma_m: mc.onboard_stereo_sigma_m,
        sensor_radius_m: mc.sensor_radius_m,
        n_stations: stations.len(),
    }
}

/// One executed leg.
#[derive(Debug, Clone, PartialEq)]
pub struct Leg {
    pub label: String,
    pub nominal_j: f64,
    pub true_j: f64,
    pub dig_e: f64,
    pub slope_deg: f64,
    pub slip: f64,
    pub energy_sigma_j: f64,
    pub believed: (f64, f64),
    pub truth: (f64, f64),
    pub pos_sigma_m: f64,
    pub fix: &'static str,
}

/// The closed loop over one canonical plan (Python `lode.autonomy.run_closed_loop`): the executed legs and the
/// loop's counters.
#[derive(Debug, Clone, PartialEq)]
pub struct ClosedLoop {
    pub legs: Vec<Leg>,
    pub perception_fixes: u64,
    pub observe_more: u64,
    pub map_observe_more: u64,
    pub survey_time_s: f64,
    pub map_channel: MapScore,
    /// The final believed pose sigma [m].
    pub pos_sigma_m: f64,
    /// The final believed pose (home at the charger, with the drive home's odometry drift).
    pub final_xy: (f64, f64),
    /// The final energy sigma [J].
    pub energy_sigma_j: f64,
}

impl ClosedLoop {
    /// The executed legs as the Python's leg records: the energies, the drive's slope and slip, the believed and
    /// true poses (builtin-rounded), the fix kind, and the leg's faults against the pack `reserve_frac`. The belief
    /// spends no energy (the plant owns it), so the state of charge stays 1.0; no dense perception runs, so no dig
    /// is deferred.
    #[must_use]
    pub fn leg_records(&self, reserve_frac: f64) -> Vec<Value> {
        use stewie_traverse::nav::{Telemetry, classify_faults, py_round};
        self.legs
            .iter()
            .map(|l| {
                let t = Telemetry { slip: Some(l.slip), battery_frac: Some(1.0), loc_sigma_m: Some(l.pos_sigma_m),
                                    ..Telemetry::default() };
                json!({"leg": l.label, "nominal_J": l.nominal_j, "true_J": l.true_j, "dig_e": l.dig_e, "soc": 1.0,
                       "slope_deg": l.slope_deg, "slip": l.slip, "energy_sigma_J": l.energy_sigma_j,
                       "bx": py_round(l.believed.0, 2), "by": py_round(l.believed.1, 2),
                       "tx": py_round(l.truth.0, 2), "ty": py_round(l.truth.1, 2),
                       "pos_sigma_m": py_round(l.pos_sigma_m, 3), "fix": l.fix,
                       "faults": classify_faults(&t, reserve_frac), "dense_deferred": false})
            })
            .collect()
    }
}

/// Walk `plan`'s trips on `dem` (Python `run_closed_loop`): gate digs on the worksite's map coverage, execute
/// each leg (slope from the elevation gain, weight-coupled slip, the gravity climb), and dead-reckon with odometry
/// drift. With `perception` (a fix precision [m]) the loop also dwells until the pose is confident enough to dig,
/// fuses a DEM scan-match or the lander beacon per leg, and docks at the charger as a final fix; without it the
/// belief only drifts (a training session's run).
///
/// # Errors
/// The slip ladder refusing a leg's inputs.
#[allow(clippy::too_many_lines)] // the Python's loop, step by step
pub fn run_closed_loop(
    m: &Mission,
    plan: &Plan,
    dem: &Dem<'_>,
    inp: &Inputs<'_>,
    perception: Option<f64>,
) -> Result<ClosedLoop, String> {
    let ctx = inp.ctx;
    let mut b = Belief {
        x: m.charger.0,
        y: m.charger.1,
        pos_sigma_m: 0.5,
        energy_sigma_j: 0.0,
    };
    let (mut observe_more, mut map_observe_more, mut fixes, mut survey_s) =
        (0_u64, 0_u64, 0_u64, 0.0);
    let mut stations = vec![m.charger];
    let mut legs: Vec<Leg> = Vec::new();
    for tr in &plan.trips {
        let is_dig = tr.dig_e > 0.0;
        if let Some(sigma) = perception
            && is_dig
        {
            while b.pos_sigma_m > DIG_SIGMA_GATE_M {
                let here = (b.x, b.y);
                update_pose(&mut b, here, sigma);
                observe_more += 1;
            }
        }
        if is_dig
            && local_coverage(&stations, tr.site, inp.map.sensor_radius_m)
                < inp.map.coverage_dig_gate
        {
            survey_s += inp.map.observe_dwell_s;
            map_observe_more += 1;
        }
        stations.push(tr.site);
        let pose = (b.x, b.y);
        let drive_m = (pose.0 - tr.site.0).hypot(pose.1 - tr.site.1);
        // the Python's left-to-right sums: drive, dig, sinter (none), haul, lift
        let nominal_j = drive_m * ctx.drive_j_per_m + tr.dig_e + 0.0 + tr.haul_e + tr.lift_e;
        let dh = elevation_gain_m(dem, pose, tr.site).unwrap_or(0.0);
        let slope_deg = if drive_m > 1e-9 {
            dh.abs().atan2(drive_m).to_degrees()
        } else {
            0.0
        };
        let haul_mass = tr.mass_kg.max(0.0).min(ctx.drum_kg);
        let slip = slip_at(
            slope_deg,
            haul_mass,
            ctx.rover_mass_kg,
            inp.gravity_ms2,
            inp.soil,
            inp.slip,
        )?;
        let true_drive = drive_m * ctx.drive_j_per_m / (1.0 - slip)
            + (ctx.rover_mass_kg + haul_mass) * inp.gravity_ms2 * dh.max(0.0);
        let true_j = true_drive + tr.dig_e + 0.0 + tr.haul_e + tr.lift_e;
        let truth = tr.site;
        predict(
            &mut b,
            (truth.0 + ODOM_DRIFT_FRAC * drive_m, truth.1),
            drive_m,
        );
        let mut kind = "none";
        if let Some(sigma) = perception {
            let fix = match dem_fix(dem, truth, (b.x, b.y), sigma) {
                Some(f) => {
                    kind = "dem";
                    Some(f)
                }
                None => {
                    beacon_fix(m.lander.unwrap_or(m.charger), truth).inspect(|_| kind = "beacon")
                }
            };
            if let Some((xy, sig)) = fix {
                update_pose(&mut b, xy, sig);
                fixes += 1;
            }
        }
        b.energy_sigma_j =
            (b.energy_sigma_j.powi(2) + (ENERGY_MODEL_SIGMA_FRAC * nominal_j).powi(2)).sqrt();
        legs.push(Leg {
            label: tr.label.clone(),
            nominal_j,
            true_j,
            dig_e: tr.dig_e,
            slope_deg,
            slip,
            energy_sigma_j: b.energy_sigma_j,
            believed: (b.x, b.y),
            truth,
            pos_sigma_m: b.pos_sigma_m,
            fix: kind,
        });
    }
    // drive home and dock at the charger (a known-landmark fix)
    let home_m = (b.x - m.charger.0).hypot(b.y - m.charger.1);
    predict(
        &mut b,
        (m.charger.0 + ODOM_DRIFT_FRAC * home_m, m.charger.1),
        home_m,
    );
    if let Some(sigma) = perception {
        update_pose(&mut b, m.charger, sigma);
        fixes += 1;
    }
    Ok(ClosedLoop {
        map_channel: map_channel(m, &stations, inp.map),
        legs,
        perception_fixes: fixes,
        observe_more,
        map_observe_more,
        survey_time_s: survey_s,
        pos_sigma_m: b.pos_sigma_m,
        final_xy: (b.x, b.y),
        energy_sigma_j: b.energy_sigma_j,
    })
}

/// The `/plan` response's `autonomy` and `perception` blocks for `plan` on `dem` (Python `_autonomy_perception`:
/// the closed loop with a 0.10 m fix).
///
/// # Errors
/// The slip ladder refusing a leg's inputs.
pub fn autonomy_perception(
    m: &Mission,
    plan: &Plan,
    dem: &Dem<'_>,
    inp: &Inputs<'_>,
) -> Result<(Value, Value), String> {
    let cl = run_closed_loop(m, plan, dem, inp, Some(PERCEPTION_SIGMA_M))?;
    let (legs, fixes, observe_more, map_observe_more) = (
        &cl.legs,
        cl.perception_fixes,
        cl.observe_more,
        cl.map_observe_more,
    );
    let (coverage, mean_uncertainty) = (cl.map_channel.coverage, cl.map_channel.mean_uncertainty_m);
    // the Python's builtin `sum`, from +0.0
    let nominal = legs.iter().fold(0.0, |a, l| a + l.nominal_j);
    let truth_j = legs.iter().fold(0.0, |a, l| a + l.true_j);
    // the learned model re-prices only the plain drive portion (the legs carry dig energy as their fixed part)
    let learned = legs.iter().fold(0.0, |a, l| {
        let fixed_j = l.dig_e + 0.0 + 0.0; // dig; the legs carry no lift or haul term
        a + (fixed_j + (l.nominal_j - fixed_j).max(0.0) * inp.model.predict(l.slope_deg))
    });
    let max_slip = legs.iter().map(|l| l.slip).fold(0.0, f64::max);
    let autonomy = json!({
        "completed": true, "n_trips": plan.trips.len(), "n_legs": legs.len(), "recharges": plan.totals.charges,
        "replans": 0, "perception_fixes": fixes, "observe_more": observe_more, "final_soc": round(1.0, 3),
        "max_slip": round(max_slip, 3),
        "true_vs_nominal_energy": if nominal == 0.0 { Value::Null } else { json!(round(truth_j / nominal, 3)) },
        "energy_naive_kj": round(nominal / 1e3, 1), "energy_learned_kj": round(learned / 1e3, 1),
        "energy_actual_kj": round(truth_j / 1e3, 1),
    });
    let leg_e_sig = legs.iter().map(|l| l.energy_sigma_j).fold(0.0, f64::max);
    let count = |k: &str| legs.iter().filter(|l| l.fix == k).count();
    let perception = json!({
        "pose_sigma_m": round(cl.pos_sigma_m, 2), "map_fixes": fixes, "observe_more_before_dig": observe_more,
        "fix_sigma_m": PERCEPTION_SIGMA_M, "energy_model_sigma_J": round(leg_e_sig, 1),
        "drum_fill_uncertainty_pct": DRUM_FILL_UNCERTAINTY_PCT,
        "map_coverage": round(coverage, 3), "map_uncertainty_m": round(mean_uncertainty, 2),
        "map_observe_more_before_dig": map_observe_more, "map_survey_time_s": round(cl.survey_time_s, 1),
        "localization": {
            "trajectory": legs.iter().map(|l| json!({
                "est": [round(l.believed.0, 2), round(l.believed.1, 2)],
                "true": [round(l.truth.0, 2), round(l.truth.1, 2)],
                "sigma": round(l.pos_sigma_m, 3), "fix": l.fix})).collect::<Vec<_>>(),
            "fix_kinds": {"dem": count("dem"), "beacon": count("beacon"), "none": count("none")},
        },
        "note": "perception-in-the-loop: a map/landmark pose fix per leg bounds dead-reckoning drift; the dig-ready \
                 gate observes more before digging when the pose is uncertain OR the dig site's local map coverage \
                 is low. map_coverage is the onboard-observability tier (what the route sees) -- the dense \
                 observed-map RMSE is the gated render/COLMAP tier (see /render).",
    });
    Ok((autonomy, perception))
}
