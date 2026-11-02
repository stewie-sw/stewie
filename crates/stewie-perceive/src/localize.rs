//! Measured relocalization fixes (RW-41a): SN-10 articulation parallax (Python `dart.articulated_parallax`) and the
//! SN-03 shadow-yaw heading factors (Python `dart.shadow_factors`), both fused through the SE(2) pose graph.
//!
//! A commanded chassis lift moves the camera by a known vertical baseline `dh`; a ground landmark at range `R` shifts
//! by exactly `fx * dh / R` image rows, so `R = fx * dh / shift`. Ranges to two or more known landmarks fix the rover
//! position from a standstill without a heading. Fewer than three non-collinear landmarks leave a mirror pair: that
//! fix is reported with both hypotheses and is not fused (H-14, M-02). A shadow's anti-solar ray, seen at a body
//! bearing, fixes the heading, admitted only past a contrast gate and an observability gate.

use std::collections::BTreeMap;

use nalgebra::DMatrix;

use crate::pose_graph_se2::{GraphError, PoseGraphSe2, yaw_from_shadow};

/// Range [m] from a measured shadow-tip pixel shift under the camera lift `dh_m`; unbounded for no shift.
#[must_use]
pub fn range_from_pixel_parallax(dh_m: f64, pixel_shift: f64, fx_px: f64) -> f64 {
    if pixel_shift <= 0.0 {
        return f64::INFINITY;
    }
    fx_px * dh_m / pixel_shift
}

/// Range 1-sigma from shadow-tip localization noise: `R^2 / (fx dh) * sigma_px`.
#[must_use]
pub fn range_sigma_from_pixel_noise(range_m: f64, dh_m: f64, fx_px: f64, sigma_px: f64) -> f64 {
    range_m.powf(2.0) / (fx_px * dh_m).max(1e-9) * sigma_px
}

/// The trilateration position covariance from per-landmark range sigmas (the GDOP form: the inverse of the summed
/// unit-bearing outer products over the range variances).
#[must_use]
pub fn position_fix_covariance(
    landmarks: &[[f64; 2]],
    rover: [f64; 2],
    range_sigmas: &[f64],
) -> [[f64; 2]; 2] {
    let mut info = [[0.0; 2]; 2];
    for (l, s) in landmarks.iter().zip(range_sigmas) {
        let d = [rover[0] - l[0], rover[1] - l[1]];
        let n = d[0].hypot(d[1]);
        if n < 1e-9 {
            continue;
        }
        let u = [d[0] / n, d[1] / n];
        let v = (s * s).max(1e-12);
        for a in 0..2 {
            for b in 0..2 {
                info[a][b] += u[a] * u[b] / v;
            }
        }
    }
    let m = DMatrix::from_row_slice(
        2,
        2,
        &[
            info[0][0] + 1e-12,
            info[0][1],
            info[1][0],
            info[1][1] + 1e-12,
        ],
    );
    let inv = m
        .try_inverse()
        .unwrap_or_else(|| DMatrix::from_element(2, 2, f64::NAN));
    [[inv[(0, 0)], inv[(0, 1)]], [inv[(1, 0)], inv[(1, 1)]]]
}

/// Trilaterate the rover position from ranges to known landmarks (Gauss-Newton from `guess`, at most `iters`).
#[must_use]
#[allow(clippy::many_single_char_names)] // p, h, g, j, d as the Python
pub fn position_fix_from_ranges(
    landmarks: &[[f64; 2]],
    ranges: &[f64],
    guess: [f64; 2],
    iters: usize,
) -> [f64; 2] {
    let mut p = guess;
    for _ in 0..iters {
        let mut h = [[0.0; 2]; 2];
        let mut g = [0.0; 2];
        for (l, r) in landmarks.iter().zip(ranges) {
            let d = [p[0] - l[0], p[1] - l[1]];
            let dist = d[0].hypot(d[1]).max(1e-9);
            let res = dist - r;
            let j = [d[0] / dist, d[1] / dist];
            for a in 0..2 {
                g[a] += j[a] * res;
                for b in 0..2 {
                    h[a][b] += j[a] * j[b];
                }
            }
        }
        let m = DMatrix::from_row_slice(2, 2, &[h[0][0] + 1e-9, h[0][1], h[1][0], h[1][1] + 1e-9]);
        let Some(step) = m.lu().solve(&nalgebra::DVector::from_column_slice(&g)) else {
            break;
        };
        p = [p[0] - step[0], p[1] - step[1]];
        if step.norm() < 1e-10 {
            break;
        }
    }
    p
}

/// H-14: true when the landmarks span (essentially) a line, so their trilateration has a mirror twin; fewer than
/// three always do.
fn collinear(points: &[[f64; 2]]) -> bool {
    if points.len() < 3 {
        return true;
    }
    #[allow(clippy::cast_precision_loss)] // a landmark count
    let n = points.len() as f64;
    let mean = points
        .iter()
        .fold([0.0, 0.0], |m, p| [m[0] + p[0], m[1] + p[1]]);
    let mean = [mean[0] / n, mean[1] / n];
    let c = DMatrix::from_fn(points.len(), 2, |r, k| points[r][k] - mean[k]);
    c.singular_values().min() < 1e-6
}

/// H-14: `p` reflected across the line through landmarks `a` and `b`, the second trilateration root.
#[allow(clippy::many_single_char_names)] // p, h, g, j, d as the Python
fn reflect_across_baseline(p: [f64; 2], a: [f64; 2], b: [f64; 2]) -> [f64; 2] {
    let d = [b[0] - a[0], b[1] - a[1]];
    let dd = d[0] * d[0] + d[1] * d[1];
    if dd < 1e-18 {
        return p;
    }
    let t = ((p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1]) / dd;
    let foot = [a[0] + t * d[0], a[1] + t * d[1]];
    [2.0 * foot[0] - p[0], 2.0 * foot[1] - p[1]]
}

/// An articulation-parallax relocalization (Python `articulation_localize`'s result).
#[derive(Debug, Clone, PartialEq)]
pub struct ParallaxFix {
    pub fix_xy: [f64; 2],
    pub fix_sigma_m: f64,
    pub ambiguous: bool,
    /// Whether the fix entered the graph (only an unambiguous one does).
    pub fused: bool,
    pub hypotheses: Vec<[f64; 2]>,
    pub pose: BTreeMap<i64, [f64; 3]>,
    pub xy_sigma: BTreeMap<i64, f64>,
    pub yaw_sigma: BTreeMap<i64, f64>,
}

/// SN-10 into the estimator: triangulate ranges from the shadow-tip pixel shifts under the lift `dh_m`, fix the
/// rover position near its current estimate, fuse it into `graph` with its full geometry-derived covariance when
/// it is unambiguous (H-30), and return the re-optimized estimate.
///
/// # Errors
/// Fewer than two finite positive ranges (a non-positive pixel shift is not a measurement), or a covariance the
/// graph refuses.
pub fn articulation_localize(
    graph: &mut PoseGraphSe2,
    node: i64,
    landmarks: &[[f64; 2]],
    pixel_shifts: &[f64],
    dh_m: f64,
    fx_px: f64,
    sigma_px: f64,
) -> Result<ParallaxFix, GraphError> {
    let current = graph.optimize();
    let guess = current.get(&node).map_or([0.0, 0.0], |p| [p[0], p[1]]);
    let ranges: Vec<f64> = pixel_shifts
        .iter()
        .map(|s| range_from_pixel_parallax(dh_m, *s, fx_px))
        .collect();
    let keep: Vec<([f64; 2], f64)> = landmarks
        .iter()
        .zip(&ranges)
        .filter(|(_, r)| r.is_finite() && **r > 0.0)
        .map(|(l, r)| (*l, *r))
        .collect();
    if keep.len() < 2 {
        return Err(GraphError(format!(
            "articulation parallax: only {} finite range(s) from {} landmark(s) (non-positive pixel shift or \
             inconsistent geometry); need >= 2 for a heading-free fix",
            keep.len(),
            ranges.len()
        )));
    }
    let kept: Vec<[f64; 2]> = keep.iter().map(|k| k.0).collect();
    let ranges: Vec<f64> = keep.iter().map(|k| k.1).collect();
    let fix = position_fix_from_ranges(&kept, &ranges, guess, 50);
    let ambiguous = collinear(&kept);
    let hypotheses = if ambiguous {
        vec![fix, reflect_across_baseline(fix, kept[0], kept[1])]
    } else {
        vec![fix]
    };
    let sig: Vec<f64> = ranges
        .iter()
        .map(|r| range_sigma_from_pixel_noise(*r, dh_m, fx_px, sigma_px))
        .collect();
    let cov = position_fix_covariance(&kept, fix, &sig);
    let fix_sigma_m = (0.5 * (cov[0][0] + cov[1][1])).sqrt();
    let fused = !ambiguous;
    if fused {
        graph.add_absolute_cov(node, fix, cov, 1e-3)?;
    }
    let out = graph.optimize_with_cov();
    Ok(ParallaxFix {
        fix_xy: fix,
        fix_sigma_m,
        ambiguous,
        fused,
        hypotheses,
        pose: out.pose,
        xy_sigma: out.xy_sigma,
        yaw_sigma: out.yaw_sigma,
    })
}

/// A shadow heading 1-sigma beyond this is too azimuthally fuzzy to observe heading (high sun).
pub const MAX_HEADING_SIGMA_DEG: f64 = 25.0;

/// The observability gate: the least heading information a shadow-yaw factor must carry.
#[must_use]
pub fn min_heading_information() -> f64 {
    1.0 / MAX_HEADING_SIGMA_DEG.to_radians().powf(2.0)
}

/// One shadow-yaw heading measurement (Python's typed `MeasurementFactor`, `SHADOW_YAW`).
#[derive(Debug, Clone, PartialEq)]
pub struct ShadowYaw {
    pub yaw_rad: f64,
    pub variance: f64,
    /// Whether the shadow cleared the contrast gate; a refused one carries its reason.
    pub accepted: bool,
    pub refusal_reason: Option<String>,
    pub bearing_deg: f64,
    pub contrast: f64,
}

/// The shadow-implied headings from each landmark's contrast and the body bearing of its anti-solar ray, given the
/// ephemeris anti-solar azimuth; a landmark below `min_contrast` is an ambiguous match and is refused.
#[must_use]
pub fn shadow_yaw_factors(
    contrasts: &[f64],
    body_bearings_deg: &[f64],
    anti_solar_az_deg: f64,
    sigma_deg: f64,
    min_contrast: f64,
) -> Vec<ShadowYaw> {
    let sig = sigma_deg.to_radians();
    let asol = anti_solar_az_deg.to_radians();
    contrasts
        .iter()
        .zip(body_bearings_deg)
        .map(|(c, b)| {
            let accepted = *c >= min_contrast;
            ShadowYaw {
                yaw_rad: yaw_from_shadow(asol, b.to_radians()),
                variance: sig * sig,
                accepted,
                refusal_reason: (!accepted).then(|| {
                    format!("shadow contrast {c:.1} < gate {min_contrast:.1} (ambiguous match)")
                }),
                bearing_deg: *b,
                contrast: *c,
            }
        })
        .collect()
}

/// Add the factors that clear both gates (accepted, and information at least `min_information`) to `node`, and
/// return how many were added.
///
/// # Errors
/// A sigma the graph refuses (a factor's variance is never non-positive here).
pub fn add_shadow_yaw_factors(
    graph: &mut PoseGraphSe2,
    node: i64,
    factors: &[ShadowYaw],
    min_information: f64,
) -> Result<usize, GraphError> {
    let mut n = 0;
    for f in factors {
        let sigma = f.variance.sqrt();
        if f.accepted && 1.0 / (sigma * sigma) >= min_information {
            graph.add_shadow_yaw(node, f.yaw_rad, sigma)?;
            n += 1;
        }
    }
    Ok(n)
}
