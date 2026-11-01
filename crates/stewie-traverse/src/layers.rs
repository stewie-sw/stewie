//! The AS-11 layered costmap (Python `lode.costmap_layers`): the per-cell navigation cost composed from twelve
//! named layers (slope, roughness, sinkage, slip, tip risk, negative obstacle, illumination, PSR, shadow
//! confidence, energy, keep-out, reservation) plus the data-driven rock hazard, each adding a traversal cost or
//! marking cells impassable, with the first blocking layer recorded per cell so a refused route can name its
//! reason. Every layer reads a real source; the caller supplies the rover, soil and sun (no compiled defaults).
//!
//! The local-horizon shadow is `horizon_clip`, the bilinear up-Sun march (M-07), distinct from the nearest-cell
//! [`crate::illumination::cast_shadow_mask`] the routing illumination cost uses.

use lunar_dem::{slope_deg_grid, uniform_filter_nearest};
use stewie_physics::soil::SoilParams;
use stewie_physics::stability::tip_tilt_limit_deg;
use stewie_physics::terra::contact_static_sinkage;

use crate::costmap::negative_obstacle_mask;
use crate::illumination::sun_march_dir_rowcol;

/// The twelve always-on layers, in blocking-precedence order (the first impassable layer is a cell's reason).
pub const LAYER_NAMES: [&str; 12] = [
    "slope",
    "roughness",
    "sinkage",
    "slip",
    "tip_risk",
    "negative_obstacle",
    "illumination",
    "psr",
    "shadow_confidence",
    "energy",
    "keepout",
    "reservation",
];

/// The rover's figures the layers read.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Rover {
    pub gauge_m: f64,
    pub wheelbase_m: f64,
    pub cg_height_m: f64,
    pub mass_dry_kg: f64,
    pub n_wheels: u32,
    pub contact_len_m: f64,
    pub contact_width_m: f64,
    /// The traversable rock height [m].
    pub obstacle_height_m: f64,
    /// The flat-drive power model: rolling resistance, drive speed [m/s], drivetrain efficiency.
    pub rolling_resistance: f64,
    pub drive_speed_ms: f64,
    pub drivetrain_efficiency: f64,
}

/// A rock clast in the DEM window's metric frame (`x` = col * cell, `z` = row * cell).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Clast {
    pub x_m: f64,
    pub z_m: f64,
    pub radius_m: f64,
    pub buried_frac: f64,
}

/// One composition's inputs (Python `CostmapContext`).
#[derive(Debug, Clone)]
pub struct Context<'a> {
    pub z: &'a [f64],
    pub width: usize,
    pub height: usize,
    pub cell_m: f64,
    pub max_slope_deg: f64,
    pub slip_alpha: f64,
    pub max_drop_m: f64,
    pub sun_az_deg: f64,
    pub sun_el_deg: f64,
    pub payload_kg: f64,
    /// The burial depth past which a cell is impassable [m].
    pub max_sinkage_m: f64,
    pub gravity_ms2: f64,
    pub soil: SoilParams,
    pub rover: Rover,
    pub keepout: Option<&'a [bool]>,
    pub reserved: Option<&'a [bool]>,
    pub clasts: &'a [Clast],
}

/// The composed costmap.
#[derive(Debug, Clone, PartialEq)]
pub struct Composite {
    /// 1 per metre plus every layer's cost.
    pub cost: Vec<f64>,
    pub passable: Vec<bool>,
    /// The first blocking layer per cell, `None` where passable.
    pub reason: Vec<Option<&'static str>>,
    /// Each layer's total cost and blocked-cell count, in composition order.
    pub per_layer: Vec<(&'static str, f64, usize)>,
}

/// Per-pixel solar incidence angle [deg] (Python `illumination.incidence_angle_deg`): the angle between the
/// surface normal from the DEM gradient and the Sun direction; 90 is grazing, above 90 faces away.
#[must_use]
pub fn incidence_angle_deg(
    z: &[f64],
    width: usize,
    height: usize,
    cell_m: f64,
    sun_az_deg: f64,
    sun_el_deg: f64,
) -> Vec<f64> {
    let (el, az) = (sun_el_deg.to_radians(), sun_az_deg.to_radians());
    let (sx, sy, sz) = (az.sin() * el.cos(), el.sin(), az.cos() * el.cos());
    let at = |r: usize, c: usize| z[r * width + c];
    // numpy gradient: central inside, one-sided at the edges
    let grad = |lo: f64, hi: f64, span: f64| (hi - lo) / span;
    (0..z.len())
        .map(|i| {
            let (r, c) = (i / width, i % width);
            let d_col = if width < 2 {
                0.0
            } else if c == 0 {
                grad(at(r, 0), at(r, 1), cell_m)
            } else if c == width - 1 {
                grad(at(r, c - 1), at(r, c), cell_m)
            } else {
                grad(at(r, c - 1), at(r, c + 1), 2.0 * cell_m)
            };
            let d_row = if height < 2 {
                0.0
            } else if r == 0 {
                grad(at(0, c), at(1, c), cell_m)
            } else if r == height - 1 {
                grad(at(r - 1, c), at(r, c), cell_m)
            } else {
                grad(at(r - 1, c), at(r + 1, c), 2.0 * cell_m)
            };
            let (nx, ny, nz) = (-d_col, 1.0, -d_row);
            let nmag = (nx * nx + ny * ny + nz * nz).sqrt();
            let cos_inc = (nx * sx + ny * sy + nz * sz) / nmag;
            cos_inc.clamp(-1.0, 1.0).acos().to_degrees()
        })
        .collect()
}

/// The local-horizon illuminated mask (Python `illumination.horizon_clip`, M-07): marching one cell at a time
/// toward the Sun and sampling the terrain bilinearly, a cell is lit unless some sample rises above its line of
/// sight. Nothing is lit with the Sun at or below the horizon; a non-finite cell is never claimed lit, nor
/// occludes.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
pub fn horizon_clip(
    z: &[f64],
    width: usize,
    height: usize,
    cell_m: f64,
    sun_az_deg: f64,
    sun_el_deg: f64,
) -> Vec<bool> {
    if sun_el_deg <= 0.0 {
        return vec![false; z.len()];
    }
    let tan_el = sun_el_deg.to_radians().tan();
    let (d_row, d_col) = sun_march_dir_rowcol(sun_az_deg);
    let max_steps = (height as f64).hypot(width as f64) as usize + 1;
    let occ = |i: usize| {
        if z[i].is_finite() {
            z[i]
        } else {
            f64::NEG_INFINITY
        }
    };
    let (hr, wc) = (height as f64 - 1.0, width as f64 - 1.0);
    let mut lit = vec![true; z.len()];
    for k in 1..=max_steps {
        let kf = k as f64;
        let mut any_in = false;
        for (i, l) in lit.iter_mut().enumerate() {
            let (r, c) = ((i / width) as f64, (i % width) as f64);
            let (sr, sc) = (r + kf * d_row, c + kf * d_col);
            if !(sr >= 0.0 && sr <= hr && sc >= 0.0 && sc <= wc) {
                continue;
            }
            any_in = true;
            if !*l {
                continue;
            }
            // the bilinear stencil, its lower corner held inside the grid
            let r0 = (sr.floor() as usize).min(height.saturating_sub(2));
            let c0 = (sc.floor() as usize).min(width.saturating_sub(2));
            let fr = (sr - r0 as f64).clamp(0.0, 1.0);
            let fc = (sc - c0 as f64).clamp(0.0, 1.0);
            let (h00, h01) = (occ(r0 * width + c0), occ(r0 * width + c0 + 1));
            let (h10, h11) = (occ((r0 + 1) * width + c0), occ((r0 + 1) * width + c0 + 1));
            let sample = (1.0 - fr) * (1.0 - fc) * h00
                + (1.0 - fr) * fc * h01
                + fr * (1.0 - fc) * h10
                + fr * fc * h11;
            if sample > z[i] + kf * cell_m * tan_el {
                *l = false;
            }
        }
        if !any_in {
            break;
        }
    }
    for (l, h) in lit.iter_mut().zip(z) {
        *l &= h.is_finite();
    }
    lit
}

/// The per-cell maximum exposed rock height [m]: a clast protrudes `2 r (1 - buried)`, stamped over its disk
/// (cell centres within `r`), or over the cell it sits in when its disk clears every centre.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap
)]
pub fn rock_exposed_height_grid(
    width: usize,
    height: usize,
    cell_m: f64,
    clasts: &[Clast],
) -> Vec<f64> {
    let mut grid = vec![0.0_f64; width * height];
    for c in clasts {
        let h = 2.0 * c.radius_m * (1.0 - c.buried_frac);
        if h <= 0.0 {
            continue;
        }
        let (cc, cr, rad) = (c.x_m / cell_m, c.z_m / cell_m, c.radius_m / cell_m);
        // the Python's window: max(0, floor) .. min(n - 1, ceil), empty when the clast lies off the grid
        let (c_lo, c_hi) = (
            ((cc - rad).floor() as i64).max(0),
            ((cc + rad).ceil() as i64).min(width as i64 - 1),
        );
        let (r_lo, r_hi) = (
            ((cr - rad).floor() as i64).max(0),
            ((cr + rad).ceil() as i64).min(height as i64 - 1),
        );
        let mut covered = false;
        for rr in r_lo..=r_hi {
            for col in c_lo..=c_hi {
                #[allow(clippy::cast_precision_loss)]
                let (dr, dc) = (rr as f64 - cr, col as f64 - cc);
                if dr * dr + dc * dc <= rad * rad {
                    let cell = &mut grid[rr as usize * width + col as usize];
                    *cell = cell.max(h);
                    covered = true;
                }
            }
        }
        if !covered {
            let ri = (cr.round_ties_even() as i64).clamp(0, height as i64 - 1) as usize;
            let ci = (cc.round_ties_even() as i64).clamp(0, width as i64 - 1) as usize;
            grid[ri * width + ci] = grid[ri * width + ci].max(h);
        }
    }
    grid
}

/// Compose the costmap: every layer's cost summed onto 1, the impassable masks OR-ed, the first blocking layer
/// recorded; the rock hazard joins when there are clasts.
///
/// # Errors
/// A soil the sinkage model refuses.
#[allow(clippy::too_many_lines)] // one block per layer, in the Python's order
pub fn compose(ctx: &Context<'_>) -> Result<Composite, String> {
    let n = ctx.z.len();
    let (w, h, cell) = (ctx.width, ctx.height, ctx.cell_m);
    let slope = slope_deg_grid(ctx.z, w, h, cell);
    let lit = horizon_clip(ctx.z, w, h, cell, ctx.sun_az_deg, ctx.sun_el_deg);
    let tan_cap = |s: f64| s.min(89.0).to_radians().tan();
    let none = vec![false; n];
    let zeros = vec![0.0; n];

    let mut layers: Vec<(&'static str, Vec<f64>, Vec<bool>)> = Vec::with_capacity(13);
    layers.push((
        "slope",
        slope.iter().map(|s| ctx.slip_alpha * tan_cap(*s)).collect(),
        slope.iter().map(|s| *s > ctx.max_slope_deg).collect(),
    ));
    let sq: Vec<f64> = slope.iter().map(|s| s * s).collect();
    let (mean, mean_sq) = (
        uniform_filter_nearest(&slope, w, h, 3),
        uniform_filter_nearest(&sq, w, h, 3),
    );
    layers.push((
        "roughness",
        mean.iter()
            .zip(&mean_sq)
            .map(|(m, m2)| (m2 - m * m).max(0.0).sqrt() / 10.0)
            .collect(),
        none.clone(),
    ));
    let rv = &ctx.rover;
    let load =
        (rv.mass_dry_kg + ctx.payload_kg.max(0.0)) * ctx.gravity_ms2 / f64::from(rv.n_wheels);
    let sink = contact_static_sinkage(load, rv.contact_len_m, rv.contact_width_m, None, &ctx.soil)
        .map_err(|e| e.to_string())?;
    layers.push((
        "sinkage",
        vec![sink / ctx.max_sinkage_m.max(1e-6); n],
        vec![sink > ctx.max_sinkage_m; n],
    ));
    layers.push((
        "slip",
        slope.iter().map(|s| tan_cap(*s)).collect(),
        none.clone(),
    ));
    let tip = tip_tilt_limit_deg(rv.gauge_m, rv.wheelbase_m, rv.cg_height_m);
    layers.push((
        "tip_risk",
        zeros.clone(),
        slope.iter().map(|s| *s > tip).collect(),
    ));
    layers.push((
        "negative_obstacle",
        zeros.clone(),
        negative_obstacle_mask(ctx.z, w, h, ctx.max_drop_m),
    ));
    let inc = incidence_angle_deg(ctx.z, w, h, cell, ctx.sun_az_deg, ctx.sun_el_deg);
    layers.push((
        "illumination",
        inc.iter().map(|a| a.clamp(0.0, 90.0) / 90.0).collect(),
        none.clone(),
    ));
    layers.push(("psr", zeros.clone(), lit.iter().map(|l| !l).collect()));
    layers.push((
        "shadow_confidence",
        lit.iter().map(|l| if *l { 0.0 } else { 1.0 }).collect(),
        none.clone(),
    ));
    // the grade-dependent flat-drive power over the level figure, minus one (Python `lunar_drive_power_w`)
    let power = |s: f64| {
        let th = s.abs().min(30.0).to_radians();
        let f = rv.mass_dry_kg * ctx.gravity_ms2 * (rv.rolling_resistance * th.cos() + th.sin());
        f * rv.drive_speed_ms / rv.drivetrain_efficiency
    };
    let base = power(0.0);
    layers.push((
        "energy",
        slope.iter().map(|s| power(*s) / base - 1.0).collect(),
        none.clone(),
    ));
    layers.push((
        "keepout",
        zeros.clone(),
        ctx.keepout.map_or_else(|| none.clone(), <[bool]>::to_vec),
    ));
    layers.push((
        "reservation",
        zeros.clone(),
        ctx.reserved.map_or_else(|| none.clone(), <[bool]>::to_vec),
    ));
    if !ctx.clasts.is_empty() {
        let lim = rv.obstacle_height_m;
        let g = rock_exposed_height_grid(w, h, cell, ctx.clasts);
        layers.push((
            "rock_hazard",
            g.iter().map(|x| x / lim.max(1e-6)).collect(),
            g.iter().map(|x| *x > lim).collect(),
        ));
    }

    let mut cost = vec![1.0; n];
    let mut passable = vec![true; n];
    let mut reason = vec![None; n];
    let mut per_layer = Vec::with_capacity(layers.len());
    for (name, c, block) in layers {
        for i in 0..n {
            cost[i] += c[i];
            if block[i] && passable[i] {
                reason[i] = Some(name);
            }
            passable[i] &= !block[i];
        }
        per_layer.push((
            name,
            c.iter().filter(|x| !x.is_nan()).sum(),
            block.iter().filter(|b| **b).count(),
        ));
    }
    Ok(Composite {
        cost,
        passable,
        reason,
        per_layer,
    })
}
