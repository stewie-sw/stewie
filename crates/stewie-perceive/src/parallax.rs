//! The measured articulation-parallax fix from a rendered two-posture pair (RW-51c; Python
//! `stewie.godot.articulation_bridge.localize_on_render_pair` with `dart.depth_truth`).
//!
//! High-contrast features (shadow and clast edges) are block-matched vertically from the posture-A frame to the
//! posture-B frame, gated by a truth-free confidence (best over median match error). Each confident shift `dv` gives
//! the range `R = fx * dh / dv`; the feature's pixel, ray-cast onto the scene heightfield, gives its landmark. A
//! RANSAC over the measured ranges, seeded by a drifted prior, trilaterates the rover in the DEM-local frame
//! (x = world x, y = world z). Truth (the camera pose) only associates pixels with landmarks and scores the error.
//! The names are the Python's (`q`, `v`, `o`, `d`, `a`, `b`, ...).
#![allow(clippy::many_single_char_names)]

use stewie_twin::pcg64::Pcg64;

use crate::localize::{
    position_fix_covariance, position_fix_from_ranges, range_sigma_from_pixel_noise,
};

/// A scene heightfield: `z[row * width + col]` is the world height [m] at world `(col * cell, row * cell)`.
#[derive(Debug, Clone)]
pub struct Heightfield {
    pub z: Vec<f64>,
    pub width: usize,
    pub height: usize,
    pub cell_m: f64,
}

/// A grayscale frame, row-major.
#[derive(Debug, Clone)]
pub struct Gray {
    pub px: Vec<f64>,
    pub width: usize,
    pub height: usize,
}

/// A pinhole camera in the world: intrinsics, position and `(x, y, z, w)` orientation (Godot: looks down local -Z,
/// +X right, +Y up).
#[derive(Debug, Clone, Copy)]
pub struct Camera {
    pub fx: f64,
    pub fy: f64,
    pub cx: f64,
    pub cy: f64,
    pub position: [f64; 3],
    pub quat_xyzw: [f64; 4],
}

/// The fix and its evidence.
#[derive(Debug, Clone)]
pub struct RenderPairFix {
    pub fix_xy: [f64; 2],
    pub seed_xy: [f64; 2],
    pub fix_sigma_m: f64,
    pub n_features: usize,
    pub inlier_ranges: Vec<f64>,
    pub inlier_landmarks: Vec<[f64; 2]>,
}

/// Rotate `v` by the quaternion `q = (x, y, z, w)`.
#[must_use]
pub fn quat_rotate(q: [f64; 4], v: [f64; 3]) -> [f64; 3] {
    let [x, y, z, w] = q;
    let [vx, vy, vz] = v;
    let (tx, ty, tz) = (
        2.0 * (y * vz - z * vy),
        2.0 * (z * vx - x * vz),
        2.0 * (x * vy - y * vx),
    );
    [
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    ]
}

/// The world ray (origin, unit direction) through image pixel `(u, v)`; image y is down.
#[must_use]
pub fn camera_ray_world(u: f64, v: f64, cam: &Camera) -> ([f64; 3], [f64; 3]) {
    let d = quat_rotate(
        cam.quat_xyzw,
        [(u - cam.cx) / cam.fx, -(v - cam.cy) / cam.fy, -1.0],
    );
    let n = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
    (
        cam.position,
        if n > 0.0 {
            [d[0] / n, d[1] / n, d[2] / n]
        } else {
            d
        },
    )
}

/// The bilinear terrain height at world `(x, z)`; `None` outside the patch.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)] // c, r >= 0, inside the grid
pub fn height_at(t: &Heightfield, x: f64, z: f64) -> Option<f64> {
    let (c, r) = (x / t.cell_m, z / t.cell_m);
    if c < 0.0 || r < 0.0 || c >= (t.width - 1) as f64 || r >= (t.height - 1) as f64 {
        return None;
    }
    let (c0, r0) = (c as usize, r as usize);
    let (fc, fr) = (c - c0 as f64, r - r0 as f64);
    let at = |r: usize, c: usize| t.z[r * t.width + c];
    Some(
        (1.0 - fr) * ((1.0 - fc) * at(r0, c0) + fc * at(r0, c0 + 1))
            + fr * ((1.0 - fc) * at(r0 + 1, c0) + fc * at(r0 + 1, c0 + 1)),
    )
}

/// March the ray until it crosses the terrain; the range [m] at the crossing, `None` if none within `t_max`.
#[must_use]
pub fn raycast_range(
    o: [f64; 3],
    d: [f64; 3],
    t: &Heightfield,
    t_max: f64,
    step: f64,
) -> Option<f64> {
    let (mut prev_above, mut prev_t) = (None, 0.0);
    let mut s = step;
    while s <= t_max {
        let p = [o[0] + s * d[0], o[1] + s * d[1], o[2] + s * d[2]];
        if let Some(gh) = height_at(t, p[0], p[2]) {
            let above = p[1] > gh;
            if prev_above.is_some_and(|a| a != above) {
                return Some(0.5 * (s + prev_t));
            }
            (prev_above, prev_t) = (Some(above), s);
        }
        s += step;
    }
    None
}

/// The `(2 hw + 1)`-square patch at `(u, v)`, or `None` where it leaves the frame.
fn patch(g: &Gray, u: usize, v: usize, hw: usize) -> Option<Vec<f64>> {
    (u >= hw && v >= hw && u + hw < g.width && v + hw < g.height).then(|| {
        (v - hw..=v + hw)
            .flat_map(|r| {
                g.px[r * g.width + u - hw..=r * g.width + u + hw]
                    .iter()
                    .copied()
            })
            .collect()
    })
}

#[allow(clippy::cast_precision_loss)] // a patch of a few hundred pixels
fn mean(x: &[f64]) -> f64 {
    x.iter().sum::<f64>() / x.len() as f64
}

/// numpy's `std` (population): `sqrt(mean(|x - mean|^2))`.
fn std(x: &[f64]) -> f64 {
    let m = mean(x);
    mean(&x.iter().map(|v| (v - m).powi(2)).collect::<Vec<_>>()).sqrt()
}

/// The vertical parallax shift [px] of the patch at `(u, v)` from frame A to B, and a truth-free confidence (best
/// over median match error; small is a sharp match). `None` with fewer than five candidate shifts.
#[must_use]
pub fn vparallax(
    a: &Gray,
    b: &Gray,
    u: usize,
    v: usize,
    search_px: usize,
    hw: usize,
) -> Option<(usize, f64)> {
    let pa = patch(a, u, v, hw)?;
    let mut errs = Vec::new();
    for s in 1..search_px {
        if v + s + hw + 1 > a.height {
            break;
        }
        let Some(pb) = patch(b, u, v + s, hw) else {
            break;
        };
        errs.push(mean(
            &pa.iter()
                .zip(&pb)
                .map(|(x, y)| (x - y).powi(2))
                .collect::<Vec<_>>(),
        ));
    }
    if errs.len() < 5 {
        return None;
    }
    let (i0, min) = errs
        .iter()
        .copied()
        .enumerate()
        .fold(
            (0, f64::INFINITY),
            |best, (i, e)| if e < best.1 { (i, e) } else { best },
        );
    Some((i0 + 1, min / (median(&errs) + 1e-9)))
}

/// numpy's `median`: the middle value, or the mean of the middle two.
fn median(x: &[f64]) -> f64 {
    let mut sorted = x.to_vec();
    sorted.sort_by(f64::total_cmp);
    let k = sorted.len() / 2;
    if sorted.len() % 2 == 1 {
        sorted[k]
    } else {
        f64::midpoint(sorted[k - 1], sorted[k])
    }
}

/// The fix from the two-posture pair: `dh` is the B-minus-A chassis lift, `true_xy` the posture-A rover position
/// (scoring and the drifted seed only), `drift_m` the seed's offset. The Python's defaults: a 280 px search, a
/// 19-pixel patch, confidence <= 0.5, 200 RANSAC draws from `default_rng(0)`, inliers within 0.15 m.
///
/// # Errors
/// Fewer than three confident features.
#[allow(clippy::cast_precision_loss)] // pixel coordinates and shifts
pub fn localize_on_render_pair(
    a: &Gray,
    b: &Gray,
    terrain: &Heightfield,
    cam: &Camera,
    dh: f64,
    true_xy: [f64; 2],
    drift_m: f64,
) -> Result<RenderPairFix, String> {
    const HW: usize = 9;
    let (w, h) = (a.width, a.height);
    let (mut landmarks, mut ranges) = (Vec::new(), Vec::new());
    for v in (80..h / 2 + 80).step_by(10) {
        for u in (120..w.saturating_sub(120)).step_by(16) {
            let Some(p) = patch(a, u, v, HW) else {
                continue;
            };
            let m = mean(&p);
            if std(&p) < 30.0 || !(30.0 < m && m < 215.0) {
                continue;
            }
            // confident matches only (no truth used)
            let Some((dv, conf)) = vparallax(a, b, u, v, 280, HW) else {
                continue;
            };
            if dv < 8 || conf > 0.5 {
                continue;
            }
            let (o, d) = camera_ray_world(u as f64, v as f64, cam);
            let Some(rt) = raycast_range(o, d, terrain, 12.0, 0.01) else {
                continue;
            };
            landmarks.push([o[0] + rt * d[0], o[2] + rt * d[2]]);
            ranges.push(cam.fx * dh / dv as f64);
        }
    }
    let n = landmarks.len();
    if n < 3 {
        return Err(format!(
            "only {n} confident parallax features (need >= 3); the render geometry may be outside the camera's \
             resolvable range"
        ));
    }
    let s = drift_m / 2.0_f64.sqrt();
    let guess = [true_xy[0] + s, true_xy[1] - s];
    let mut rng = Pcg64::new(0);
    let mut best: Option<Vec<bool>> = None;
    for _ in 0..200 {
        let idx = rng.choice_without_replacement(n, 3);
        let f = position_fix_from_ranges(
            &idx.iter().map(|&i| landmarks[i]).collect::<Vec<_>>(),
            &idx.iter().map(|&i| ranges[i]).collect::<Vec<_>>(),
            guess,
            50,
        );
        let inl: Vec<bool> = landmarks
            .iter()
            .zip(&ranges)
            .map(|(l, r)| ((l[0] - f[0]).hypot(l[1] - f[1]) - r).abs() < 0.15)
            .collect();
        let count = |m: &[bool]| m.iter().filter(|&&x| x).count();
        if best.as_ref().is_none_or(|b| count(&inl) > count(b)) {
            best = Some(inl);
        }
    }
    let best = best.unwrap_or_default();
    let pick = |xs: &[f64]| -> Vec<f64> {
        xs.iter()
            .zip(&best)
            .filter(|p| *p.1)
            .map(|p| *p.0)
            .collect()
    };
    let inlier_ranges = pick(&ranges);
    let inlier_landmarks: Vec<[f64; 2]> = landmarks
        .iter()
        .zip(&best)
        .filter(|p| *p.1)
        .map(|p| *p.0)
        .collect();
    let fix_xy = position_fix_from_ranges(&inlier_landmarks, &inlier_ranges, guess, 50);
    let sig: Vec<f64> = inlier_ranges
        .iter()
        .map(|&r| range_sigma_from_pixel_noise(r, dh, cam.fx, 0.68))
        .collect();
    let cov = position_fix_covariance(&inlier_landmarks, fix_xy, &sig);
    Ok(RenderPairFix {
        fix_xy,
        seed_xy: guess,
        fix_sigma_m: (0.5 * (cov[0][0] + cov[1][1])).sqrt(),
        n_features: n,
        inlier_ranges,
        inlier_landmarks,
    })
}

#[cfg(test)]
mod tests {
    /// The real render pair always yields 279 candidate shifts (odd); the even branch on SYNTHETIC lists (labelled).
    #[test]
    fn median_is_numpys() {
        assert!((super::median(&[4.0, 1.0, 3.0, 2.0]) - 2.5).abs() < 1e-15);
        assert!((super::median(&[3.0, 1.0, 2.0]) - 2.0).abs() < 1e-15);
    }
}
