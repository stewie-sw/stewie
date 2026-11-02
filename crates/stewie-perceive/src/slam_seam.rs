//! The SLAM seam (RW-41b; Python `dart.slam_seam`, `dart.localization.register_to_dem`, `dart.integrated_slam`,
//! `dart.ablation`'s scores): a real-terrain est-vs-truth. A rover follows a path across a real DEM; dead reckoning
//! integrates each true step along a gyro heading carrying a constant bias, so the odometry drifts; at DEM keyframes
//! the rover senses the real terrain patch where it truly is and registers it onto the prior DEM near the drifted
//! guess, a measured absolute fix; the SE(2) pose graph fuses odometry, gyro and those fixes, scored against the
//! DEM's own path. Only measured fixes enter the graph: where the Python would substitute a modeled truth-plus-noise
//! fix for a missing one, no fix is added (D-R166).

use std::collections::BTreeMap;
use std::f64::consts::PI;

use nalgebra::Matrix2;
use stewie_twin::numpy::sum;

use crate::pose_graph_se2::PoseGraphSe2;

/// A DEM grid: row-major heights [m], its shape and cell size [m].
#[derive(Debug, Clone, Copy)]
pub struct Grid<'a> {
    pub z: &'a [f64],
    pub rows: usize,
    pub cols: usize,
    pub cell_m: f64,
}

impl Grid<'_> {
    fn at(&self, r: usize, c: usize) -> f64 {
        self.z[r * self.cols + c]
    }
}

/// A registration of an observed patch onto the DEM (Python `register_to_dem`'s result).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Registration {
    pub corrected_rc: (i64, i64),
    pub shift_cells: (i64, i64),
    pub residual_rmse_m: f64,
    /// `1 - best/second` against the best rival outside the minimum's 3x3 neighbourhood, in `[0, 1]`.
    pub confidence: f64,
}

/// numpy's `mean` of the in-bounds window of side `2 half + 1` centred at `(r0, c0)` as a strided view: each row's
/// pairwise sum added in turn.
#[allow(clippy::cast_precision_loss)] // a window count
fn view_mean(g: &Grid<'_>, (r0, c0): (usize, usize), half: usize) -> f64 {
    let side = 2 * half + 1;
    let mut acc = 0.0;
    for r in r0 - half..=r0 + half {
        let start = r * g.cols + c0 - half;
        acc += sum(&g.z[start..start + side]);
    }
    acc / (side * side) as f64
}

/// The `(2 half + 1)^2` patch centred at `rc`, edge-clamped (Python `patch_at`'s default), row-major.
#[must_use]
pub fn patch_clamped(g: &Grid<'_>, rc: (i64, i64), half: i64) -> Vec<f64> {
    let clamp = |v: i64, n: usize| usize::try_from(v.max(0)).unwrap_or(0).min(n - 1);
    (rc.0 - half..=rc.0 + half)
        .flat_map(|r| (rc.1 - half..=rc.1 + half).map(move |c| (r, c)))
        .map(|(r, c)| g.at(clamp(r, g.rows), clamp(c, g.cols)))
        .collect()
}

/// Register `observed` (a square patch of side `2 half + 1`, row-major, with its numpy mean `observed_mean`) onto
/// the DEM near `guess_rc`: the mean-removed mean-square difference over integer shifts within `search` cells,
/// candidates whose full patch leaves the map refused (M-06), equal scores preferring the smaller shift. `None` when
/// no candidate lies inside the map.
#[must_use]
#[allow(clippy::cast_precision_loss)] // a patch size
pub fn register_to_dem(
    g: &Grid<'_>,
    observed: &[f64],
    observed_mean: f64,
    half: i64,
    guess_rc: (i64, i64),
    search: i64,
) -> Option<Registration> {
    let side = usize::try_from(2 * half + 1).ok()?;
    let (rows, cols) = (i64::try_from(g.rows).ok()?, i64::try_from(g.cols).ok()?);
    let uhalf = usize::try_from(half).ok()?;
    let mut ssds: Vec<(f64, i64, i64)> = Vec::new();
    let mut best: Option<(f64, i64, i64)> = None;
    for dr in -search..=search {
        for dc in -search..=search {
            let (r, c) = (guess_rc.0 + dr, guess_rc.1 + dc);
            if r - half < 0 || r + half >= rows || c - half < 0 || c + half >= cols {
                continue;
            }
            let (ur, uc) = (usize::try_from(r).ok()?, usize::try_from(c).ok()?);
            let mean = view_mean(g, (ur, uc), uhalf);
            let mut sq = Vec::with_capacity(side * side);
            for (k, ov) in observed.iter().enumerate() {
                let pv = g.at(ur - uhalf + k / side, uc - uhalf + k % side);
                let res = (pv - mean) - (ov - observed_mean);
                sq.push(res * res);
            }
            let ssd = sum(&sq) / sq.len() as f64;
            ssds.push((ssd, dr, dc));
            #[allow(clippy::float_cmp)] // the Python's exact tie rule
            let better = best.is_none_or(|(b, br, bc)| {
                ssd < b || (ssd == b && dr.abs() + dc.abs() < br.abs() + bc.abs())
            });
            if better {
                best = Some((ssd, dr, dc));
            }
        }
    }
    let (best_ssd, br, bc) = best?;
    let second = ssds
        .iter()
        .filter(|&&(_, dr, dc)| (dr - br).abs().max((dc - bc).abs()) > 1)
        .map(|&(v, ..)| v)
        .fold(None, |m: Option<f64>, v| Some(m.map_or(v, |m| m.min(v))))
        .unwrap_or(0.0);
    let confidence = if second > 1e-12 {
        1.0 - best_ssd / second
    } else {
        0.0
    };
    Some(Registration {
        corrected_rc: (guess_rc.0 + br, guess_rc.1 + bc),
        shift_cells: (br, bc),
        residual_rmse_m: best_ssd.max(0.0).sqrt(),
        confidence: confidence.clamp(0.0, 1.0),
    })
}

/// Python's builtin `round(x, 4)` (correctly rounded through the decimal form).
fn round4(x: f64) -> f64 {
    format!("{x:.4}").parse().unwrap_or(x)
}

/// numpy's `mean` of a 1-D array.
#[allow(clippy::cast_precision_loss)] // a keyframe count
fn mean(v: &[f64]) -> f64 {
    sum(v) / v.len() as f64
}

/// Aligned ATE [m]: the RMS position error after the best 2-D rigid alignment (Umeyama without scale), with the
/// reflection guard (Python `ablation._align_ate`).
#[must_use]
#[allow(clippy::cast_precision_loss, clippy::many_single_char_names)] // a keyframe count; n, h, r, u as the Python
pub fn align_ate(est: &[[f64; 2]], truth: &[[f64; 2]]) -> f64 {
    let n = est.len() as f64;
    let col_mean = |p: &[[f64; 2]], k: usize| p.iter().fold(0.0, |a, q| a + q[k]) / n;
    let (me, mg) = (
        [col_mean(est, 0), col_mean(est, 1)],
        [col_mean(truth, 0), col_mean(truth, 1)],
    );
    let mut h: Matrix2<f64> = Matrix2::zeros();
    for (e, g) in est.iter().zip(truth) {
        for a in 0..2 {
            for b in 0..2 {
                h[(a, b)] += (e[a] - me[a]) * (g[b] - mg[b]);
            }
        }
    }
    let svd = h.svd(true, true);
    let (Some(u), Some(mut vt)) = (svd.u, svd.v_t) else {
        return f64::NAN;
    };
    let mut r: Matrix2<f64> = vt.transpose() * u.transpose();
    if r.determinant() < 0.0 {
        vt.row_mut(1).neg_mut();
        r = vt.transpose() * u.transpose();
    }
    let sq: Vec<f64> = est
        .iter()
        .zip(truth)
        .map(|(e, g)| {
            let d = [e[0] - me[0], e[1] - me[1]];
            let al = [
                d[0] * r[(0, 0)] + d[1] * r[(0, 1)] + mg[0],
                d[0] * r[(1, 0)] + d[1] * r[(1, 1)] + mg[1],
            ];
            (al[0] - g[0]).powi(2) + (al[1] - g[1]).powi(2)
        })
        .collect();
    mean(&sq).sqrt()
}

/// The RMS heading error [deg], wrapped, after removing the best constant frame offset (Python
/// `ablation._heading_rmse_deg`).
#[must_use]
pub fn heading_rmse_deg(est: &[f64], truth: &[f64]) -> f64 {
    let diff: Vec<f64> = truth.iter().zip(est).map(|(g, e)| g - e).collect();
    let off = mean(&diff.iter().map(|d| d.sin()).collect::<Vec<_>>())
        .atan2(mean(&diff.iter().map(|d| d.cos()).collect::<Vec<_>>()));
    let sq: Vec<f64> = truth
        .iter()
        .zip(est)
        .map(|(g, e)| {
            let x = g - (e + off);
            x.sin().atan2(x.cos()).powi(2)
        })
        .collect();
    mean(&sq).sqrt() * (180.0 / PI)
}

fn wrap(a: f64) -> f64 {
    (a + PI).rem_euclid(2.0 * PI) - PI
}

/// One fused (or odometry-only) run (Python `run_integrated_slam`'s result).
#[derive(Debug, Clone, PartialEq)]
pub struct SlamRun {
    pub ate_aligned_m: f64,
    pub abs_max_err_m: f64,
    pub heading_rmse_deg: f64,
    pub est_xy: Vec<[f64; 2]>,
    /// How many measured fixes were fused.
    pub measured: usize,
}

/// Fuse the odometry backbone, the gyro (`imu`) and the measured DEM fixes keyed by keyframe over every node, and
/// score against the truth. The odometry between carries the world-frame step as its measurement, as the Python's.
///
/// # Errors
/// A fix sigma the graph refuses.
pub fn integrated_slam(
    truth_xy: &[[f64; 2]],
    dr_xy: &[[f64; 2]],
    truth_yaw: &[f64],
    gyro_yaw: &[f64],
    imu: bool,
    dem_fixes: &BTreeMap<usize, ([f64; 2], f64)>,
    fix_interval: usize,
) -> Result<SlamRun, crate::pose_graph_se2::GraphError> {
    let n = truth_xy.len();
    let node = |k: usize| i64::try_from(k).unwrap_or(i64::MAX);
    let mut g = PoseGraphSe2::default();
    g.add_prior(0, [truth_xy[0][0], truth_xy[0][1], truth_yaw[0]], 0.1, 0.1)?;
    for k in 1..n {
        let d = [dr_xy[k][0] - dr_xy[k - 1][0], dr_xy[k][1] - dr_xy[k - 1][1]];
        let dyaw = wrap(gyro_yaw[k] - gyro_yaw[k - 1]);
        g.add_between(node(k - 1), node(k), [d[0], d[1], dyaw], 0.5, 0.5)?;
        if imu {
            g.add_imu_yaw(node(k - 1), node(k), dyaw, 0.05)?;
        }
    }
    let mut measured = 0;
    for k in (2 * fix_interval..n).step_by(2 * fix_interval) {
        if let Some((xy, sigma)) = dem_fixes.get(&k) {
            g.add_absolute(node(k), *xy, *sigma)?;
            measured += 1;
        }
    }
    let est = g.optimize();
    let e: Vec<[f64; 2]> = (0..n)
        .map(|k| [est[&node(k)][0], est[&node(k)][1]])
        .collect();
    let y: Vec<f64> = (0..n).map(|k| est[&node(k)][2]).collect();
    let abs_max = e
        .iter()
        .zip(truth_xy)
        .map(|(p, t)| ((p[0] - t[0]).powi(2) + (p[1] - t[1]).powi(2)).sqrt())
        .fold(f64::NEG_INFINITY, f64::max);
    Ok(SlamRun {
        ate_aligned_m: round4(align_ate(&e, truth_xy)),
        abs_max_err_m: round4(abs_max),
        heading_rmse_deg: round4(heading_rmse_deg(&y, truth_yaw)),
        est_xy: e,
        measured,
    })
}

/// The real-terrain est-vs-truth (Python `dem_fixed_traverse` with `ref_rc` (0, 0)).
#[derive(Debug, Clone, PartialEq)]
pub struct Traverse {
    pub fused: SlamRun,
    pub odom: SlamRun,
    pub n_dem_fix: usize,
    pub true_xy: Vec<[f64; 2]>,
    pub fix_keyframes: Vec<usize>,
}

/// Drive `path_rc` across the DEM, dead-reckon under a constant per-step gyro bias, register the true terrain patch
/// near the drifted guess every `2 fix_interval` keyframes (a fix only above confidence 0.05, its sigma
/// `base_sigma_m / confidence`), and fuse; also run odometry and gyro alone.
///
/// # Errors
/// A fix the graph refuses.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::many_single_char_names
)] // indices
pub fn dem_fixed_traverse(
    g: &Grid<'_>,
    path_rc: &[(i64, i64)],
    patch_half: i64,
    gyro_bias_rad: f64,
    fix_interval: usize,
    base_sigma_m: f64,
) -> Result<Traverse, crate::pose_graph_se2::GraphError> {
    let cell = g.cell_m;
    let n = path_rc.len();
    let true_xy: Vec<[f64; 2]> = path_rc
        .iter()
        .map(|&(r, c)| [c as f64 * cell, r as f64 * cell])
        .collect();
    let d: Vec<[f64; 2]> = true_xy
        .windows(2)
        .map(|w| [w[1][0] - w[0][0], w[1][1] - w[0][1]])
        .collect();
    let mut truth_yaw = vec![0.0; n];
    if n > 1 {
        for k in 1..n {
            truth_yaw[k] = d[k - 1][1].atan2(d[k - 1][0]);
        }
        truth_yaw[0] = truth_yaw[1];
    }
    let gyro_yaw: Vec<f64> = truth_yaw
        .iter()
        .enumerate()
        .map(|(k, t)| t + gyro_bias_rad * k as f64)
        .collect();
    let mut dr_xy = vec![[0.0; 2]; n];
    dr_xy[0] = true_xy[0];
    for k in 1..n {
        let step = (d[k - 1][0] * d[k - 1][0] + d[k - 1][1] * d[k - 1][1]).sqrt();
        dr_xy[k] = [
            dr_xy[k - 1][0] + step * gyro_yaw[k].cos(),
            dr_xy[k - 1][1] + step * gyro_yaw[k].sin(),
        ];
    }
    let mut fixes = BTreeMap::new();
    for k in (2 * fix_interval..n).step_by(2 * fix_interval) {
        let guess = (
            (dr_xy[k][1] / cell).round_ties_even() as i64,
            (dr_xy[k][0] / cell).round_ties_even() as i64,
        );
        let observed = patch_clamped(g, path_rc[k], patch_half);
        // the clamped patch is a contiguous copy: numpy sums it whole, pairwise
        let observed_mean = sum(&observed) / observed.len() as f64;
        let Some(reg) = register_to_dem(g, &observed, observed_mean, patch_half, guess, 5) else {
            continue;
        };
        if reg.confidence < 0.05 {
            continue;
        }
        let (r, c) = reg.corrected_rc;
        fixes.insert(
            k,
            (
                [c as f64 * cell, r as f64 * cell],
                base_sigma_m / reg.confidence.max(0.05),
            ),
        );
    }
    let fused = integrated_slam(
        &true_xy,
        &dr_xy,
        &truth_yaw,
        &gyro_yaw,
        true,
        &fixes,
        fix_interval,
    )?;
    let odom = integrated_slam(
        &true_xy,
        &dr_xy,
        &truth_yaw,
        &gyro_yaw,
        true,
        &BTreeMap::new(),
        fix_interval,
    )?;
    Ok(Traverse {
        fused,
        odom,
        n_dem_fix: fixes.len(),
        true_xy,
        fix_keyframes: fixes.keys().copied().collect(),
    })
}

/// The reproducible real-terrain demo (Python `haworth_demo_traverse`): start at the strongest row gradient inside
/// a margin that keeps the 16-step diagonal path on the map, drive it, and score. Returns the start cell too.
///
/// # Errors
/// A fix the graph refuses.
#[allow(clippy::cast_possible_wrap)] // grid indices
pub fn demo_traverse(
    g: &Grid<'_>,
) -> Result<(Traverse, (i64, i64)), crate::pose_graph_se2::GraphError> {
    const N: usize = 16;
    const MARGIN: usize = 20;
    let (rows, cols) = (g.rows, g.cols);
    // |np.gradient(Z)[0]| over rows MARGIN..rows-MARGIN-2N, cols MARGIN..cols-MARGIN-N: interior central differences
    let mut best = (f64::NEG_INFINITY, 0, 0);
    for r in MARGIN..rows - MARGIN - 2 * N {
        for c in MARGIN..cols - MARGIN - N {
            let v = ((g.at(r + 1, c) - g.at(r - 1, c)) / 2.0).abs();
            if v > best.0 {
                best = (v, r, c);
            }
        }
    }
    let (r0, c0) = (best.1 as i64, best.2 as i64);
    let path: Vec<(i64, i64)> = (0..N as i64).map(|k| (r0 + 2 * k, c0 + k)).collect();
    Ok((dem_fixed_traverse(g, &path, 6, 0.01, 2, 2.0)?, (r0, c0)))
}
