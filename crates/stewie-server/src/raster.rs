//! The analysis-layer rasters (RW-55b6c-1; Python `gis_layers._layer_rgba` and its helpers): each layer's colouring
//! as a function of a DEM patch and its cell size, row-major RGBA. Relief is a Lambertian hillshade; slope,
//! hazard, aspect and curvature come from numpy's `gradient`; illumination, PSR and incidence from the real local
//! horizon; roughness is the costmap's window-RMS slope. Floats are cast to bytes by truncation, as numpy's
//! `astype("uint8")`.

use lunar_dem::uniform_filter_nearest;
use stewie_traverse::layers::{horizon_clip, incidence_angle_deg};

use crate::point::{grid_sun_az, np_interp, py_mod};

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
        "slope" => {
            let (gy, gx) = gradient(z, w, h, cell);
            for s in slope_of(&gy, &gx) {
                let t = (s / 30.0).clamp(0.0, 1.0);
                push([60.0 + 195.0 * t, 200.0 * (1.0 - t), 40.0, 90.0 + 120.0 * t]);
            }
        }
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
