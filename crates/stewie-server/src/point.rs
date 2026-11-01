//! The GW-07 selection inspector (RW-55b5c; Python `gis_layers.point_values`, `_terra_fields`, `_costmap_compose`):
//! a clicked order-frame location resolves to its site-DEM cell, and the servable layers report their values there
//! from the same producers the map drapes use. Elevation and slope come from the DEM; the six terramechanics-spine
//! fields from a 512-sample slope table of the slip-sinkage solve, interpolated as numpy does; the plan-independent
//! cost and veto from the AS-11 layered costmap on a 97 x 97 window around the cell. A layer with no per-cell scalar
//! is reported unavailable with its reason, and an out-of-tile click reports no values at all.
//!
//! The IPEx figures come from the rover profile and fleet registry, the soil from the body registry (D-R72: the
//! loose friction is the registry's 35 deg), and the representative dig from the profile's large drum on BP-1.

use lunar_dem::{slope_deg_grid, uniform_filter_nearest};
use serde_json::{Value, json};
use stewie_physics::excavation::{self, Dig};
use stewie_physics::material::MaterialModel;
use stewie_physics::soil::SoilParams;
use stewie_physics::terra::{self, DriveCase};
use stewie_traverse::layers::{Context, Rover, compose, horizon_clip};
use stewie_twin::numpy::round;
use stewie_twin::terrain_view::{Source, TerrainView};

use crate::planning::Planning;
use crate::state::SiteDem;

/// The globe cost drape's default sun [deg]; reported in the payload so the fixed choice is legible.
pub const SUN_EL_DEG: f64 = 6.0;
pub const SUN_AZ_DEG: f64 = 90.0;
/// The traversable slope cap the drape composes at [deg]; the drop cap is one cell at this grade.
const MAX_SLOPE_DEG: f64 = 25.0;
/// The Python `CostmapContext` defaults the drape leaves unset.
const SLIP_ALPHA: f64 = 2.0;
const MAX_SINKAGE_M: f64 = 0.10;
/// Half the inspector's window [cells] (a 97 x 97 patch).
const HALF: usize = 48;
/// Slope table samples.
const LUT_N: usize = 512;
/// Rupture-angle knots of the earthmoving solve (the Python's default).
const N_BETA: u32 = 900;

const PROFILE: &str = include_str!("../../stewie-contracts/fixtures/rover_ipex.json");

/// The IPEx figures the terramechanics spine and the costmap read.
#[derive(Debug, Clone, Copy)]
pub struct Spine {
    pub rover: Rover,
    pub soil: SoilParams,
    pub gravity_ms2: f64,
    /// The representative dig's draft force [N] (McKyes/Reece FEE): uniform where the material is.
    pub draft_n: f64,
}

impl Spine {
    /// The IPEx rover on the Moon.
    ///
    /// # Errors
    /// A registry or profile without a value the spine reads, or a dig the solver refuses.
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // the profile's wheel count
    pub fn ipex(p: &Planning) -> Result<Self, String> {
        let prof: Value = serde_json::from_str(PROFILE).map_err(|e| format!("rover_ipex: {e}"))?;
        let num = |v: &Value, what: &str| {
            v.as_f64()
                .ok_or_else(|| format!("rover_ipex has no {what}"))
        };
        let pv = |k: &str| num(&prof[k]["value"], k);
        let fleet = p
            .fleet
            .vehicles
            .get("ipex")
            .ok_or("the fleet registry has no ipex")?;
        let rover = Rover {
            gauge_m: fleet.gauge_m,
            wheelbase_m: fleet.wheelbase_m,
            cg_height_m: pv("cg_height_m")?,
            mass_dry_kg: pv("mass_dry_kg")?,
            n_wheels: pv("n_wheels")? as u32,
            contact_len_m: pv("contact_len_m")?,
            contact_width_m: pv("contact_width_m")?,
            obstacle_height_m: pv("obstacle_height_m")?,
            rolling_resistance: pv("rolling_resistance_coeff")?,
            drive_speed_ms: pv("drive_speed_ms")?,
            drivetrain_efficiency: pv("drivetrain_efficiency")?,
        };
        let soil = SoilParams::for_body(&p.bodies, &p.soil_base, "moon", false)
            .map_err(|e| e.to_string())?;
        let gravity_ms2 = p.bodies.get("moon").ok_or("no Moon in the registry")?.g;
        // the representative dig: the large drum's width, half its scoop height per pass, on BP-1 at its density
        let drum = &prof["drums"]["large"];
        let rho = p
            .bodies
            .get("bp1_testbed")
            .and_then(|b| b.bulk_density)
            .ok_or("the registry has no BP-1 density")?;
        let (phi, cohesion) = MaterialModel::for_soil(&soil, &p.soil_base).cell_strength(rho);
        let dig = Dig {
            depth_m: pv("max_cut_depth_frac")?
                * num(&drum["scoop_height_m"]["value"], "scoop height")?,
            width_m: num(&drum["width_m"]["value"], "drum width")?,
            cohesion_pa: cohesion,
            bulk_density_kg_m3: rho,
            gravity_ms2,
            phi_rad: phi,
            rake_rad: pv("rake_deg")?.to_radians(),
            soil_tool_friction_rad: pv("soil_tool_friction_frac")? * phi,
            surcharge_pa: 0.0,
        };
        let draft_n = excavation::solve(&dig, N_BETA)
            .map_err(|e| e.to_string())?
            .draft_n;
        Ok(Self {
            rover,
            soil,
            gravity_ms2,
            draft_n,
        })
    }

    fn case(&self, slope_rad: f64) -> DriveCase {
        let r = &self.rover;
        DriveCase {
            total_weight_n: r.mass_dry_kg * self.gravity_ms2,
            slope_rad,
            n_wheels: r.n_wheels,
            contact_len_m: r.contact_len_m,
            contact_width_m: r.contact_width_m,
            density: None,
            demand_frac: 1.0,
            extra_demand_n: 0.0,
            s_entrap: 0.95,
            // the Python's [PROXY] entrapment depth: twice the contact width
            z_entrap_m: 2.0 * r.contact_width_m,
        }
    }
}

/// `np.interp(x, xp, fp)` for an increasing `xp`: the end values outside it, NaN for a NaN `x`.
#[allow(clippy::float_cmp)] // numpy's exact knot and equal-value tests
fn np_interp(x: f64, xp: &[f64], fp: &[f64]) -> f64 {
    let n = xp.len();
    if x.is_nan() {
        return f64::NAN;
    }
    let j = xp.partition_point(|v| *v <= x);
    if j == 0 {
        return fp[0];
    }
    let j = j - 1;
    if j >= n - 1 || xp[j] == x {
        return fp[j];
    }
    let slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
    let r = slope * (x - xp[j]) + fp[j];
    if !r.is_nan() {
        return r;
    }
    let r = slope * (x - xp[j + 1]) + fp[j + 1];
    if r.is_nan() && fp[j] == fp[j + 1] {
        fp[j]
    } else {
        r
    }
}

/// The spine fields as a function of slope, sampled at 512 slopes up to the window's steepest (at most 89 deg).
#[derive(Debug, Clone)]
pub struct Terra {
    grid: Vec<f64>,
    bearing: Vec<f64>,
    sinkage: Vec<f64>,
    slip: Vec<f64>,
    margin: Vec<f64>,
    power: Vec<f64>,
}

/// The spine fields at one slope: contact pressure [Pa], sinkage [m], slip ratio, traction margin, drive power [W].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TerraAt {
    pub bearing_pa: f64,
    pub sinkage_m: f64,
    pub slip: f64,
    pub traction_margin: f64,
    pub drive_power_w: f64,
}

impl Terra {
    /// The table over a slope map [deg].
    ///
    /// # Errors
    /// A solve the physics refuses.
    #[allow(clippy::cast_precision_loss, clippy::many_single_char_names)] // LUT_N; the Python's r, t, c, b, d
    pub fn over(slope: &[f64], s: &Spine) -> Result<Self, String> {
        let steepest = slope
            .iter()
            .copied()
            .filter(|v| !v.is_nan())
            .reduce(f64::max)
            .unwrap_or(f64::NAN);
        let top = 89.0_f64.min(steepest).max(1.0);
        let step = top / (LUT_N - 1) as f64;
        let mut grid: Vec<f64> = (0..LUT_N).map(|i| i as f64 * step).collect();
        grid[LUT_N - 1] = top;
        let r = &s.rover;
        let nw = f64::from(r.n_wheels);
        let weight = r.mass_dry_kg * s.gravity_ms2;
        let mut t = Self {
            grid: Vec::with_capacity(LUT_N),
            bearing: Vec::with_capacity(LUT_N),
            sinkage: Vec::with_capacity(LUT_N),
            slip: Vec::with_capacity(LUT_N),
            margin: Vec::with_capacity(LUT_N),
            power: Vec::with_capacity(LUT_N),
        };
        let bad = |e: stewie_physics::PhysicsError| e.to_string();
        for &deg in &grid {
            let th = deg.to_radians();
            let c = s.case(th);
            t.bearing
                .push(weight * th.cos() / nw / (r.contact_width_m * r.contact_len_m));
            let eq = terra::slip_sinkage_equilibrium(&c, &s.soil).map_err(bad)?;
            t.sinkage.push(eq.sinkage_m);
            t.slip.push(eq.slip);
            let (b, d) = (eq.budget_n, eq.demand_n);
            t.margin.push(if b > 0.0 {
                0.0_f64.max((b - d) / b)
            } else {
                0.0
            });
            t.power.push(
                terra::bekker_drive_power(&c, r.drive_speed_ms, r.drivetrain_efficiency, &s.soil)
                    .map_err(bad)?
                    .drive_power_w,
            );
        }
        t.grid = grid;
        Ok(t)
    }

    #[must_use]
    pub fn at(&self, slope_deg: f64) -> TerraAt {
        let i = |fp: &[f64]| np_interp(slope_deg, &self.grid, fp);
        TerraAt {
            bearing_pa: i(&self.bearing),
            sinkage_m: i(&self.sinkage),
            slip: i(&self.slip),
            traction_margin: i(&self.margin),
            drive_power_w: i(&self.power),
        }
    }
}

/// The AS-11 costmap on a DEM window at the drape's sun and a slope cap, the drop cap one cell at that grade.
///
/// # Errors
/// The costmap's refusal.
pub fn drape_costmap(
    z: &[f64],
    width: usize,
    height: usize,
    cell_m: f64,
    sun_az_deg: f64,
    max_slope_deg: f64,
    s: &Spine,
) -> Result<stewie_traverse::layers::Composite, String> {
    compose(&Context {
        z,
        width,
        height,
        cell_m,
        max_slope_deg,
        slip_alpha: SLIP_ALPHA,
        max_drop_m: cell_m * max_slope_deg.to_radians().tan(),
        sun_az_deg,
        sun_el_deg: SUN_EL_DEG,
        payload_kg: 0.0,
        max_sinkage_m: MAX_SINKAGE_M,
        gravity_ms2: s.gravity_ms2,
        soil: s.soil,
        rover: s.rover,
        keepout: None,
        reserved: None,
        clasts: &[],
    })
}

/// The inspector's rows in order: catalog id, label, unit.
const ORDER: [(&str, &str, &str); 16] = [
    ("base.dem", "Elevation", "m"),
    ("terrain.slope", "Slope", "deg"),
    ("hazard.slope_nogo", "Slope no-go", ""),
    ("physics.bearing", "Bearing (contact pressure)", "Pa"),
    ("physics.sinkage", "Sinkage", "m"),
    ("physics.slip_risk", "Slip risk", "slip ratio"),
    ("physics.traction_margin", "Traction margin", "fraction"),
    ("physics.energy_cost", "Drive power", "W"),
    (
        "physics.excavation_resistance",
        "Excavation draft force",
        "N",
    ),
    ("traffic.cost_global", "Traversal cost", ""),
    ("traffic.traversability", "Passable", ""),
    ("terrain.illumination", "Illumination", ""),
    ("terrain.incidence", "Incidence", "deg"),
    ("terrain.psr", "PSR", ""),
    ("base.grid", "Reference grid", ""),
    ("traffic.compaction", "Traversal compaction", "Dr"),
];

/// Why a row has no per-cell value here.
fn no_data(id: &str) -> &'static str {
    match id {
        "terrain.illumination" => {
            "sun-parameterized (horizon shadowing) -- set the sun to query per cell"
        }
        "terrain.incidence" => {
            "sun-parameterized (solar incidence angle) -- set the sun to query per cell"
        }
        "terrain.psr" => {
            "permanently-shadowed sweep -- an area classification, not a per-cell scalar here"
        }
        "base.grid" => "reference grid overlay -- no measured cell value",
        "traffic.compaction" => "observed traversal compaction -- only where the rover has driven",
        _ => "no per-cell value",
    }
}

fn attr(id: &str, label: &str, unit: &str, value: &Value, note: Option<&str>) -> Value {
    let mut a = json!({"id": id, "label": label, "unit": unit, "available": !value.is_null(), "value": value});
    if let Some(n) = note {
        a["note"] = json!(n);
    }
    if id == "traffic.traversability" {
        a["reason"] = Value::Null;
    }
    a
}

/// The mission actions a cell affords, each enabled or with the reason it is not.
fn actions(in_bounds: bool, passable: bool) -> Value {
    if !in_bounds {
        let why = "outside the site tile";
        return json!([
            {"id": "plan_here", "label": "Plan here", "enabled": false, "reason": why},
            {"id": "place_structure", "label": "Place structure", "enabled": false, "reason": why},
            {"id": "add_keepout", "label": "Add keep-out", "enabled": false, "reason": why},
        ]);
    }
    json!([
        {"id": "plan_here", "label": "Plan here", "enabled": true, "reason": null},
        {"id": "place_structure", "label": "Place structure", "enabled": passable,
         "reason": if passable { Value::Null } else { json!("cell is impassable (blocked terrain)") }},
        {"id": "add_keepout", "label": "Add keep-out", "enabled": true, "reason": null},
    ])
}

/// A rounded grid index as JSON: an integer where it fits, else the (whole) float.
#[allow(clippy::cast_possible_truncation)] // checked against the i64 range
fn index_json(v: f64) -> Value {
    if v.abs() < 9.2e18 {
        json!(v as i64)
    } else {
        json!(v)
    }
}

/// The point query at order-frame (`x_m`, `y_m`) on a site DEM anchored at `origin`, with its composed `view`.
///
/// # Errors
/// A spine or costmap solve the physics refuses.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::too_many_lines,
    clippy::many_single_char_names
)] // grid indices; one payload; the Python's h, w, f, i, s
pub fn point_values(
    site: &str,
    x_m: f64,
    y_m: f64,
    dem: &SiteDem,
    origin: (f64, f64),
    view: &TerrainView,
    s: &Spine,
) -> Result<Value, String> {
    let (ox, oy, cell) = (origin.0, origin.1, dem.cell_m);
    let (h, w) = (dem.rows, dem.cols);
    let finite = x_m.is_finite() && y_m.is_finite();
    // a quotient that overflows is out of the tile (the Python raises there)
    let (colf, rowf) = if finite {
        (
            ((ox + x_m) / cell).round_ties_even(),
            ((oy + y_m) / cell).round_ties_even(),
        )
    } else {
        (-1.0, -1.0)
    };
    let (colf, rowf) = if colf.is_finite() && rowf.is_finite() {
        (colf, rowf)
    } else {
        (-1.0, -1.0)
    };
    let in_bounds = rowf >= 0.0 && rowf < h as f64 && colf >= 0.0 && colf < w as f64;
    let pos = |v: f64| {
        if finite {
            json!(round(v, 2))
        } else {
            Value::Null
        }
    };
    let mut out = json!({
        "ok": true, "site": site,
        "cell": {"row": index_json(rowf), "col": index_json(colf), "cell_m": cell, "in_bounds": in_bounds,
                 "grid_rows": h, "grid_cols": w},
        "position": {"x_m": pos(x_m), "y_m": pos(y_m), "dem_origin_m": [round(ox, 2), round(oy, 2)]},
        "sun": {"el_deg": SUN_EL_DEG, "az_deg": SUN_AZ_DEG},
    });
    if !in_bounds {
        let note = "outside the site tile -- no data at this location";
        out["attributes"] = ORDER
            .iter()
            .map(|(id, label, unit)| attr(id, label, unit, &Value::Null, Some(note)))
            .collect();
        out["runtime_evidence"] = json!({"cell_source": "out_of_bounds", "as_built_delta_m": 0.0,
            "as_built_version": 0, "twin_version": 0, "observed_fraction": 0.0, "observed_at_cell": false});
        out["actions"] = actions(false, false);
        return Ok(out);
    }
    let (row, col) = (rowf as usize, colf as usize);
    let (r0, r1) = (row.saturating_sub(HALF), h.min(row + HALF + 1));
    let (c0, c1) = (col.saturating_sub(HALF), w.min(col + HALF + 1));
    let (ph, pw) = (r1 - r0, c1 - c0);
    let patch: Vec<f64> = (r0..r1)
        .flat_map(|r| dem.z[r * w + c0..r * w + c1].iter().copied())
        .collect();
    let at = (row - r0) * pw + (col - c0);
    let elevation = dem.z[row * w + col];
    let slope_map = slope_deg_grid(&patch, pw, ph, cell);
    let slope = slope_map[at];
    let f = Terra::over(&slope_map, s)?.at(slope);
    let cm = drape_costmap(&patch, pw, ph, cell, SUN_AZ_DEG, MAX_SLOPE_DEG, s)?;
    let passable = cm.passable[at];
    let scalar = |id: &str| match id {
        "base.dem" => Some(elevation),
        "terrain.slope" => Some(slope),
        "physics.bearing" => Some(f.bearing_pa),
        "physics.sinkage" => Some(f.sinkage_m),
        "physics.slip_risk" => Some(f.slip),
        "physics.traction_margin" => Some(f.traction_margin),
        "physics.energy_cost" => Some(f.drive_power_w),
        "physics.excavation_resistance" => Some(s.draft_n),
        "traffic.cost_global" => Some(cm.cost[at]),
        _ => None,
    };
    out["attributes"] = ORDER
        .iter()
        .map(|&(id, label, unit)| {
            if let Some(v) = scalar(id) {
                attr(id, label, unit, &json!(round(v, 4)), None)
            } else if id == "hazard.slope_nogo" {
                attr(
                    id,
                    label,
                    unit,
                    &json!(slope > 20.0),
                    Some("slope > 20 deg tested-envelope no-go [WHEELTEST]"),
                )
            } else if id == "traffic.traversability" {
                let mut a = attr(id, label, unit, &json!(passable), None);
                a["reason"] = cm.reason[at].map_or(Value::Null, |r| json!(r));
                a
            } else {
                attr(id, label, unit, &Value::Null, Some(no_data(id)))
            }
        })
        .collect();
    let i = row * w + col;
    let src = view.source[i];
    out["runtime_evidence"] = json!({
        "cell_source": match src { Source::Pristine => "pristine", Source::AsBuilt => "as_built",
                                   Source::Observed => "observed" },
        "as_built_delta_m": round(view.heights[i] - elevation, 4),
        "as_built_version": view.as_built_version, "twin_version": view.twin_version,
        "observed_fraction": view.observed_fraction, "observed_at_cell": src == Source::Observed,
    });
    out["actions"] = actions(true, passable);
    Ok(out)
}

/// The planner's work-area crop (Python `gis_layers._work_area`): 128 x 128 cells around the flattest anchor,
/// kept inside the tile. Returns the crop (row-major), its rows and columns, and its offset `(r0, c0)`.
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_possible_wrap,
    clippy::cast_sign_loss
)] // tile indices
#[must_use]
pub fn work_area(dem: &SiteDem, origin: (f64, f64)) -> (Vec<f64>, usize, usize, (usize, usize)) {
    const HALF: i64 = 64;
    let (rows, cols) = (dem.rows as i64, dem.cols as i64);
    // int() truncates toward zero
    let r0 = 0.max((rows - 2 * HALF).min((origin.1 / dem.cell_m) as i64 - HALF)) as usize;
    let c0 = 0.max((cols - 2 * HALF).min((origin.0 / dem.cell_m) as i64 - HALF)) as usize;
    let (r1, c1) = (dem.rows.min(r0 + 128), dem.cols.min(c0 + 128));
    let crop = (r0..r1)
        .flat_map(|r| dem.z[r * dem.cols + c0..r * dem.cols + c1].iter().copied())
        .collect();
    (crop, r1 - r0, c1 - c0, (r0, c0))
}

/// Python's float `%`: the result takes the divisor's sign.
pub(crate) fn py_mod(a: f64, b: f64) -> f64 {
    let m = a % b;
    if m == 0.0 {
        0.0_f64.copysign(b)
    } else if (b < 0.0) != (m < 0.0) {
        m + b
    } else {
        m
    }
}

/// A true sun azimuth in the DEM grid's frame (Python `gis_layers.grid_sun_az`): a reflection about the grid's
/// +row bearing, since the north-up raster makes the grid left-handed against the compass.
#[must_use]
pub fn grid_sun_az(sun_az_true_deg: f64, grid_north_bearing_deg: f64) -> f64 {
    py_mod(grid_north_bearing_deg - sun_az_true_deg, 360.0)
}

/// `np.nanmean`: the pairwise sum of the non-NaN values over their count.
#[allow(clippy::cast_precision_loss)] // a cell count
fn nanmean(v: &[f64]) -> f64 {
    let kept: Vec<f64> = v
        .iter()
        .map(|x| if x.is_nan() { 0.0 } else { *x })
        .collect();
    let n = v.iter().filter(|x| !x.is_nan()).count();
    stewie_twin::numpy::sum(&kept) / n as f64
}

/// `np.nanpercentile(v, q)` with numpy's default linear method.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::many_single_char_names
)] // indices of a sorted copy; numpy's n, q, t, a, b, d
fn nanpercentile(v: &[f64], q_pct: f64) -> f64 {
    let mut s: Vec<f64> = v.iter().copied().filter(|x| !x.is_nan()).collect();
    if s.is_empty() {
        return f64::NAN;
    }
    s.sort_by(f64::total_cmp);
    let n = s.len() as f64;
    let q = q_pct / 100.0;
    // numpy's virtual index for alpha = beta = 1, in its order of operations (`alpha + q * (1 - alpha - beta)`
    // is exactly 1 - q)
    let vi = n * q + (1.0 - q) - 1.0;
    let prev = vi.floor().clamp(0.0, n - 1.0);
    let next = (prev + 1.0).min(n - 1.0);
    let t = vi - vi.floor();
    let (a, b) = (s[prev as usize], s[next as usize]);
    let d = b - a;
    if t >= 0.5 {
        b - d * (1.0 - t)
    } else {
        a + d * t
    }
}

fn nan_extreme(v: &[f64], max: bool) -> f64 {
    v.iter()
        .copied()
        .filter(|x| !x.is_nan())
        .reduce(if max { f64::max } else { f64::min })
        .unwrap_or(f64::NAN)
}

/// The veto reasons a blocked cell is attributed to, in the costmap's first-blocking order.
const SUITABILITY_REASONS: [&str; 7] = [
    "slope",
    "sinkage",
    "tip_risk",
    "negative_obstacle",
    "psr",
    "keepout",
    "reservation",
];

/// The stated rating band of the suitable-fraction score (a decision-support label, not a measurement).
fn grade(score: i64) -> &'static str {
    match score {
        90.. => "excellent",
        75..=89 => "good",
        50..=74 => "marginal",
        25..=49 => "poor",
        _ => "unsuitable",
    }
}

/// The SS-01 site-survey suitability (Python `gis_layers.site_suitability`): the fraction of the work-area cells
/// the AS-11 costmap passes (no weighting), the dominant first-blocking veto, and the crop's terrain statistics.
/// `sun_az_grid_deg` is the drape sun's azimuth re-expressed in the grid frame.
///
/// # Errors
/// A solve the physics refuses.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::too_many_lines
)] // cell counts; one payload
pub fn site_suitability(
    site: &str,
    crop: &[f64],
    rows: usize,
    cols: usize,
    cell_m: f64,
    sun_az_grid_deg: f64,
    s: &Spine,
) -> Result<Value, String> {
    let cm = drape_costmap(crop, cols, rows, cell_m, sun_az_grid_deg, MAX_SLOPE_DEG, s)?;
    let n = cm.passable.len();
    let n_suitable = cm.passable.iter().filter(|p| **p).count();
    let fraction = if n > 0 {
        n_suitable as f64 / n as f64
    } else {
        0.0
    };
    let score = (100.0 * fraction).round_ties_even() as i64;
    let mut counts: Vec<(&str, usize)> = SUITABILITY_REASONS
        .iter()
        .map(|name| {
            let c = cm
                .passable
                .iter()
                .zip(&cm.reason)
                .filter(|(p, r)| !**p && **r == Some(*name))
                .count();
            (*name, c)
        })
        .filter(|(_, c)| *c > 0)
        .collect();
    counts.sort_by_key(|(_, c)| std::cmp::Reverse(*c)); // stable: ties keep the veto order
    let blocking: Vec<Value> = counts
        .iter()
        .map(|(name, c)| json!({"reason": name, "count": c, "fraction": round(*c as f64 / n as f64, 6)}))
        .collect();
    let slope = slope_deg_grid(crop, cols, rows, cell_m);
    let mean = uniform_filter_nearest(&slope, cols, rows, 3);
    let sq: Vec<f64> = slope.iter().map(|x| x * x).collect();
    let mean_sq = uniform_filter_nearest(&sq, cols, rows, 3);
    let rough: Vec<f64> = mean_sq
        .iter()
        .zip(&mean)
        .map(|(q, m)| (q - m * m).max(0.0).sqrt() / 10.0)
        .collect();
    let lut = Terra::over(&slope, s)?;
    let at: Vec<TerraAt> = slope.iter().map(|x| lut.at(*x)).collect();
    let field = |f: fn(&TerraAt) -> f64| at.iter().map(f).collect::<Vec<f64>>();
    let (bearing, margin, sinkage) = (
        field(|a| a.bearing_pa),
        field(|a| a.traction_margin),
        field(|a| a.sinkage_m),
    );
    let r4 = |v: f64| round(v, 4);
    Ok(json!({
        "ok": true, "site": site,
        "score": score, "grade": grade(score),
        "suitable_fraction": round(fraction, 6),
        "n_cells": n, "n_suitable": n_suitable,
        "binding_constraint": counts.first().map(|(name, _)| *name),
        "blocking": blocking,
        "fields": {
            "slope_deg": {"mean": r4(nanmean(&slope)), "p95": r4(nanpercentile(&slope, 95.0)),
                          "max": r4(nan_extreme(&slope, true))},
            "roughness": {"mean": r4(nanmean(&rough)), "p95": r4(nanpercentile(&rough, 95.0))},
            "bearing_pa": {"mean": r4(nanmean(&bearing))},
            "traction_margin": {"mean": r4(nanmean(&margin)), "min": r4(nan_extreme(&margin, false))},
            "sinkage_m": {"mean": r4(nanmean(&sinkage)), "max": r4(nan_extreme(&sinkage, true))},
        },
        "thresholds": {"max_slope_deg": MAX_SLOPE_DEG, "max_sinkage_m": MAX_SINKAGE_M,
                       "max_drop_m": r4(cell_m * MAX_SLOPE_DEG.to_radians().tan())},
        "grid": {"rows": rows, "cols": cols, "cell_m": cell_m},
        "sun": {"el_deg": SUN_EL_DEG, "az_deg": SUN_AZ_DEG},
        "provenance": "FORGE costmap compose (lode.costmap_layers) + terramechanics spine (_terra_fields) + LY-05 \
                       roughness over the real site work-area crop; score = passable fraction, no invented weighting; \
                       grade band is a stated decision-support label",
    }))
}

/// A site's permanently-shadowed mask (SD-03; Python `gis_layers._site_psr_mask`): cells never lit across a
/// 0..330 deg azimuth sweep (every 30 deg) at 3 deg elevation, on the DEM strided to about 384 px. Returns the
/// stride, the strided grid's columns, and the never-lit mask.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid sizes
#[must_use]
pub fn psr_mask(dem: &SiteDem) -> (usize, usize, Vec<bool>) {
    let step = ((dem.rows.max(dem.cols) as f64 / 384.0).round_ties_even() as usize).max(1);
    let (sh, sw) = (dem.rows.div_ceil(step), dem.cols.div_ceil(step));
    let strided: Vec<f64> = (0..sh)
        .flat_map(|r| (0..sw).map(move |c| (r * step, c * step)))
        .map(|(r, c)| dem.z[r * dem.cols + c])
        .collect();
    let mut ever = vec![false; sh * sw];
    for az in (0..360).step_by(30) {
        let lit = horizon_clip(
            &strided,
            sw,
            sh,
            dem.cell_m * step as f64,
            f64::from(az),
            3.0,
        );
        for (e, l) in ever.iter_mut().zip(lit) {
            *e |= l;
        }
    }
    (step, sw, ever.into_iter().map(|e| !e).collect())
}

/// The SD-03 cross-section (Python `gis_layers.transect_profile`): per sample the elevation, slope, bearing and
/// sinkage the point query reads, the PSR flag, and the cumulative distance. `points` are order-frame metres, or
/// already resolved from lon/lat with `None` for a sample outside the tile (distance is carried, not advanced).
///
/// # Errors
/// A solve the physics refuses.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid indices
pub fn transect_profile(
    site: &str,
    points: &[Option<(f64, f64)>],
    dem: &SiteDem,
    origin: (f64, f64),
    view: &TerrainView,
    s: &Spine,
) -> Result<Value, String> {
    let (step, sw, psr) = psr_mask(dem);
    let sh = psr.len() / sw.max(1);
    let mut samples = Vec::with_capacity(points.len());
    let (mut prev, mut dist): (Option<(f64, f64)>, f64) = (None, 0.0);
    for p in points {
        let Some((x, y)) = *p else {
            samples.push(json!({"dist_m": round(dist, 2), "x_m": null, "y_m": null, "in_bounds": false,
                "elevation_m": null, "slope_deg": null, "bearing_pa": null, "sinkage_m": null, "psr": null}));
            continue;
        };
        if let Some((px, py)) = prev {
            dist += (x - px).hypot(y - py);
        }
        prev = Some((x, y));
        let pv = point_values(site, x, y, dem, origin, view, s)?;
        let value = |id: &str| {
            pv["attributes"]
                .as_array()
                .and_then(|a| a.iter().find(|r| r["id"] == id))
                .map_or(Value::Null, |r| r["value"].clone())
        };
        let col = ((origin.0 + x) / dem.cell_m).round_ties_even();
        let row = ((origin.1 + y) / dem.cell_m).round_ties_even();
        let in_b = row >= 0.0 && row < dem.rows as f64 && col >= 0.0 && col < dem.cols as f64;
        let flag = if in_b {
            let (dr, dc) = (row as usize / step, col as usize / step);
            (dr < sh && dc < sw).then(|| psr[dr * sw + dc])
        } else {
            None
        };
        samples.push(json!({
            "dist_m": round(dist, 2), "x_m": round(x, 2), "y_m": round(y, 2), "in_bounds": in_b,
            "elevation_m": value("base.dem"), "slope_deg": value("terrain.slope"),
            "bearing_pa": value("physics.bearing"), "sinkage_m": value("physics.sinkage"), "psr": flag,
        }));
    }
    Ok(json!({
        "ok": true, "site": site, "n": samples.len(), "samples": samples,
        "sources": {
            "elevation_m": "LOLA DEM (base.dem, prior/observed)",
            "slope_deg": "derived from the DEM gradient",
            "bearing_pa": "terramechanics spine (physics.bearing, derived/estimated)",
            "sinkage_m": "terramechanics spine (physics.sinkage, derived/estimated)",
            "psr": "permanently-shadowed = never lit across a 0..360 deg sun-azimuth sweep at 3 deg elevation \
                    (dart.illumination horizon-clip on the real DEM)",
        },
        "unavailable": {
            "ice_stability": "NO real per-cell producer -- terrain.thermal is catalog-only (no Diviner/thermal \
                              ice-stability raster wired). NOT fabricated. PSR (cold-trap candidate) is the real \
                              ice-relevant proxy; a quantitative depth-to-ice needs a Diviner/LOLA thermal dataset.",
        },
    }))
}

/// The costmap layers that are physical terrain barriers (the PSR veto, keep-outs and reservations are not).
const HAZARD_LAYERS: [&str; 4] = ["slope", "sinkage", "tip_risk", "negative_obstacle"];
/// The keep-out output's caps: regions, then vertices.
const MAX_POLYS: usize = 400;
const MAX_VERTICES: usize = 100_000;

/// The absolute shoelace area [m^2] of a ring of projected metres (Python `gis_layers._ring_area_m2`).
fn ring_area_m2(ring: &[[f64; 2]]) -> f64 {
    let n = ring.len();
    if n < 3 {
        return 0.0;
    }
    let (mut a, mut b) = (0.0, 0.0);
    for i in 0..n {
        let next = ring[(i + 1) % n];
        a += ring[i][0] * next[1];
        b += ring[i][1] * next[0];
    }
    (a - b).abs() / 2.0
}

/// Drop the vertices exactly collinear with their neighbours (Python `gis_layers._dedup_collinear`), re-closing
/// the ring; a ring that would degenerate keeps its distinct vertices.
#[allow(clippy::many_single_char_names)] // the Python's n, m, p, c, q
fn dedup_collinear(ring: &[[f64; 2]]) -> Vec<[f64; 2]> {
    let n = ring.len();
    if n <= 3 {
        return ring.to_vec();
    }
    let close = |a: f64, b: f64| (a - b).abs() <= 1e-8 + 1e-5 * b.abs();
    let (first, last) = (ring[0], ring[n - 1]);
    let pts = if close(first[0], last[0]) && close(first[1], last[1]) {
        &ring[..n - 1]
    } else {
        ring
    };
    let m = pts.len();
    let mut keep: Vec<[f64; 2]> = (0..m)
        .filter(|&i| {
            let (p, c, q) = (pts[(i + m - 1) % m], pts[i], pts[(i + 1) % m]);
            ((c[0] - p[0]) * (q[1] - p[1]) - (c[1] - p[1]) * (q[0] - p[0])).abs() > 1e-6
        })
        .map(|i| pts[i])
        .collect();
    if keep.len() < 3 {
        keep = pts.to_vec();
    }
    keep.push(keep[0]);
    keep
}

/// Council #52's hazard keep-outs (Python `gis_layers.hazard_keepouts_geojson`): the physical terrain-hazard
/// no-go mask of the work-area crop, traced by the contourpy port, reprojected to selenographic lon/lat, as a
/// `GeoJSON` `FeatureCollection` of polygons; regions whose outer ring is under `min_area_m2` are dropped and
/// counted. `crop` sits at `(r0, c0)` in `dem`, whose frame `proj` inverts.
///
/// # Errors
/// A solve the physics refuses, or a crop the tracer refuses.
#[allow(
    clippy::cast_precision_loss,
    clippy::too_many_arguments,
    clippy::too_many_lines
)] // grid indices; the Python's inputs; one payload
pub fn hazard_keepouts(
    site: &str,
    crop: &[f64],
    (rows, cols): (usize, usize),
    (r0, c0): (usize, usize),
    dem: &SiteDem,
    proj: &lunar_frames::PolarStereographic,
    min_area_m2: f64,
    max_slope_deg: f64,
    s: &Spine,
) -> Result<Value, String> {
    let cell = dem.cell_m;
    let cm = drape_costmap(crop, cols, rows, cell, SUN_AZ_DEG, max_slope_deg, s)?;
    let nogo: Vec<f64> = cm
        .reason
        .iter()
        .map(|r| f64::from(u8::from(r.is_some_and(|r| HAZARD_LAYERS.contains(&r)))))
        .collect();
    let n_nogo = nogo.iter().filter(|v| **v > 0.0).count();
    let per_block: serde_json::Map<String, Value> = cm
        .per_layer
        .iter()
        .filter(|(name, _, _)| HAZARD_LAYERS.contains(name))
        .map(|(name, _, blocked)| ((*name).to_owned(), json!(blocked)))
        .collect();
    // crop pixel to tile-frame metres, point-registered over the full tile's extent
    let [x0, y0, x1, y1] = dem.bounds_m;
    let (wd, hd) = (
        dem.cols.saturating_sub(1).max(1) as f64,
        dem.rows.saturating_sub(1).max(1) as f64,
    );
    let xs: Vec<f64> = (0..cols)
        .map(|k| x0 + (x1 - x0) * (c0 + k) as f64 / wd)
        .collect();
    let ys: Vec<f64> = (0..rows)
        .map(|k| y1 - (y1 - y0) * (r0 + k) as f64 / hd)
        .collect();
    let (mut features, mut n_vertices, mut n_specks, mut truncated) = (Vec::new(), 0, 0, false);
    if n_nogo > 0 {
        for (pts, offs) in crate::contour::filled(&xs, &ys, &nogo, 0.5, 2.0)? {
            let rings: Vec<&[[f64; 2]]> = offs.windows(2).map(|w| &pts[w[0]..w[1]]).collect();
            if rings.first().is_none_or(|r| ring_area_m2(r) < min_area_m2) {
                n_specks += 1;
                continue;
            }
            let coords: Vec<Value> = rings
                .iter()
                .filter_map(|ring| {
                    let line: Vec<Value> = dedup_collinear(ring)
                        .iter()
                        .map(|p| {
                            let ll = proj.inverse(p[0], p[1]);
                            json!([round(ll.lon_deg, 6), round(ll.lat_deg, 6)])
                        })
                        .collect();
                    (line.len() >= 4).then(|| {
                        n_vertices += line.len();
                        Value::Array(line)
                    })
                })
                .collect();
            if coords.is_empty() {
                continue;
            }
            features.push(json!({"type": "Feature",
                "properties": {"kind": "hazard_keepout", "area_m2": round(ring_area_m2(rings[0]), 2),
                               "holes": coords.len() - 1},
                "geometry": {"type": "Polygon", "coordinates": coords}}));
            if features.len() >= MAX_POLYS || n_vertices >= MAX_VERTICES {
                truncated = true;
                break;
            }
        }
    }
    let cells = nogo.len();
    Ok(json!({"type": "FeatureCollection",
        "properties": {"site": site, "crs": "OGC:CRS84", "n_features": features.len(),
            "n_specks_dropped": n_specks, "nogo_cells": n_nogo, "grid_cells": cells,
            "nogo_fraction": if cells > 0 { round(n_nogo as f64 / cells as f64, 6) } else { 0.0 },
            "hazard_gate": HAZARD_LAYERS, "per_layer_block": per_block,
            "thresholds": {"max_slope_deg": max_slope_deg, "min_area_m2": min_area_m2},
            "grid": {"rows": rows, "cols": cols, "cell_m": cell},
            "truncated": truncated,
            "source": "FORGE costmap terrain-hazard impassable mask (lode.costmap_layers: \
                       slope/sinkage/tip_risk/negative_obstacle; PSR-shadow + operator keepout + reservation \
                       EXCLUDED) traced by contourpy over the real work-area crop, reprojected to selenographic \
                       lon/lat",
            "eligibility": "mission keep-outs (the planner routes around them)"},
        "features": features}))
}

#[cfg(test)]
#[allow(clippy::float_cmp)] // exact by construction
mod tests {
    use super::np_interp;

    #[test]
    fn interp_is_numpys() {
        // SYNTHETIC knots: the end values outside, the knot value on a knot, linear between
        let (xp, fp) = ([0.0, 1.0, 3.0], [10.0, 20.0, 0.0]);
        assert_eq!(np_interp(-1.0, &xp, &fp), 10.0);
        assert_eq!(np_interp(4.0, &xp, &fp), 0.0);
        assert_eq!(np_interp(3.0, &xp, &fp), 0.0);
        assert_eq!(np_interp(1.0, &xp, &fp), 20.0);
        assert_eq!(np_interp(2.0, &xp, &fp), 10.0);
        assert!(np_interp(f64::NAN, &xp, &fp).is_nan());
    }
}
