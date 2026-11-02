//! The analysis-layer rasters (RW-55b6c-1; Python `gis_layers._layer_rgba` and its helpers): each layer's colouring
//! as a function of a DEM patch and its cell size, row-major RGBA. Relief is a Lambertian hillshade; slope,
//! hazard, aspect and curvature come from numpy's `gradient`; illumination, PSR and incidence from the real local
//! horizon; roughness is the costmap's window-RMS slope. Floats are cast to bytes by truncation, as numpy's
//! `astype("uint8")`.

use lunar_dem::{uniform_filter_nearest, uniform_filter_reflect};
use stewie_traverse::layers::{horizon_clip, incidence_angle_deg};

use crate::point::{Spine, Terra, drape_costmap, grid_sun_az, np_interp, py_mod};

/// numpy's `gradient(z, cell)` on a row-major grid: `(d/drow, d/dcol)`, central inside, one-sided on the border.
#[must_use]
pub fn gradient(z: &[f64], w: usize, h: usize, cell: f64) -> (Vec<f64>, Vec<f64>) {
    let at = |r: usize, c: usize| z[r * w + c];
    let d = |lo: f64, hi: f64, span: f64| (hi - lo) / span;
    let mut gy = Vec::with_capacity(z.len());
    let mut gx = Vec::with_capacity(z.len());
    for r in 0..h {
        for c in 0..w {
            gx.push(if w < 2 {
                0.0
            } else if c == 0 {
                d(at(r, 0), at(r, 1), cell)
            } else if c == w - 1 {
                d(at(r, c - 1), at(r, c), cell)
            } else {
                d(at(r, c - 1), at(r, c + 1), 2.0 * cell)
            });
            gy.push(if h < 2 {
                0.0
            } else if r == 0 {
                d(at(0, c), at(1, c), cell)
            } else if r == h - 1 {
                d(at(r - 1, c), at(r, c), cell)
            } else {
                d(at(r - 1, c), at(r + 1, c), 2.0 * cell)
            });
        }
    }
    (gy, gx)
}

fn slope_of(gy: &[f64], gx: &[f64]) -> Vec<f64> {
    gx.iter()
        .zip(gy)
        .map(|(x, y)| x.hypot(*y).atan().to_degrees())
        .collect()
}

/// numpy's `astype("uint8")` of a value already in range (truncation; NaN as 0).
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // the cast is the point
fn u8_of(v: f64) -> u8 {
    v as u8
}

/// `np.percentile(v, q)` over the finite values (numpy's linear rule), or `default` when there are none.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::many_single_char_names
)] // indices of a sorted copy; numpy's n, q, t, a, b
fn percentile(v: &[f64], q_pct: f64, default: f64) -> f64 {
    let mut s: Vec<f64> = v.iter().copied().filter(|x| x.is_finite()).collect();
    if s.is_empty() {
        return default;
    }
    s.sort_by(f64::total_cmp);
    let n = s.len() as f64;
    let q = q_pct / 100.0;
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

/// Piecewise-linear RGB along `(t, (r, g, b))` stops (Python `_ramp_rgb`, per channel `np.interp`).
fn ramp(t: f64, stops: &[(f64, [f64; 3])]) -> [f64; 3] {
    let t = t.clamp(0.0, 1.0);
    let ts: Vec<f64> = stops.iter().map(|s| s.0).collect();
    let mut out = [0.0; 3];
    for (k, o) in out.iter_mut().enumerate() {
        let fs: Vec<f64> = stops.iter().map(|s| s.1[k]).collect();
        *o = np_interp(t, &ts, &fs);
    }
    out
}

const CURV_DIVERGING: [(f64, [f64; 3]); 3] = [
    (0.0, [33.0, 102.0, 172.0]),
    (0.5, [247.0, 247.0, 247.0]),
    (1.0, [178.0, 24.0, 43.0]),
];
const ROUGH_SEQUENTIAL: [(f64, [f64; 3]); 3] = [
    (0.0, [255.0, 255.0, 217.0]),
    (0.5, [65.0, 182.0, 196.0]),
    (1.0, [34.0, 39.0, 110.0]),
];

/// Python `_hsv_to_rgb` for one pixel.
#[allow(clippy::cast_possible_truncation, clippy::many_single_char_names)] // a sector index; HSV's names
fn hsv_to_rgb(h: f64, s: f64, v: f64) -> [f64; 3] {
    let h = py_mod(h, 1.0);
    let (s, v) = (s.clamp(0.0, 1.0), v.clamp(0.0, 1.0));
    let h6 = h * 6.0;
    let i = (h6.floor() as i64).rem_euclid(6);
    let f = h6 - h6.floor();
    let (p, q, t) = (v * (1.0 - s), v * (1.0 - f * s), v * (1.0 - (1.0 - f) * s));
    match i {
        0 => [v, t, p],
        1 => [q, v, p],
        2 => [p, v, t],
        3 => [p, q, v],
        4 => [t, p, v],
        _ => [v, p, q],
    }
}

/// The slope layer under the graduated renderer (G5): `vmax` the ramp's domain [deg] (at least 1), `classes` >= 2 an
/// equal-interval classified ramp instead of the stretch.
#[must_use]
pub fn slope_rgba(z: &[f64], w: usize, h: usize, cell: f64, vmax: f64, classes: usize) -> Vec<u8> {
    let (gy, gx) = gradient(z, w, h, cell);
    let vmax = vmax.max(1.0);
    #[allow(clippy::cast_precision_loss)] // a class count of at most 12
    let bands = classes as f64;
    slope_of(&gy, &gx)
        .into_iter()
        .flat_map(|s| {
            let mut t = (s / vmax).clamp(0.0, 1.0);
            if classes >= 2 {
                t = (t * bands).floor().clamp(0.0, bands - 1.0) / (bands - 1.0);
            }
            [60.0 + 195.0 * t, 200.0 * (1.0 - t), 40.0, 90.0 + 120.0 * t].map(u8_of)
        })
        .collect()
}

/// The hazard map's geometric layers (Python `dart.dem_cross.dem_layers`): the slope [deg] from numpy's gradient,
/// and the roughness, the 5-cell windowed height std (scipy `uniform_filter`, reflect edges), NaN kept as numpy's
/// `clip` keeps it so nodata stays unknown.
#[must_use]
pub fn hazard_layers(z: &[f64], w: usize, h: usize, cell: f64) -> (Vec<f64>, Vec<f64>) {
    let (gy, gx) = gradient(z, w, h, cell);
    let slope = slope_of(&gy, &gx);
    let sq: Vec<f64> = z.iter().map(|v| v * v).collect();
    let (mean, mean_sq) = (
        uniform_filter_reflect(z, w, h, 5),
        uniform_filter_reflect(&sq, w, h, 5),
    );
    let rough = (0..z.len())
        .map(|i| {
            let var = mean_sq[i] - mean[i] * mean[i];
            if var.is_nan() {
                f64::NAN
            } else {
                var.max(0.0).sqrt()
            }
        })
        .collect();
    (slope, rough)
}

/// The surveyed work-area hazard: the navigation cost the routing detours on (Python `dart.hazard_map.
/// build_hazard_map` with no rocks or zones, over `dem_cross.dem_layers`) drawn red, graded from benign
/// (transparent) to costly, opaque where no-go (slope at the 20 deg tested limit, or no data).
#[must_use]
pub fn hazard_cost_rgba(z: &[f64], w: usize, h: usize, cell: f64) -> Vec<u8> {
    let (slope, roughness) = hazard_layers(z, w, h, cell);
    (0..z.len())
        .flat_map(|i| {
            let rough = roughness[i];
            let s = slope[i];
            let mut cost = 1.0;
            cost += ((s - 15.0) / 10.0).max(0.0);
            cost += ((rough - 0.075) / 0.1).max(0.0) * 0.5;
            let nogo = s >= 20.0 || !s.is_finite() || !rough.is_finite() || !cost.is_finite();
            if nogo {
                [255.0, 0.0, 0.0, 230.0].map(u8_of)
            } else {
                let graded = ((cost - 1.0) / 4.0).clamp(0.0, 1.0);
                [255.0, 140.0 * (1.0 - graded), 0.0, 170.0 * graded].map(u8_of)
            }
        })
        .collect()
}

/// The TW-11 traffic layer from a site's relative density `dr` and pass counts: colour the Dr band (loose
/// `#f7f7f7` to paved `#252525`), opacity the hardening normalised to the layer's peak on driven cells.
#[must_use]
pub fn traffic_rgba(dr: &[f64], passes: &[u32]) -> Vec<u8> {
    const THRESHOLDS: [f64; 4] = [0.2, 0.4, 0.6, 0.8];
    const COLORS: [[f64; 3]; 5] = [
        [247.0, 247.0, 247.0],
        [204.0, 204.0, 204.0],
        [150.0, 150.0, 150.0],
        [99.0, 99.0, 99.0],
        [37.0, 37.0, 37.0],
    ];
    // numpy max: NaN if any
    let peak = dr.iter().copied().fold(f64::NEG_INFINITY, |m, x| {
        if x.is_nan() || m.is_nan() {
            f64::NAN
        } else {
            m.max(x)
        }
    });
    dr.iter()
        .zip(passes)
        .flat_map(|(&d, &p)| {
            // numpy digitize (right=False): how many thresholds are <= d; NaN sorts past them all
            let band = if d.is_nan() {
                4
            } else {
                THRESHOLDS.iter().filter(|&&t| t <= d).count()
            };
            let norm = if peak > 0.0 { d / peak } else { 0.0 };
            let [r, g, b] = COLORS[band];
            [r, g, b, if p > 0 { 60.0 + 180.0 * norm } else { 0.0 }].map(u8_of)
        })
        .collect()
}

/// Python `gis_layers._upscale`: each pixel repeated `k` times along both axes.
#[must_use]
pub fn upscale(rgba: &[u8], w: usize, h: usize, k: usize) -> Vec<u8> {
    let mut out = Vec::with_capacity(rgba.len() * k * k);
    for r in 0..h {
        let row: Vec<u8> = (0..w)
            .flat_map(|c| {
                std::iter::repeat_n(&rgba[(r * w + c) * 4..(r * w + c) * 4 + 4], k)
                    .flatten()
                    .copied()
            })
            .collect();
        for _ in 0..k {
            out.extend_from_slice(&row);
        }
    }
    out
}

/// The LY-07 signed terrain change (Python `gis_layers._changed_terrain_rgba`): as-built minus base [m], cut red,
/// fill blue, scaled by the 98th percentile of the changed cells' magnitude; an unchanged cell (|d| <= 1e-6 m) is
/// transparent, a change at least faintly opaque.
#[must_use]
#[allow(clippy::many_single_char_names, clippy::manual_midpoint)] // the Python's d, t, r, g, b; its (t + 1) / 2
pub fn changed_terrain_rgba(d: &[f64]) -> Vec<u8> {
    const STOPS: [(f64, [f64; 3]); 3] = [
        (0.0, [178.0, 24.0, 43.0]),
        (0.5, [247.0, 247.0, 247.0]),
        (1.0, [33.0, 102.0, 172.0]),
    ];
    let moved = |v: f64| v.abs() > 1e-6;
    let vals: Vec<f64> = d.iter().filter(|v| moved(**v)).map(|v| v.abs()).collect();
    let mut scale = if vals.is_empty() {
        1.0
    } else {
        percentile(&vals, 98.0, 1.0)
    };
    if scale <= 0.0 {
        scale = 1e-9;
    }
    d.iter()
        .flat_map(|&v| {
            let t = (v / scale).clamp(-1.0, 1.0);
            let [r, g, b] = ramp((t + 1.0) / 2.0, &STOPS);
            [
                r,
                g,
                b,
                if moved(v) {
                    90.0 + 165.0 * t.abs()
                } else {
                    0.0
                },
            ]
            .map(u8_of)
        })
        .collect()
}

/// One layer's RGBA bytes (row-major, `w * h * 4`) for a DEM patch, or `None` for a kind this renderer does not
/// draw. `grid_north_bearing` re-expresses a true sun azimuth in the grid frame for the sun-parameterised layers.
#[must_use]
#[allow(
    clippy::too_many_lines,
    clippy::many_single_char_names,
    clippy::too_many_arguments,
    clippy::manual_midpoint
)] // one dispatch, as the Python; its names and inputs; its (t + 1) / 2, bit for bit
pub fn layer_rgba(
    z: &[f64],
    w: usize,
    h: usize,
    cell: f64,
    kind: &str,
    sun_az: f64,
    sun_el: f64,
    grid_north_bearing: Option<f64>,
) -> Option<Vec<u8>> {
    let n = z.len();
    let grid_az = || grid_north_bearing.map_or(sun_az, |b| grid_sun_az(sun_az, b));
    let mut out = Vec::with_capacity(n * 4);
    let mut push = |px: [f64; 4]| out.extend(px.map(u8_of));
    match kind {
        "dem" | "hillshade" => {
            let (gy, gx) = gradient(z, w, h, cell);
            let (az, el) = (sun_az.to_radians(), sun_el.to_radians());
            let (lx, ly, lz) = (el.cos() * az.sin(), el.cos() * az.cos(), el.sin());
            for i in 0..n {
                let (nx, ny) = (-gx[i], -gy[i]);
                let norm = (nx * nx + ny * ny + 1.0).sqrt();
                let shade = ((nx * lx + ny * ly + lz) / norm).clamp(0.0, 1.0);
                let g = 40.0 + shade * 200.0;
                push([g, g, g, 255.0]);
            }
        }
        "slope" => return Some(slope_rgba(z, w, h, cell, 30.0, 0)),
        "hazard" => {
            let (gy, gx) = gradient(z, w, h, cell);
            for s in slope_of(&gy, &gx) {
                let nogo = s > 20.0;
                let graded = ((s - 15.0) / 5.0).clamp(0.0, 1.0);
                let g = if nogo { 0.0 } else { 140.0 * (1.0 - graded) };
                push([255.0, g, 0.0, if nogo { 230.0 } else { 170.0 * graded }]);
            }
        }
        "illumination" => {
            for lit in horizon_clip(z, w, h, cell, grid_az(), sun_el) {
                push([0.0, 0.0, 180.0, if lit { 0.0 } else { 165.0 }]);
            }
        }
        "psr" => {
            let mut ever = vec![false; n];
            for az in (0..360).step_by(30) {
                for (e, l) in ever
                    .iter_mut()
                    .zip(horizon_clip(z, w, h, cell, f64::from(az), 3.0))
                {
                    *e |= l;
                }
            }
            for e in ever {
                push([90.0, 0.0, 200.0, if e { 0.0 } else { 200.0 }]);
            }
        }
        "incidence" => {
            for inc in incidence_angle_deg(z, w, h, cell, grid_az(), sun_el) {
                let t = (if inc.is_nan() { 90.0 } else { inc } / 90.0).clamp(0.0, 1.0);
                push([255.0, 200.0 * (1.0 - t), 40.0, 40.0 + 170.0 * t]);
            }
        }
        "aspect" => {
            let (gy, gx) = gradient(z, w, h, cell);
            for i in 0..n {
                let aspect = py_mod((-gx[i]).atan2(gy[i]).to_degrees(), 360.0);
                let slope = gx[i].hypot(gy[i]).atan().to_degrees();
                let a = (slope / 5.0).clamp(0.0, 1.0);
                let rgb = hsv_to_rgb(aspect / 360.0, 0.85, 0.95);
                push([
                    rgb[0] * 255.0,
                    rgb[1] * 255.0,
                    rgb[2] * 255.0,
                    35.0 + 185.0 * a,
                ]);
            }
        }
        "curvature" => {
            let (gy, gx) = gradient(z, w, h, cell);
            let (gyy, _) = gradient(&gy, w, h, cell);
            let (_, gxx) = gradient(&gx, w, h, cell);
            let lap: Vec<f64> = gxx.iter().zip(&gyy).map(|(a, b)| a + b).collect();
            let abs: Vec<f64> = lap.iter().map(|v| v.abs()).collect();
            let mut scale = percentile(&abs, 98.0, 1.0);
            if scale <= 0.0 {
                scale = 1e-9;
            }
            for v in lap {
                let t = (v / scale).clamp(-1.0, 1.0);
                let rgb = ramp((t + 1.0) / 2.0, &CURV_DIVERGING);
                push([rgb[0], rgb[1], rgb[2], 45.0 + 180.0 * t.abs()]);
            }
        }
        "roughness" => {
            let (gy, gx) = gradient(z, w, h, cell);
            let slope = slope_of(&gy, &gx);
            let sq: Vec<f64> = slope.iter().map(|s| s * s).collect();
            let (mean, mean_sq) = (
                uniform_filter_nearest(&slope, w, h, 3),
                uniform_filter_nearest(&sq, w, h, 3),
            );
            let r: Vec<f64> = mean
                .iter()
                .zip(&mean_sq)
                .map(|(m, m2)| (m2 - m * m).max(0.0).sqrt() / 10.0)
                .collect();
            let lo = percentile(&r, 2.0, 0.0);
            let mut hi = percentile(&r, 98.0, 1.0);
            if hi <= lo {
                hi = lo + 1e-9;
            }
            for v in r {
                let t = ((if v.is_finite() { v } else { lo } - lo) / (hi - lo)).clamp(0.0, 1.0);
                let rgb = ramp(t, &ROUGH_SEQUENTIAL);
                push([rgb[0], rgb[1], rgb[2], 70.0 + 150.0 * t]);
            }
        }
        _ => return None,
    }
    Some(out)
}

const PHYS_BLUES: [(f64, [f64; 3]); 3] = [
    (0.0, [222.0, 235.0, 247.0]),
    (0.5, [66.0, 146.0, 198.0]),
    (1.0, [8.0, 48.0, 107.0]),
];
const PHYS_BROWNS: [(f64, [f64; 3]); 3] = [
    (0.0, [243.0, 232.0, 210.0]),
    (0.5, [191.0, 138.0, 80.0]),
    (1.0, [94.0, 55.0, 18.0]),
];
const PHYS_GYR: [(f64, [f64; 3]); 3] = [
    (0.0, [33.0, 145.0, 80.0]),
    (0.5, [241.0, 196.0, 15.0]),
    (1.0, [192.0, 40.0, 40.0]),
];
const PHYS_PURPLES: [(f64, [f64; 3]); 3] = [
    (0.0, [239.0, 237.0, 245.0]),
    (0.5, [158.0, 154.0, 200.0]),
    (1.0, [84.0, 39.0, 143.0]),
];
const PHYS_YLORRD: [(f64, [f64; 3]); 3] = [
    (0.0, [255.0, 237.0, 160.0]),
    (0.5, [253.0, 141.0, 60.0]),
    (1.0, [153.0, 0.0, 13.0]),
];
const COST_RAMP: [(f64, [f64; 3]); 3] = PHYS_GYR;

/// Each veto (and cost-only) reason's colour (Python `BLOCKING_COLORS`).
const BLOCKING_COLORS: [(&str, [f64; 3]); 12] = [
    ("slope", [214.0, 40.0, 40.0]),
    ("sinkage", [0.0, 158.0, 158.0]),
    ("tip_risk", [190.0, 30.0, 160.0]),
    ("negative_obstacle", [150.0, 82.0, 24.0]),
    ("psr", [124.0, 74.0, 214.0]),
    ("keepout", [110.0, 110.0, 110.0]),
    ("reservation", [30.0, 128.0, 224.0]),
    ("roughness", [150.0, 150.0, 60.0]),
    ("slip", [150.0, 96.0, 60.0]),
    ("illumination", [60.0, 128.0, 150.0]),
    ("shadow_confidence", [86.0, 86.0, 128.0]),
    ("energy", [176.0, 116.0, 44.0]),
];

/// A field stretched between its 2nd and 98th percentiles onto `stops` (`invert` puts the risky end high), alpha
/// rising toward the high end (Python `_physics_heatmap_rgba`; `_cost_heatmap_rgba` with its own degenerate span).
fn heatmap(f: &[f64], stops: &[(f64, [f64; 3])], invert: bool, degenerate: f64) -> Vec<u8> {
    let lo = percentile(f, 2.0, 0.0);
    let mut hi = percentile(f, 98.0, 1.0);
    if hi <= lo {
        hi = lo + degenerate;
    }
    let mut out = Vec::with_capacity(f.len() * 4);
    for v in f {
        let mut t = ((if v.is_finite() { *v } else { lo } - lo) / (hi - lo)).clamp(0.0, 1.0);
        if invert {
            t = 1.0 - t;
        }
        let rgb = ramp(t, stops);
        out.extend([rgb[0], rgb[1], rgb[2], 110.0 + 120.0 * t].map(u8_of));
    }
    out
}

/// One terramechanics-spine drape (Python `_physics_rgba`): the spine field over the patch's slope map, or `None`
/// for a kind that is not a physics layer.
///
/// # Errors
/// A spine solve the physics refuses.
#[allow(clippy::many_single_char_names)] // the grid's z, w, h, s and a sample a
pub fn physics_rgba(
    z: &[f64],
    w: usize,
    h: usize,
    cell: f64,
    kind: &str,
    s: &Spine,
) -> Result<Option<Vec<u8>>, String> {
    let (stops, invert): (&[(f64, [f64; 3])], bool) = match kind {
        "bearing" => (&PHYS_BLUES, false),
        "sinkage" => (&PHYS_BROWNS, false),
        "slip_risk" => (&PHYS_GYR, false),
        "traction_margin" => (&PHYS_GYR, true),
        "energy_cost" => (&PHYS_YLORRD, false),
        "excavation_resistance" => (&PHYS_PURPLES, false),
        _ => return Ok(None),
    };
    let (gy, gx) = gradient(z, w, h, cell);
    let slope = slope_of(&gy, &gx);
    let field: Vec<f64> = if kind == "excavation_resistance" {
        vec![s.draft_n; z.len()]
    } else {
        let lut = Terra::over(&slope, s)?;
        slope
            .iter()
            .map(|x| {
                let a = lut.at(*x);
                match kind {
                    "bearing" => a.bearing_pa,
                    "sinkage" => a.sinkage_m,
                    "slip_risk" => a.slip,
                    "traction_margin" => a.traction_margin,
                    _ => a.drive_power_w,
                }
            })
            .collect()
    };
    Ok(Some(heatmap(&field, stops, invert, 1e-9)))
}

/// The costmap drapes (Python `_costmap_rgba`): `cost`, the plan-independent traversal cost green to red, or
/// `blocking`, each impassable cell in its first veto reason's colour; `None` for another kind.
///
/// # Errors
/// The costmap's refusal.
#[allow(clippy::too_many_arguments)] // the Python's inputs
pub fn costmap_rgba(
    z: &[f64],
    w: usize,
    h: usize,
    cell: f64,
    kind: &str,
    sun_az: f64,
    sun_el: f64,
    grid_north_bearing: Option<f64>,
    s: &Spine,
) -> Result<Option<Vec<u8>>, String> {
    if kind != "cost" && kind != "blocking" {
        return Ok(None);
    }
    let az = grid_north_bearing.map_or(sun_az, |b| grid_sun_az(sun_az, b));
    let cm = drape_costmap(z, w, h, cell, az, sun_el, 25.0, s)?;
    if kind == "cost" {
        return Ok(Some(heatmap(&cm.cost, &COST_RAMP, false, 1e-6)));
    }
    let mut out = vec![0_u8; z.len() * 4];
    for (i, (pass, reason)) in cm.passable.iter().zip(&cm.reason).enumerate() {
        if *pass {
            continue;
        }
        if let Some(col) = reason.and_then(|r| BLOCKING_COLORS.iter().find(|(n, _)| *n == r)) {
            out[i * 4..i * 4 + 4]
                .copy_from_slice(&[col.1[0], col.1[1], col.1[2], 205.0].map(u8_of));
        }
    }
    Ok(Some(out))
}

/// The rows reversed (numpy `flipud`), for an image whose row 0 is the grid's last row (north up).
#[must_use]
pub fn flipud(rgba: &[u8], w: usize) -> Vec<u8> {
    rgba.chunks(w * 4).rev().flatten().copied().collect()
}

/// An 8-bit RGBA PNG.
///
/// # Errors
/// The encoder's refusal, in words.
pub fn png_rgba(rgba: &[u8], w: usize, h: usize) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    {
        let mut e = png::Encoder::new(
            &mut out,
            u32::try_from(w).map_err(|e| e.to_string())?,
            u32::try_from(h).map_err(|e| e.to_string())?,
        );
        e.set_color(png::ColorType::Rgba);
        e.set_depth(png::BitDepth::Eight);
        let mut wr = e.write_header().map_err(|e| e.to_string())?;
        wr.write_image_data(rgba).map_err(|e| e.to_string())?;
    }
    Ok(out)
}
