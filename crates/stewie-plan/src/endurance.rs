//! The endurance report (RW-55b14b; Python `lode.planner_endurance`): single-charge driving range (flat, and at the
//! work area's median slope with its slip), the per-site power regime with cold derating, the body's operating
//! timescale, the IPEx `ConOps` scale, and the DEM-grounded one-charge reach from the charger. It does not affect
//! sequencing, the plan IR or feasibility (D-R91); `/plan` returns it.

use std::cmp::Reverse;
use std::collections::{BTreeMap, BinaryHeap};

use serde::Deserialize;
use serde_json::{Value, json};
use stewie_physics::soil::SoilParams;
use stewie_traverse::route::Dem;

use crate::trips::{Context, SlipModel, slip_at};

/// A body's operating timescale (Python `planner_model.BODY_TIMESCALE`).
#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Timescale {
    pub solar_day_h: f64,
    pub daylight_h: f64,
    pub op_window_h: (f64, f64),
    pub day_label: String,
}

/// The IPEx `ConOps` scale (Python `ipex_specs`).
#[derive(Debug, Clone, Copy, Deserialize, PartialEq)]
pub struct Conops {
    pub traverse_km: f64,
    pub mission_days: f64,
    pub total_regolith_kg: (f64, f64),
}

/// The endurance tables (`endurance.json`).
#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct Tables {
    pub body_timescale: BTreeMap<String, Timescale>,
    pub default_timescale: Timescale,
    pub conops: Conops,
    pub power_kinds: Vec<String>,
}

impl Tables {
    fn timescale(&self, body: &str) -> &Timescale {
        self.body_timescale
            .get(body)
            .unwrap_or(&self.default_timescale)
    }
}

/// What the report needs beyond the vehicle's context.
#[derive(Debug, Clone, Copy)]
pub struct Inputs<'a> {
    pub body: &'a str,
    /// The body's gravity [m/s^2].
    pub gravity_ms2: f64,
    /// The gravity the Python's slip ladder defaults to (lunar), whatever the body.
    pub slip_gravity_ms2: f64,
    /// The configured recharge power [W] (the Python's module `CHARGE_W`).
    pub charge_w: f64,
    /// The IPEx pack [J]: the Python's module `BATTERY_J`, which the power regime and the reach field read.
    pub ipex_battery_j: f64,
    /// Slip energy multiplier versus tan(slope) [CALIB].
    pub slip_alpha: f64,
    pub soil: &'a SoilParams,
    pub slip: &'a SlipModel,
    pub tables: &'a Tables,
}

/// One-way driving distance on a single charge [m] (Python `single_charge_range_m`).
#[must_use]
pub fn single_charge_range_m(
    g: f64,
    slope_deg: f64,
    slip: f64,
    full_pack: bool,
    ctx: &Context,
) -> f64 {
    let usable = ctx.battery_j
        * if full_pack {
            1.0
        } else {
            1.0 - ctx.reserve_frac
        };
    let jpm = ctx.drive_j_per_m / (1.0 - slip).max(1e-6)
        + ctx.rover_mass_kg * g * slope_deg.max(0.0).to_radians().sin();
    usable / jpm
}

/// Usable pack fraction versus temperature [CALIB]: 1 at or above 0 C, about 1 % per degree below, floored at 0.5.
#[must_use]
pub fn thermal_derate(temp_c: Option<f64>) -> f64 {
    match temp_c {
        Some(t) if t < 0.0 => (1.0 + 0.01 * t).max(0.5),
        _ => 1.0,
    }
}

/// The per-site power model (Python `power_regime`): a PSR tower charges anytime; sunlit solar only in daylight.
///
/// # Errors
/// An unknown power kind, in the Python's words.
pub fn power_regime(kind: &str, temp_c: Option<f64>, inp: &Inputs<'_>) -> Result<Value, String> {
    if !inp.tables.power_kinds.iter().any(|k| k == kind) {
        let known = inp
            .tables
            .power_kinds
            .iter()
            .map(|k| format!("'{k}'"))
            .collect::<Vec<_>>()
            .join(", ");
        return Err(format!("unknown power kind '{kind}'; known: ({known})"));
    }
    let ts = inp.tables.timescale(inp.body);
    let (duty, avail) = if kind == "sunlit_solar" {
        (
            ts.daylight_h / ts.solar_day_h,
            format!(
                "daylight only (~{:.0} h / {:.0} h {})",
                ts.daylight_h, ts.solar_day_h, ts.day_label
            ),
        )
    } else {
        (
            1.0,
            "anytime (lander/tower budget; a PSR has no sun)".to_owned(),
        )
    };
    let derate = thermal_derate(temp_c);
    Ok(
        json!({"kind": kind, "charge_power_w": inp.charge_w, "duty_frac": duty, "effective_charge_w": inp.charge_w * duty,
              "availability": avail, "thermal_derate": derate, "usable_pack_J": inp.ipex_battery_j * derate,
              "day_label": ts.day_label, "daylight_h": ts.daylight_h, "solar_day_h": ts.solar_day_h}),
    )
}

/// The 8-neighbourhood of the routing costmap with each step's length in cells (Python `_ROUTE_NB`).
const NB: [(isize, isize, f64); 8] = [
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, std::f64::consts::SQRT_2),
    (-1, 1, std::f64::consts::SQRT_2),
    (1, -1, std::f64::consts::SQRT_2),
    (1, 1, std::f64::consts::SQRT_2),
];

/// A clamped grid index of an order-frame offset (the Python's `min(max(int(round(v / cell)), 0), n - 1)`).
#[allow(clippy::cast_possible_truncation)] // a rounded, clamped index
fn anchor_index(v: f64, cell: f64, stride: usize, n: usize) -> usize {
    let k = (v / cell).round_ties_even() as i64;
    let k = k.div_euclid(i64::try_from(stride).unwrap_or(1));
    usize::try_from(k.max(0))
        .unwrap_or(0)
        .min(n.saturating_sub(1))
}

/// A float with a total order, for the reach queue (the Python's heap orders `(energy, row, col)` tuples).
#[derive(Debug, Clone, Copy, PartialEq)]
struct Energy(f64);
impl Eq for Energy {}
impl PartialOrd for Energy {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(o))
    }
}
impl Ord for Energy {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        self.0.total_cmp(&o.0)
    }
}

/// The DEM-grounded one-charge reach (Python `reachable_radius_on_dem`): a Dijkstra drive-energy field from the
/// anchor over the DEM coarsened by `stride`, each edge `seg * drive * (1 + alpha tan slope)` plus the climb.
#[allow(clippy::cast_precision_loss, clippy::many_single_char_names)] // grid counts; the Python's names
fn reach(dem: &Dem<'_>, usable_j: f64, g: f64, ctx: &Context, inp: &Inputs<'_>) -> Value {
    const STRIDE: usize = 10;
    let (h, w) = (dem.height.div_ceil(STRIDE), dem.width.div_ceil(STRIDE));
    let zc = |r: usize, c: usize| dem.z[r * STRIDE * dem.width + c * STRIDE];
    let cc = dem.cell_m * STRIDE as f64;
    let ar = anchor_index(dem.origin.1, dem.cell_m, STRIDE, h);
    let ac = anchor_index(dem.origin.0, dem.cell_m, STRIDE, w);
    let mut energy = vec![f64::INFINITY; h * w];
    energy[ar * w + ac] = 0.0;
    let mut pq = BinaryHeap::from([Reverse((Energy(0.0), ar, ac))]);
    while let Some(Reverse((Energy(e), r, c))) = pq.pop() {
        if e > energy[r * w + c] {
            continue;
        }
        for (dr, dc, seg) in NB {
            let (Some(nr), Some(nc)) = (r.checked_add_signed(dr), c.checked_add_signed(dc)) else {
                continue;
            };
            if nr >= h || nc >= w {
                continue;
            }
            let dh = zc(nr, nc) - zc(r, c);
            let slope = dh.abs().atan2(seg * cc);
            let step = seg * cc * ctx.drive_j_per_m * (1.0 + inp.slip_alpha * slope.tan())
                + ctx.rover_mass_kg * g * dh.max(0.0);
            let ne = e + step;
            if ne < energy[nr * w + nc] {
                energy[nr * w + nc] = ne;
                pq.push(Reverse((Energy(ne), nr, nc)));
            }
        }
    }
    let (mut radius, mut count, mut worst) = (0.0_f64, 0_usize, None::<f64>);
    for r in 0..h {
        for c in 0..w {
            let e = energy[r * w + c];
            if e <= usable_j {
                count += 1;
                radius =
                    radius.max(((c as f64 - ac as f64) * cc).hypot((r as f64 - ar as f64) * cc));
            }
            if e.is_finite() {
                worst = Some(worst.map_or(e, |m| m.max(e)));
            }
        }
    }
    let worst = worst.unwrap_or(0.0);
    json!({"radius_m": radius, "area_m2": count as f64 * cc * cc, "tile_fully_reachable": count == h * w,
           "worst_cell_J": worst, "worst_cell_pack_frac": worst / inp.ipex_battery_j, "grid_cell_m": cc})
}

/// The median of `v` as numpy's (the mean of the two middle values of an even count).
fn median(mut v: Vec<f64>) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    v.sort_by(f64::total_cmp);
    let n = v.len();
    if n % 2 == 1 {
        v[n / 2]
    } else {
        f64::midpoint(v[n / 2 - 1], v[n / 2])
    }
}

/// The endurance report of a mission's vehicle (Python `endurance`).
///
/// # Errors
/// An unknown power kind, or the slip ladder refusing its inputs.
#[allow(clippy::cast_precision_loss)] // window sizes
pub fn endurance(
    ctx: &Context,
    dem: Option<&Dem<'_>>,
    power_site: &str,
    temp_c: Option<f64>,
    inp: &Inputs<'_>,
) -> Result<Value, String> {
    let g = inp.gravity_ms2;
    let sortie_m = single_charge_range_m(g, 0.0, 0.0, false, ctx); // one way, stopping at the operational floor
    let dur_h = sortie_m / ctx.drive_speed_ms / 3600.0;
    let mut out = json!({
        "pack_energy_MJ": ctx.battery_j / 1e6, "drive_power_w": ctx.drive_power_w, "flat_j_per_m": ctx.drive_j_per_m,
        "speed_ms": ctx.drive_speed_ms, "rover_mass_kg": ctx.rover_mass_kg, "g": g, "reserve_frac": ctx.reserve_frac,
        "range_flat_full_km": single_charge_range_m(g, 0.0, 0.0, true, ctx) / 1000.0,
        "range_flat_reserve_km": sortie_m / 1000.0,
        "duration_flat_h": dur_h,
    });
    out["power"] = power_regime(power_site, temp_c, inp)?;
    let ts = inp.tables.timescale(inp.body);
    out["timescale"] = json!({
        "solar_day_h": ts.solar_day_h, "daylight_h": ts.daylight_h, "op_window_h": [ts.op_window_h.0, ts.op_window_h.1],
        "day_label": ts.day_label, "body": inp.body, "sortie_h": dur_h, "sorties_per_window": ts.op_window_h.0 / dur_h,
        "spans_days": dur_h / ts.daylight_h, "fits_in_window": dur_h <= ts.op_window_h.1,
    });
    let cv = &inp.tables.conops;
    let drive_mj = cv.traverse_km * 1000.0 * ctx.drive_j_per_m / 1e6;
    let (lo, hi) = cv.total_regolith_kg;
    let dig = ctx.dig_j_per_kg;
    out["conops"] = json!({
        "traverse_km": cv.traverse_km, "mission_days": cv.mission_days, "regolith_t": [lo / 1000.0, hi / 1000.0],
        "drive_energy_MJ": drive_mj, "drive_packs": drive_mj * 1e6 / ctx.battery_j,
        "dig_energy_MJ": [lo * dig / 1e6, hi * dig / 1e6], "dig_packs": [lo * dig / ctx.battery_j, hi * dig / ctx.battery_j],
        "drums_dominate": lo * dig > cv.traverse_km * 1000.0 * ctx.drive_j_per_m,
    });
    if let Some(d) = dem {
        let (h, w) = (d.height, d.width);
        let rc = anchor_index(d.origin.1, d.cell_m, 1, h);
        let cc0 = anchor_index(d.origin.0, d.cell_m, 1, w);
        let r0 = rc.saturating_sub(200).min(h.saturating_sub(400));
        let c0 = cc0.saturating_sub(200).min(w.saturating_sub(400));
        let (wh, ww) = ((h - r0).min(400), (w - c0).min(400));
        let win: Vec<f64> = (r0..r0 + wh)
            .flat_map(|r| (c0..c0 + ww).map(move |c| (r, c)))
            .map(|(r, c)| d.z[r * w + c])
            .collect();
        let med = median(lunar_dem::slope_deg_grid(&win, ww, wh, d.cell_m));
        let slip = slip_at(
            med,
            0.0,
            ctx.rover_mass_kg,
            inp.slip_gravity_ms2,
            inp.soil,
            inp.slip,
        )?
        .min(0.95);
        out["work_area_median_slope_deg"] = json!(med);
        out["range_slopeslip_km"] = json!(single_charge_range_m(g, med, slip, false, ctx) / 1000.0);
        out["reach"] = reach(d, ctx.battery_j * (1.0 - ctx.reserve_frac), g, ctx, inp);
    }
    Ok(out)
}
