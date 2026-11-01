//! Pooled plan acceptance on the conserved authority (Python `lode.planner_acceptance.validate_plan`, RW-33e1):
//! rasterize each order's real footprint (its typed ring, or the scalar square) onto a [`ColumnState`] laid over the
//! real terrain, run every cut into one drum and then every fill from it, and report material realizability (mass
//! conservation, the datum floor, drum supply), slope and off-DEM siting, as-built flatness, berm rise, repose and
//! bearing capacity. Route, battery, sequence and drum-cycle feasibility belong to the plan totals.
//!
//! The column is built at bank density, so its mantle is `regolith_depth_m` thick and the pre-build surface is the
//! terrain; the Python's column takes the default surface density instead, which stands the mantle 1.48x taller and
//! drops each cut 1.48x its depth (D-R98). Only the repose figures differ. The DEM is required.

use serde_json::{Value, json};
use stewie_physics::bearing::allowable_pa;
use stewie_physics::column::{ColumnState, Fields, Regolith, StateLabel};
use stewie_physics::soil::SoilParams;
use stewie_traverse::route::Dem;
use stewie_twin::numpy::{round, sum as np_sum};

use crate::mission::{BuildOrder, Mission, OrderKind};
use crate::trips::Trip;

/// The acceptance settings (Python `validate_plan` keywords).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AcceptanceParams {
    /// Preferred grid cell [m]; coarsened so neither side exceeds `max_cells`.
    pub cell_m: f64,
    pub max_cells: usize,
    /// Mantle thickness above the datum [m].
    pub regolith_depth_m: f64,
    /// Steepest terrain an order's footprint may sit on [deg].
    pub max_slope_deg: f64,
    pub accept_flatness_tol_m: f64,
    /// A structural design load the pads must carry [Pa], when one is given.
    pub bearing_load_pa: Option<f64>,
    pub bearing_fs: f64,
}

impl Default for AcceptanceParams {
    /// The Python `validate_plan` keyword defaults.
    fn default() -> Self {
        Self {
            cell_m: 0.5,
            max_cells: 500,
            regolith_depth_m: 10.0,
            max_slope_deg: 15.0,
            accept_flatness_tol_m: 0.02,
            bearing_load_pa: None,
            bearing_fs: 3.0,
        }
    }
}

/// The physical inputs besides the mission and terrain.
#[derive(Debug, Clone, Copy)]
pub struct AcceptanceInputs<'a> {
    /// The body's loose regolith density [kg/m^3].
    pub body_density: f64,
    pub regolith: &'a Regolith,
    pub soil: &'a SoilParams,
    pub gravity_ms2: f64,
    /// The vehicle's drum capacity [kg] and dig energy [J/kg].
    pub drum_kg: f64,
    pub dig_j_per_kg: f64,
}

/// The closed boundary ring of a typed footprint, centred on the order (Python `gis_export._footprint_ring_xy`);
/// None for a scalar order.
#[must_use]
pub fn footprint_ring(o: &BuildOrder) -> Option<Vec<(f64, f64)>> {
    let shape = o.shape.as_ref()?.as_object()?;
    let num = |k: &str| shape.get(k).and_then(Value::as_f64);
    let (cx, cy) = (o.x, o.y);
    let theta = num("theta_deg").unwrap_or(0.0).to_radians();
    let (ct, st) = (theta.cos(), theta.sin());
    let place = |pts: &[(f64, f64)]| -> Vec<(f64, f64)> {
        pts.iter()
            .map(|&(lx, ly)| (cx + lx * ct - ly * st, cy + lx * st + ly * ct))
            .collect()
    };
    let kind = shape.get("kind").and_then(Value::as_str)?.to_lowercase();
    let mut ring = match kind.as_str() {
        "rectangle" | "corridor" => {
            let (a, b) = if kind == "rectangle" {
                (num("w")? / 2.0, num("h")? / 2.0)
            } else {
                (num("length")? / 2.0, num("width")? / 2.0)
            };
            place(&[(-a, -b), (a, -b), (a, b), (-a, b)])
        }
        "circle" => {
            let r = num("r")?;
            (0..32_u32)
                .map(|i| {
                    let t = 2.0 * std::f64::consts::PI * f64::from(i) / 32.0;
                    (cx + r * t.cos(), cy + r * t.sin())
                })
                .collect()
        }
        "polygon" => {
            let v: Option<Vec<(f64, f64)>> = shape
                .get("vertices")?
                .as_array()?
                .iter()
                .map(|p| Some((p.get(0)?.as_f64()?, p.get(1)?.as_f64()?)))
                .collect();
            place(&v?)
        }
        _ => return None,
    };
    if ring.first() != ring.last() {
        ring.push(ring[0]);
    }
    (ring.len() >= 3).then_some(ring)
}

/// The footing width for bearing: the ring's least width over its edge normals, else the scalar square's side.
#[must_use]
pub fn footing_width_m(o: &BuildOrder) -> f64 {
    let Some(ring) = footprint_ring(o) else {
        return o.footprint_m2.sqrt();
    };
    let n = ring.len();
    let mut best = f64::INFINITY;
    for i in 0..n {
        let (a, b) = (ring[i], ring[(i + 1) % n]);
        let (ex, ey) = (b.0 - a.0, b.1 - a.1);
        let len = ex.hypot(ey);
        if len < 1e-12 {
            continue;
        }
        let (nx, ny) = (-ey / len, ex / len);
        let proj = ring.iter().map(|p| p.0 * nx + p.1 * ny);
        let (lo, hi) = proj.fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), v| {
            (lo.min(v), hi.max(v))
        });
        best = best.min(hi - lo);
    }
    if best.is_finite() {
        best
    } else {
        o.footprint_m2.sqrt()
    }
}

/// The acceptance grid: origin, cell and size.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Grid {
    pub x0: f64,
    pub y0: f64,
    pub cell_m: f64,
    pub cols: usize,
    pub rows: usize,
}

impl Grid {
    /// The orders' bounding box plus a margin, at `cell_m` coarsened to at most `max_cells` a side.
    #[must_use]
    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        clippy::cast_precision_loss
    )]
    pub fn around(orders: &[BuildOrder], cell_m: f64, max_cells: usize) -> Self {
        let side = |o: &BuildOrder| o.footprint_m2.sqrt();
        let margin = 2.0 + orders.iter().map(side).fold(0.0, f64::max) / 2.0;
        let lo = |f: fn(&BuildOrder) -> f64| {
            orders
                .iter()
                .map(|o| f(o) - side(o) / 2.0)
                .fold(f64::INFINITY, f64::min)
                - margin
        };
        let hi = |f: fn(&BuildOrder) -> f64| {
            orders
                .iter()
                .map(|o| f(o) + side(o) / 2.0)
                .fold(f64::NEG_INFINITY, f64::max)
                + margin
        };
        let (x0, y0, x1, y1) = (lo(|o| o.x), lo(|o| o.y), hi(|o| o.x), hi(|o| o.y));
        let span = (x1 - x0).max(y1 - y0);
        let cell = if span / cell_m > max_cells as f64 {
            span / max_cells as f64
        } else {
            cell_m
        };
        let n = |len: f64| ((len / cell).ceil() as usize).max(1);
        Self {
            x0,
            y0,
            cell_m: cell,
            cols: n(x1 - x0),
            rows: n(y1 - y0),
        }
    }

    /// The order's footprint mask, row-major.
    #[must_use]
    #[allow(clippy::cast_precision_loss)]
    pub fn mask(&self, o: &BuildOrder) -> Vec<bool> {
        let cells = (0..self.rows)
            .flat_map(|r| (0..self.cols).map(move |c| (r as f64 + 0.5, c as f64 + 0.5)));
        if let Some(ring) = footprint_ring(o) {
            let xs: Vec<f64> = ring.iter().map(|p| (p.0 - self.x0) / self.cell_m).collect();
            let ys: Vec<f64> = ring.iter().map(|p| (p.1 - self.y0) / self.cell_m).collect();
            let n = xs.len();
            return cells
                .map(|(py, px)| {
                    // even-odd crossings, as the Python's vectorised test
                    let mut inside = false;
                    for i in 0..n {
                        let j = (i + n - 1) % n;
                        let (xi, yi, xj, yj) = (xs[i], ys[i], xs[j], ys[j]);
                        if (yi - yj).abs() == 0.0 {
                            continue;
                        }
                        let xint = (xj - xi) * (py - yi) / (yj - yi) + xi;
                        if ((yi > py) != (yj > py)) && px < xint {
                            inside = !inside;
                        }
                    }
                    inside
                })
                .collect();
        }
        let half = o.footprint_m2.sqrt() / 2.0 / self.cell_m;
        let (cx, cy) = ((o.x - self.x0) / self.cell_m, (o.y - self.y0) / self.cell_m);
        cells
            .map(|(py, px)| (px - cx).abs() <= half && (py - cy).abs() <= half)
            .collect()
    }
}

/// The mantle over the real terrain: `regolith_depth_m` of bank-density regolith on a datum that puts the surface
/// at the terrain height under each cell centre.
///
/// # Errors
/// The column's own validation.
// cell indices clamped to [0, n) before and after the cast
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss
)]
pub fn column_over(
    g: &Grid,
    dem: Dem<'_>,
    regolith_depth_m: f64,
    rho_bank: f64,
    regolith: &Regolith,
) -> Result<ColumnState, String> {
    let idx = |v: f64, n: usize| (v.trunc().max(0.0) as usize).min(n - 1);
    let ci: Vec<usize> = (0..g.cols)
        .map(|c| {
            idx(
                (g.x0 + (c as f64 + 0.5) * g.cell_m + dem.origin.0) / dem.cell_m,
                dem.width,
            )
        })
        .collect();
    let ri: Vec<usize> = (0..g.rows)
        .map(|r| {
            idx(
                (g.y0 + (r as f64 + 0.5) * g.cell_m + dem.origin.1) / dem.cell_m,
                dem.height,
            )
        })
        .collect();
    let datum: Vec<f64> = ri
        .iter()
        .flat_map(|&r| {
            ci.iter()
                .map(move |&c| dem.z[r * dem.width + c] - regolith_depth_m)
        })
        .collect();
    let n = g.rows * g.cols;
    ColumnState::new(
        g.cols,
        g.rows,
        g.cell_m,
        Fields {
            mass_areal: vec![rho_bank * regolith_depth_m; n],
            density: vec![rho_bank; n],
            state_label: vec![StateLabel::Virgin as u8; n],
            disturbance: vec![0.0; n],
            datum,
            ice: None,
        },
        0.0,
        regolith,
    )
    .map_err(|e| e.to_string())
}

fn masked(v: &[f64], mask: &[bool]) -> Vec<f64> {
    v.iter()
        .zip(mask)
        .filter(|(_, m)| **m)
        .map(|(x, _)| *x)
        .collect()
}

#[allow(clippy::cast_precision_loss)]
fn mean(v: &[f64]) -> f64 {
    np_sum(v) / v.len() as f64
}

/// The surfaces an acceptance run built (Python `return_grids`), row-major over its grid.
#[derive(Debug, Clone, PartialEq)]
pub struct BuiltGrids {
    pub grid: Grid,
    /// The pre-build surface (the terrain).
    pub base: Vec<f64>,
    /// The surface after every cut and fill.
    pub as_built: Vec<f64>,
}

/// Pooled acceptance of the mission's orders (Python `validate_plan`).
///
/// # Errors
/// A column the physics refuses.
pub fn validate_plan(
    m: &Mission,
    dem: Dem<'_>,
    inp: &AcceptanceInputs<'_>,
    p: &AcceptanceParams,
) -> Result<Value, String> {
    validate_plan_grids(m, dem, inp, p).map(|(report, _)| report)
}

/// [`validate_plan`] with the surfaces it built, so the terrain change it executed can be recorded.
///
/// # Errors
/// A column the physics refuses.
#[allow(
    clippy::too_many_lines,
    clippy::cast_precision_loss,
    clippy::many_single_char_names
)] // the Python's report
pub fn validate_plan_grids(
    m: &Mission,
    dem: Dem<'_>,
    inp: &AcceptanceInputs<'_>,
    p: &AcceptanceParams,
) -> Result<(Value, BuiltGrids), String> {
    let swell = inp.regolith.rho_deep / inp.regolith.rho_spoil;
    let (rho_bank, rho_loose) = (inp.body_density * swell, inp.body_density);
    let of = |k: OrderKind| m.orders.iter().filter(move |o| o.kind == k);
    let g = Grid::around(&m.orders, p.cell_m, p.max_cells);
    let mut cs = column_over(&g, dem, p.regolith_depth_m, rho_bank, inp.regolith)?;
    let m0 = cs.total_mass();
    let datum_h0 = cs.derive_height();
    let cell_area = g.cell_m * g.cell_m;
    let count = |mask: &[bool]| mask.iter().filter(|b| **b).count();
    let phys = |e: stewie_physics::PhysicsError| e.to_string();
    let mut feasible = true;
    let mut exec_cut = 0.0;
    for o in of(OrderKind::Cut) {
        let mask = g.mask(o);
        if count(&mask) == 0 {
            feasible = false;
            continue;
        }
        let per_cell = vec![o.depth_m * rho_bank; mask.len()];
        let moved = cs.cut_to_inventory(&mask, &per_cell).map_err(phys)?;
        exec_cut += moved;
        // a datum floor: the authority could not move the asked-for depth over the rasterized footprint
        if moved < 0.99 * count(&mask) as f64 * cell_area * o.depth_m * rho_bank {
            feasible = false;
        }
    }
    let mut exec_fill = 0.0;
    for o in of(OrderKind::Fill) {
        let mask = g.mask(o);
        if count(&mask) == 0 {
            feasible = false;
            continue;
        }
        let mut target = cs.derive_height();
        for (t, _) in target.iter_mut().zip(&mask).filter(|(_, b)| **b) {
            *t += o.depth_m;
        }
        exec_fill += cs
            .fill_toward(&mask, &target, Some(o.depth_m), rho_loose)
            .map_err(phys)?;
    }
    let planned_fill: f64 = of(OrderKind::Fill)
        .map(|o| o.footprint_m2 * o.depth_m * rho_loose)
        .sum();
    if of(OrderKind::Fill).next().is_some()
        && exec_fill < 0.99 * planned_fill
        && cs.drum_inventory() <= 1e-6 * planned_fill.max(1.0)
    {
        feasible = false;
    }
    let drift = (cs.total_mass() - m0).abs();
    let mass_conserved = drift <= 1e-6 * m0.max(1.0);
    let as_built = cs.derive_height();
    let slope = lunar_dem::slope_deg_grid(&as_built, g.cols, g.rows, g.cell_m);
    let repose_limit = inp.soil.phi_rad.to_degrees();
    let (mut flat, mut berm, mut repose, mut bearing) =
        (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    let (gamma_loose, gamma_firm) = (rho_loose * inp.gravity_ms2, rho_bank * inp.gravity_ms2);
    for o in &m.orders {
        let mask = g.mask(o);
        if count(&mask) < 2 {
            continue;
        }
        let h = masked(&as_built, &mask);
        let hm = mean(&h);
        let sq: Vec<f64> = h.iter().map(|x| (x - hm) * (x - hm)).collect();
        flat.push(mean(&sq).sqrt());
        let worst = masked(&slope, &mask)
            .into_iter()
            .fold(f64::NEG_INFINITY, f64::max);
        repose.push(json!({"action": o.action, "max_slope_deg": round(worst, 2),
                           "repose_limit_deg": round(repose_limit, 2), "stable": worst <= repose_limit}));
        if o.kind != OrderKind::Fill {
            continue;
        }
        let rise = hm - mean(&masked(&datum_h0, &mask));
        berm.push(
            json!({"action": o.action, "target_rise_m": round(o.depth_m, 4),
                         "as_built_rise_m": round(rise, 4),
                         "within_tol": (rise - o.depth_m).abs() <= p.accept_flatness_tol_m}),
        );
        let b = footing_width_m(o);
        let loose = allowable_pa(
            inp.soil.cohesion_pa,
            inp.soil.phi_rad,
            gamma_loose,
            b,
            0.0,
            p.bearing_fs,
        );
        let firm = allowable_pa(
            inp.soil.cohesion_pa,
            inp.soil.phi_rad,
            gamma_firm,
            b,
            0.0,
            p.bearing_fs,
        );
        let mut rec = json!({"action": o.action, "width_m": round(b, 3), "allowable_pa": round(loose, 1),
                             "allowable_firmed_pa": round(firm, 1), "factor_of_safety": p.bearing_fs});
        if let Some(load) = p.bearing_load_pa {
            rec["design_load_pa"] = json!(load);
            rec["holds"] = json!(loose >= load);
            rec["firming_recommended"] = json!(loose < load && firm >= load);
        }
        bearing.push(rec);
    }
    // the python orders berm/repose/bearing lists by their own loops; repose covers every order, berm and
    // bearing only fills, each in order -- the single pass above keeps those orders
    let worst_flat = flat.iter().copied().fold(0.0, f64::max);
    let mean_flat = if flat.is_empty() {
        0.0
    } else {
        flat.iter().sum::<f64>() / flat.len() as f64
    };
    let all = |v: &[Value], k: &str| {
        v.iter()
            .all(|r| r.get(k).and_then(Value::as_bool).unwrap_or(true))
    };
    let (slope_violations, off_dem) = siting(m, dem, p.max_slope_deg);
    let drum = inp.drum_kg;
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
    let shuttle: u64 = if drum > 0.0 {
        of(OrderKind::Cut)
            .map(|o| ((o.footprint_m2 * o.depth_m * rho_bank / drum).ceil() as u64).max(1))
            .sum()
    } else {
        0
    };
    let report = json!({
        "feasible": feasible && mass_conserved && slope_violations.is_empty() && off_dem.is_empty(),
        "mass_conserved": mass_conserved,
        "slope_violations": slope_violations,
        "off_dem_orders": off_dem,
        "acceptance_scope": {
            "covers": ["mass_conservation", "datum_floor_feasibility", "drum_supply", "slope_siting",
                       "off_dem_siting", "as_built_flatness", "berm_profile", "repose_stability",
                       "bearing_capacity"],
            "defers_to_totals": ["route_feasibility", "battery_reserve", "sequence_precedence",
                                 "drum_capacity_shuttle_cycles", "time_budget", "energy_budget"]},
        "drum_capacity_kg": drum,
        "shuttle_cycles_est": shuttle,
        "max_slope_deg": p.max_slope_deg,
        "mass_drift_kg": drift,
        "planned_cut_kg": of(OrderKind::Cut).map(|o| o.footprint_m2 * o.depth_m * rho_bank).sum::<f64>(),
        "executed_cut_kg": exec_cut,
        "planned_fill_kg": planned_fill,
        "executed_fill_kg": exec_fill,
        "drum_remaining_kg": cs.drum_inventory(),
        "executed_dig_J": exec_cut * inp.dig_j_per_kg,
        "grid": {"rows": g.rows, "cols": g.cols, "cell_m": g.cell_m},
        "as_built_on_real_dem": true,
        "as_built_flatness_rmse_m": worst_flat,
        "as_built_flatness_mean_m": mean_flat,
        "as_built_tol_m": p.accept_flatness_tol_m,
        "as_built_pass": worst_flat <= p.accept_flatness_tol_m,
        "berm_profile_pass": all(&berm, "within_tol"),
        "berm_profile": berm,
        "repose_pass": all(&repose, "stable"),
        "repose": repose,
        "repose_limit_deg": round(repose_limit, 2),
        "bearing_pass": all(&bearing, "holds"),
        "bearing": bearing,
    });
    Ok((
        report,
        BuiltGrids {
            grid: g,
            base: datum_h0,
            as_built,
        },
    ))
}

/// The orders whose footprint box leaves the DEM, and those whose footprint holds terrain steeper than allowed.
#[allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]
fn siting(m: &Mission, dem: Dem<'_>, max_slope_deg: f64) -> (Vec<Value>, Vec<Value>) {
    let smap = lunar_dem::slope_deg_grid(dem.z, dem.width, dem.height, dem.cell_m);
    let (mut steep, mut off) = (Vec::new(), Vec::new());
    for o in &m.orders {
        let half = o.footprint_m2.sqrt() / 2.0 / dem.cell_m;
        let (cx, cy) = (
            (dem.origin.0 + o.x) / dem.cell_m,
            (dem.origin.1 + o.y) / dem.cell_m,
        );
        // Python round(): half to even
        let r = |v: f64| v.round_ties_even() as i64;
        let (r0, r1, c0, c1) = (
            r(cy - half),
            r(cy + half) + 1,
            r(cx - half),
            r(cx + half) + 1,
        );
        let (h, w) = (
            i64::try_from(dem.height).unwrap_or(i64::MAX),
            i64::try_from(dem.width).unwrap_or(i64::MAX),
        );
        if r0 < 0 || c0 < 0 || r1 > h || c1 > w {
            off.push(json!({"action": o.action, "x": o.x, "y": o.y}));
            continue;
        }
        #[allow(clippy::cast_sign_loss)]
        let patch: Vec<f64> = (r0..r1)
            .flat_map(|rr| (c0..c1).map(move |cc| (rr as usize) * dem.width + cc as usize))
            .map(|i| smap[i])
            .collect();
        if patch.is_empty() {
            continue;
        }
        let worst = patch.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        if worst > max_slope_deg {
            let over =
                patch.iter().filter(|&&s| s > max_slope_deg).count() as f64 / patch.len() as f64;
            steep.push(json!({"action": o.action, "slope_deg": round(worst, 1), "frac_over": round(over, 2),
                              "x": o.x, "y": o.y}));
        }
    }
    (steep, off)
}

/// Ordered replay acceptance (Python `execute_plan_acceptance`, RW-33e2): walk the plan's trips in order through a
/// drum that holds at most the vehicle's capacity. A haul trip alternates cutting a drum load and filling from it
/// until its assigned flow is moved; a spoil cut with nothing to drain it overflows the drum; an import fill drains
/// it. This catches what the pooled check flattens: a fill scheduled before its supplying cut, and footprints that
/// overlap across trips. Returns the report and the ordered as-built surface (row-major over the report's grid).
///
/// # Errors
/// A column the physics refuses.
#[allow(
    clippy::too_many_lines,
    clippy::cast_precision_loss,
    clippy::many_single_char_names
)] // the Python's walk
pub fn execute_plan_acceptance(
    m: &Mission,
    trips: &[Trip],
    dem: Dem<'_>,
    inp: &AcceptanceInputs<'_>,
    p: &AcceptanceParams,
) -> Result<(Value, Vec<f64>), String> {
    let swell = inp.regolith.rho_deep / inp.regolith.rho_spoil;
    let (rho_bank, rho_loose) = (inp.body_density * swell, inp.body_density);
    let g = Grid::around(&m.orders, p.cell_m, p.max_cells);
    let mut cs = column_over(&g, dem, p.regolith_depth_m, rho_bank, inp.regolith)?;
    let m0 = cs.total_mass();
    let phys = |e: stewie_physics::PhysicsError| e.to_string();
    let count = |mask: &[bool]| mask.iter().filter(|b| **b).count();
    let cap = inp.drum_kg;
    let step = if cap > 0.0 { cap } else { f64::INFINITY };
    // what each cut order can still give, across the flows it supplies
    let mut supply: Vec<f64> = m
        .orders
        .iter()
        .map(|o| o.footprint_m2 * o.depth_m * rho_bank)
        .collect();
    let (mut feasible, mut drum_max, mut running_min) = (true, 0.0_f64, 0.0_f64);
    let (mut shuttle, mut placed_kg) = (0_u64, 0.0);
    let orders_of = |t: &Trip, k: OrderKind| -> Vec<usize> {
        t.actions
            .iter()
            .filter_map(|a| m.orders.iter().position(|o| &o.action == a))
            .filter(|&i| m.orders[i].kind == k)
            .collect()
    };
    let per_cell = |kg: f64, n: usize, len: usize| vec![kg / (n as f64 * g.cell_m * g.cell_m); len];
    // drain the drum into a fill until it is empty or nothing more fits
    let drain = |cs: &mut ColumnState,
                 mask: &[bool],
                 target: &[f64],
                 depth: f64,
                 placed_kg: &mut f64,
                 running_min: &mut f64|
     -> Result<(), String> {
        let mut placed = 1.0;
        while cs.drum_inventory() > 1e-6 && placed > 1e-6 {
            let before = cs.drum_inventory();
            cs.fill_toward(mask, target, Some(depth), rho_loose)
                .map_err(phys)?;
            placed = before - cs.drum_inventory();
            *placed_kg += placed;
            *running_min = running_min.min(cs.drum_inventory());
        }
        *running_min = running_min.min(cs.drum_inventory());
        Ok(())
    };
    let target_over = |cs: &ColumnState, mask: &[bool], depth: f64| -> Vec<f64> {
        let mut t = cs.derive_height();
        for (h, _) in t.iter_mut().zip(mask).filter(|(_, b)| **b) {
            *h += depth;
        }
        t
    };
    for t in trips {
        let (cuts, fills) = (orders_of(t, OrderKind::Cut), orders_of(t, OrderKind::Fill));
        if !cuts.is_empty() && !fills.is_empty() && t.mass_kg > 1e-6 {
            let (co, fo) = (cuts[0], fills[0]);
            let (cmask, fmask) = (g.mask(&m.orders[co]), g.mask(&m.orders[fo]));
            if count(&cmask) == 0 || count(&fmask) == 0 {
                feasible = false;
                continue;
            }
            let n = count(&cmask);
            let depth = m.orders[fo].depth_m;
            let ftarget = target_over(&cs, &fmask, depth);
            let mut remaining = t.mass_kg.min(supply[co]);
            while remaining > 1e-6 {
                let take = remaining.min(step - cs.drum_inventory());
                if take > 1e-6 {
                    let moved = cs
                        .cut_to_inventory(&cmask, &per_cell(take, n, cmask.len()))
                        .map_err(phys)?;
                    drum_max = drum_max.max(cs.drum_inventory());
                    shuttle += 1;
                    if moved <= 1e-6 {
                        feasible = false;
                        break;
                    }
                    remaining -= moved;
                    supply[co] -= moved;
                }
                drain(
                    &mut cs,
                    &fmask,
                    &ftarget,
                    depth,
                    &mut placed_kg,
                    &mut running_min,
                )?;
                if cs.drum_inventory() > 1e-6 && take <= 1e-6 {
                    feasible = false;
                    break;
                }
            }
        } else {
            for &o in &cuts {
                let mask = g.mask(&m.orders[o]);
                let n = count(&mask);
                if n == 0 {
                    feasible = false;
                    continue;
                }
                let mut want = supply[o];
                while want > 1e-6 {
                    let free = step - cs.drum_inventory();
                    if free <= 1e-6 {
                        feasible = false;
                        break;
                    }
                    let take = want.min(free);
                    let moved = cs
                        .cut_to_inventory(&mask, &per_cell(take, n, mask.len()))
                        .map_err(phys)?;
                    drum_max = drum_max.max(cs.drum_inventory());
                    shuttle += 1;
                    if moved <= 1e-6 {
                        feasible = false;
                        break;
                    }
                    want -= moved;
                }
                supply[o] = want;
            }
            for &o in &fills {
                let mask = g.mask(&m.orders[o]);
                if count(&mask) == 0 {
                    feasible = false;
                    continue;
                }
                let depth = m.orders[o].depth_m;
                let target = target_over(&cs, &mask, depth);
                drain(
                    &mut cs,
                    &mask,
                    &target,
                    depth,
                    &mut placed_kg,
                    &mut running_min,
                )?;
            }
        }
    }
    let drift = (cs.total_mass() - m0).abs();
    let mass_conserved = drift <= 1e-6 * m0.max(1.0);
    Ok((
        json!({
            "executes_ordered_ir": true,
            "feasible": feasible && mass_conserved,
            "mass_conserved": mass_conserved,
            "mass_drift_kg": drift,
            "drum_capacity_kg": cap,
            "max_simultaneous_drum_kg": drum_max,
            "running_drum_min_kg": running_min,
            "shuttle_cycles": shuttle,
            "placed_kg": placed_kg,
            "grid": {"rows": g.rows, "cols": g.cols, "cell_m": g.cell_m},
        }),
        cs.derive_height(),
    ))
}
