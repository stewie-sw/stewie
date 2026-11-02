//! The SE(2) pose graph (Python `dart.pose_graph_se2`): `(x, y, yaw)` per node by a robust, damped
//! (Levenberg-Marquardt) Gauss-Newton on the SE(2) manifold with numerical Jacobians, a Huber kernel on the data
//! factors (iteratively reweighted), and convergence and conditioning diagnostics. Factor kinds:
//!
//! - `prior(i, pose, sigma_xy, sigma_yaw)`: anchors a full pose (the gauge; never down-weighted);
//! - `between(i, j, (dx, dy, dyaw))`: a relative SE(2) motion in `i`'s body frame (wheel or visual odometry);
//! - `vo_between(i, j, ...)`: a stereo-VO between whose forward component carries the shared latent VO scale;
//! - `imu_yaw(i, j, dyaw)`: a gyro-preintegrated heading change;
//! - `shadow_yaw(i, yaw)`: SN-03, a weak absolute heading from an accepted shadow;
//! - `absolute(i, (x, y))` and `absolute_cov(i, (x, y), cov)`: a map-relative position fix, isotropic or with its
//!   full 2x2 covariance (H-30).
//!
//! Planar by design: pitch and roll are terrain-conformance outputs, not estimator state. Factor order is behaviour
//! (the residual stacking, the Huber blocks, the chained initial guess), so factors are kept as the Python keeps them.

use std::collections::BTreeMap;
use std::f64::consts::{PI, TAU};

use nalgebra::{DMatrix, DVector};

/// An input the graph refuses (Python `ValueError`), with the Python's message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GraphError(pub String);

impl std::fmt::Display for GraphError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for GraphError {}

/// Wrap an angle to `[-pi, pi)`, as the Python's floored `(a + pi) % 2pi - pi`.
#[must_use]
pub fn wrap(a: f64) -> f64 {
    (a + PI).rem_euclid(TAU) - PI
}

/// SN-03: the rover heading an accepted shadow implies, from the anti-solar shadow's world azimuth and its bearing
/// in the body frame.
#[must_use]
pub fn yaw_from_shadow(shadow_world_az: f64, observed_body_bearing: f64) -> f64 {
    wrap(shadow_world_az - observed_body_bearing)
}

/// The SE(2) relative pose `T_i^-1 T_j` as `(dx, dy, dyaw)` in `i`'s body frame.
fn relative(pi: [f64; 3], pj: [f64; 3]) -> [f64; 3] {
    let (c, s) = (pi[2].cos(), pi[2].sin());
    let (dxw, dyw) = (pj[0] - pi[0], pj[1] - pi[1]);
    [c * dxw + s * dyw, -s * dxw + c * dyw, wrap(pj[2] - pi[2])]
}

/// Python `repr` of a float, `nan` and `inf` included.
fn py_repr(x: f64) -> String {
    if x.is_nan() {
        "nan".to_owned()
    } else if x.is_infinite() {
        if x > 0.0 { "inf" } else { "-inf" }.to_owned()
    } else {
        stewie_twin::pyjson::float_repr(x).unwrap_or_else(|_| x.to_string())
    }
}

/// Python `format(x, ".3e")`: a signed exponent of at least two digits.
fn py_sci3(x: f64) -> String {
    let s = format!("{x:.3e}");
    let (mant, exp) = s.split_once('e').unwrap_or((&s, "0"));
    let (sign, digits) = exp.strip_prefix('-').map_or(("+", exp), |d| ("-", d));
    format!("{mant}e{sign}{digits:0>2}")
}

/// Information weight `1/sigma^2` (M-04: a sigma must be finite and strictly positive).
fn weight(sigma: f64) -> Result<f64, GraphError> {
    if !sigma.is_finite() || sigma <= 0.0 {
        return Err(GraphError(format!(
            "sigma must be finite and > 0 (got {}); a non-positive/non-finite sigma is not a valid measurement \
             uncertainty",
            py_repr(sigma)
        )));
    }
    Ok(1.0 / (sigma * sigma))
}

/// A relative factor: the two nodes, the measurement and the per-axis information weights.
type Relative = (i64, i64, [f64; 3], [f64; 3]);

/// The solve's convergence and conditioning diagnostics (Python `solve_status`).
#[derive(Debug, Clone, PartialEq)]
pub struct Status {
    pub converged: bool,
    pub iterations: usize,
    /// Largest over smallest eigenvalue of the un-damped information matrix; infinite when it is singular.
    pub condition_number: f64,
    pub well_conditioned: bool,
    pub final_gradient_norm: f64,
    pub final_cost: f64,
}

/// One solve: the node ids in order, their poses, the damped information matrix, the diagnostics and the VO scale.
#[derive(Debug, Clone)]
pub struct Solution {
    pub order: Vec<i64>,
    pub poses: Vec<[f64; 3]>,
    pub information: DMatrix<f64>,
    pub status: Status,
    pub vo_scale: f64,
}

impl Solution {
    /// The poses by node id.
    #[must_use]
    pub fn pose_map(&self) -> BTreeMap<i64, [f64; 3]> {
        self.order
            .iter()
            .copied()
            .zip(self.poses.iter().copied())
            .collect()
    }
}

/// The estimate with per-node 1-sigma (Python `optimize_with_cov`): an unobservable component is infinite (H-15).
#[derive(Debug, Clone, PartialEq)]
pub struct WithCov {
    pub pose: BTreeMap<i64, [f64; 3]>,
    pub xy_sigma: BTreeMap<i64, f64>,
    pub yaw_sigma: BTreeMap<i64, f64>,
    pub observable: bool,
}

/// The estimate with the latent VO scale (Python `optimize_with_scale`).
#[derive(Debug, Clone, PartialEq)]
pub struct WithScale {
    pub pose: BTreeMap<i64, [f64; 3]>,
    pub vo_scale: f64,
    /// `None` when the scale is not estimated.
    pub vo_scale_sigma: Option<f64>,
    pub scale_observable: bool,
    pub observable: bool,
    pub status: Status,
}

/// A sparse SE(2) pose graph: add factors, then solve.
#[derive(Debug, Clone)]
pub struct PoseGraphSe2 {
    robust: bool,
    huber_delta: f64,
    estimate_vo_scale: bool,
    priors: Vec<(i64, [f64; 3], [f64; 3])>,
    between: Vec<Relative>,
    vo_between: Vec<Relative>,
    imu: Vec<(i64, i64, f64, f64)>,
    shadow_yaw: Vec<(i64, f64, f64)>,
    abs: Vec<(i64, [f64; 2], f64)>,
    abs_cov: Vec<(i64, [f64; 2], [[f64; 2]; 2])>,
    vo_scale_prior: Option<(f64, f64)>,
    ids: std::collections::BTreeSet<i64>,
}

impl Default for PoseGraphSe2 {
    fn default() -> Self {
        Self::new(true, 1.345, false)
    }
}

const EPS: f64 = 1e-6;
const GRAD_TOL: f64 = 1e-4;

impl PoseGraphSe2 {
    /// A graph with the Huber kernel (`robust`, threshold `huber_delta` on the whitened residual norm; 1.345 is the
    /// 95 %-efficiency constant) and, with `estimate_vo_scale`, the shared latent VO forward-scale state.
    #[must_use]
    pub fn new(robust: bool, huber_delta: f64, estimate_vo_scale: bool) -> Self {
        Self {
            robust,
            huber_delta,
            estimate_vo_scale,
            priors: Vec::new(),
            between: Vec::new(),
            vo_between: Vec::new(),
            imu: Vec::new(),
            shadow_yaw: Vec::new(),
            abs: Vec::new(),
            abs_cov: Vec::new(),
            vo_scale_prior: None,
            ids: std::collections::BTreeSet::new(),
        }
    }

    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn add_prior(
        &mut self,
        i: i64,
        pose: [f64; 3],
        sigma_xy: f64,
        sigma_yaw: f64,
    ) -> Result<(), GraphError> {
        let (wxy, wyaw) = (weight(sigma_xy)?, weight(sigma_yaw)?);
        self.priors.push((i, pose, [wxy, wxy, wyaw]));
        self.ids.insert(i);
        Ok(())
    }

    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn add_between(
        &mut self,
        i: i64,
        j: i64,
        meas: [f64; 3],
        sigma_xy: f64,
        sigma_yaw: f64,
    ) -> Result<(), GraphError> {
        let (wxy, wyaw) = (weight(sigma_xy)?, weight(sigma_yaw)?);
        self.between.push((i, j, meas, [wxy, wxy, wyaw]));
        self.ids.extend([i, j]);
        Ok(())
    }

    /// A stereo-VO between whose forward component is scaled by the latent VO scale (exactly a between when the
    /// scale is not estimated).
    ///
    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn add_vo_between(
        &mut self,
        i: i64,
        j: i64,
        meas: [f64; 3],
        sigma_xy: f64,
        sigma_yaw: f64,
    ) -> Result<(), GraphError> {
        let (wxy, wyaw) = (weight(sigma_xy)?, weight(sigma_yaw)?);
        self.vo_between.push((i, j, meas, [wxy, wxy, wyaw]));
        self.ids.extend([i, j]);
        Ok(())
    }

    /// The Gaussian prior `N(mean, sigma^2)` on the VO scale.
    ///
    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn set_vo_scale_prior(&mut self, mean: f64, sigma: f64) -> Result<(), GraphError> {
        self.vo_scale_prior = Some((mean, weight(sigma)?));
        Ok(())
    }

    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn add_imu_yaw(&mut self, i: i64, j: i64, dyaw: f64, sigma: f64) -> Result<(), GraphError> {
        self.imu.push((i, j, dyaw, weight(sigma)?));
        self.ids.extend([i, j]);
        Ok(())
    }

    /// SN-03: an accepted shadow as a weak absolute-yaw factor (its sigma from the shadow's sharpness).
    ///
    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn add_shadow_yaw(
        &mut self,
        i: i64,
        measured_yaw: f64,
        sigma: f64,
    ) -> Result<(), GraphError> {
        self.shadow_yaw.push((i, measured_yaw, weight(sigma)?));
        self.ids.insert(i);
        Ok(())
    }

    /// # Errors
    /// A sigma that is not finite and positive.
    pub fn add_absolute(&mut self, i: i64, xy: [f64; 2], sigma: f64) -> Result<(), GraphError> {
        self.abs.push((i, xy, weight(sigma)?));
        self.ids.insert(i);
        Ok(())
    }

    /// H-30: an anisotropic absolute fix keeping its full 2x2 covariance, stored as the upper sqrt-information
    /// factor `S` (`S^T S` the information); `sigma_floor_m` is added to each variance.
    ///
    /// # Errors
    /// A covariance with a non-finite entry, not symmetric, or not positive-definite (M-04).
    pub fn add_absolute_cov(
        &mut self,
        i: i64,
        xy: [f64; 2],
        cov: [[f64; 2]; 2],
        sigma_floor_m: f64,
    ) -> Result<(), GraphError> {
        if cov.iter().flatten().any(|v| !v.is_finite()) {
            return Err(GraphError(
                "absolute-fix covariance must be finite (no NaN/Inf entries)".to_owned(),
            ));
        }
        let off = 0.5 * (cov[0][1] + cov[1][0]);
        let sym = [[cov[0][0], off], [off, cov[1][1]]];
        let asym = (cov[0][1] - off).abs().max((cov[1][0] - off).abs());
        let scale = cov.iter().flatten().fold(0.0_f64, |m, v| m.max(v.abs()));
        if asym > 1e-9 * (1.0 + scale) {
            return Err(GraphError(
                "absolute-fix covariance must be symmetric".to_owned(),
            ));
        }
        let (a, b, c) = (sym[0][0], sym[0][1], sym[1][1]);
        let min_eig = 0.5 * (a + c) - (0.25 * (a - c) * (a - c) + b * b).sqrt();
        if min_eig <= 0.0 {
            return Err(GraphError(format!(
                "absolute-fix covariance must be positive-definite (min eigenvalue {} <= 0)",
                py_sci3(min_eig)
            )));
        }
        let floor = sigma_floor_m * sigma_floor_m;
        let (a, c) = (a + floor, c + floor);
        let det = a * c - b * b;
        let (ia, ib, ic) = (c / det, -b / det, a / det);
        // the upper Cholesky factor of the information: S = L^T with L L^T = info
        let l00 = ia.sqrt();
        let l10 = ib / l00;
        let l11 = (ic - l10 * l10).sqrt();
        self.abs_cov.push((i, xy, [[l00, l10], [0.0, l11]]));
        self.ids.insert(i);
        Ok(())
    }

    /// The information-weighted residuals and each one's robust block (`-1` never down-weighted: the prior and the
    /// VO-scale prior); the scalars of one data factor share a block so Huber acts on its whitened norm.
    #[allow(clippy::many_single_char_names)] // x, r, b, p, w as the Python
    fn residuals(
        &self,
        x: &[[f64; 3]],
        idx: &BTreeMap<i64, usize>,
        scale: f64,
    ) -> (Vec<f64>, Vec<i64>) {
        let mut r = Vec::new();
        let mut block = Vec::new();
        let mut b = 0_i64;
        let p = |i: &i64| x[idx[i]];
        for (i, p0, w) in &self.priors {
            let xi = p(i);
            let d = [xi[0] - p0[0], xi[1] - p0[1], wrap(xi[2] - p0[2])];
            for k in 0..3 {
                r.push(w[k].sqrt() * d[k]);
                block.push(-1);
            }
        }
        let mut relative_factor =
            |r: &mut Vec<f64>, block: &mut Vec<i64>, (i, j, meas, w): &Relative, fwd: f64| {
                let rel = relative(p(i), p(j));
                let e = [rel[0] - fwd, rel[1] - meas[1], wrap(rel[2] - meas[2])];
                for k in 0..3 {
                    r.push(w[k].sqrt() * e[k]);
                    block.push(b);
                }
                b += 1;
            };
        for f in &self.between {
            relative_factor(&mut r, &mut block, f, f.2[0]);
        }
        for f in &self.vo_between {
            relative_factor(&mut r, &mut block, f, scale * f.2[0]);
        }
        if self.estimate_vo_scale
            && !self.vo_between.is_empty()
            && let Some((mean, w)) = self.vo_scale_prior
        {
            r.push(w.sqrt() * (scale - mean));
            block.push(-1);
        }
        for (i, j, dyaw, w) in &self.imu {
            r.push(w.sqrt() * wrap((p(j)[2] - p(i)[2]) - dyaw));
            block.push(b);
            b += 1;
        }
        for (i, myaw, w) in &self.shadow_yaw {
            r.push(w.sqrt() * wrap(p(i)[2] - myaw));
            block.push(b);
            b += 1;
        }
        for (i, xy, w) in &self.abs {
            let xi = p(i);
            for k in 0..2 {
                r.push(w.sqrt() * (xi[k] - xy[k]));
                block.push(b);
            }
            b += 1;
        }
        for (i, xy, s) in &self.abs_cov {
            let xi = p(i);
            let d = [xi[0] - xy[0], xi[1] - xy[1]];
            for row in s {
                r.push(row[0] * d[0] + row[1] * d[1]);
                block.push(b);
            }
            b += 1;
        }
        (r, block)
    }

    /// Each block's whitened norm, ascending by block id (Python `np.unique`).
    fn block_norms(r: &[f64], block: &[i64]) -> BTreeMap<i64, f64> {
        let mut sq: BTreeMap<i64, f64> = BTreeMap::new();
        for (v, b) in r.iter().zip(block) {
            *sq.entry(*b).or_default() += v * v;
        }
        sq.into_iter().map(|(b, s)| (b, s.sqrt())).collect()
    }

    /// The per-residual square-root IRLS weight: Huber's `delta/|s|` on each robust block's norm beyond `delta`.
    fn robust_weights(&self, r: &[f64], block: &[i64]) -> Vec<f64> {
        let mut w = vec![1.0; r.len()];
        if !self.robust {
            return w;
        }
        let norms = Self::block_norms(r, block);
        for (k, b) in block.iter().enumerate() {
            let norm = norms[b];
            if *b >= 0 && norm > self.huber_delta {
                w[k] = (self.huber_delta / norm).sqrt();
            }
        }
        w
    }

    fn robust_cost(&self, r: &[f64], block: &[i64]) -> f64 {
        if !self.robust {
            return 0.5 * r.iter().map(|v| v * v).sum::<f64>();
        }
        let d = self.huber_delta;
        Self::block_norms(r, block)
            .into_iter()
            .map(|(b, n)| {
                if b < 0 || n <= d {
                    0.5 * n * n
                } else {
                    d * (n - 0.5 * d)
                }
            })
            .sum()
    }

    /// The forward-difference Jacobian's nonzeros per residual row: `(column, value)`. A residual that does not
    /// involve the perturbed state recomputes bit for bit, so its entry is exactly zero and is left out.
    fn jacobian(
        &self,
        x: &[[f64; 3]],
        idx: &BTreeMap<i64, usize>,
        scale: f64,
        r0: &[f64],
        npar: usize,
    ) -> Vec<Vec<(usize, f64)>> {
        let mut rows: Vec<Vec<(usize, f64)>> = vec![Vec::new(); r0.len()];
        let mut xp = x.to_vec();
        for v in 0..npar {
            let r = if v < 3 * x.len() {
                let (node, comp) = (v / 3, v % 3);
                xp[node][comp] += EPS;
                let r = self.residuals(&xp, idx, scale).0;
                xp[node][comp] = x[node][comp];
                r
            } else {
                self.residuals(x, idx, scale + EPS).0
            };
            for (k, (a, b)) in r.iter().zip(r0).enumerate() {
                let d = (a - b) / EPS;
                if d != 0.0 {
                    rows[k].push((v, d));
                }
            }
        }
        rows
    }

    /// The weighted normal equations `J^T J` and `J^T r` (IRLS square-root weights applied to each row).
    fn normal(
        rows: &[Vec<(usize, f64)>],
        r0: &[f64],
        sw: &[f64],
        npar: usize,
    ) -> (DMatrix<f64>, DVector<f64>) {
        let mut jtj = DMatrix::zeros(npar, npar);
        let mut g = DVector::zeros(npar);
        for ((row, r), w) in rows.iter().zip(r0).zip(sw) {
            for &(a, va) in row {
                let wa = va * w;
                g[a] += wa * (r * w);
                for &(b, vb) in row {
                    jtj[(a, b)] += wa * (vb * w);
                }
            }
        }
        (jtj, g)
    }

    /// The robust Levenberg-Marquardt solve, at most `iters` iterations (Python `_solve`).
    #[allow(clippy::too_many_lines, clippy::many_single_char_names)] // the Python's _solve, step by step
    #[must_use]
    pub fn solve(&self, iters: usize) -> Solution {
        let order: Vec<i64> = self.ids.iter().copied().collect();
        let idx: BTreeMap<i64, usize> = order.iter().enumerate().map(|(k, n)| (*n, k)).collect();
        let n = order.len();
        let ns = usize::from(self.estimate_vo_scale && !self.vo_between.is_empty());
        let npar = 3 * n + ns;
        let mut scale = match self.vo_scale_prior {
            Some((mean, _)) if ns == 1 => mean,
            _ => 1.0,
        };
        if n == 0 {
            return Solution {
                order,
                poses: Vec::new(),
                information: DMatrix::zeros(npar, npar),
                status: Status {
                    converged: true,
                    iterations: 0,
                    condition_number: 1.0,
                    well_conditioned: true,
                    final_gradient_norm: 0.0,
                    final_cost: 0.0,
                },
                vo_scale: scale,
            };
        }
        // start from the priors and the chained betweens (then the VO betweens), as the Python does
        let mut x = vec![[0.0; 3]; n];
        for (i, p0, _) in &self.priors {
            x[idx[i]] = *p0;
        }
        for (i, j, meas, _) in self.between.iter().chain(&self.vo_between) {
            let a = x[idx[i]];
            let (c, s) = (a[2].cos(), a[2].sin());
            x[idx[j]] = [
                a[0] + c * meas[0] - s * meas[1],
                a[1] + s * meas[0] + c * meas[1],
                wrap(a[2] + meas[2]),
            ];
        }
        let mut lam = 1e-3;
        let mut converged = false;
        let mut it = 0;
        let mut grad_norm = f64::INFINITY;
        let (r, block) = self.residuals(&x, &idx, scale);
        let mut cost = self.robust_cost(&r, &block);
        for k in 1..=iters {
            it = k;
            let (r0, block) = self.residuals(&x, &idx, scale);
            let rows = self.jacobian(&x, &idx, scale, &r0, npar);
            let sw = self.robust_weights(&r0, &block);
            let (jtj, g) = Self::normal(&rows, &r0, &sw, npar);
            grad_norm = g.norm();
            let mut accepted = None;
            for _ in 0..12 {
                let h = &jtj + DMatrix::identity(npar, npar) * (lam + 1e-12);
                let Some(dx) = h.lu().solve(&(-&g)) else {
                    lam *= 10.0;
                    continue;
                };
                let xn: Vec<[f64; 3]> = x
                    .iter()
                    .enumerate()
                    .map(|(q, p)| {
                        [
                            p[0] + dx[3 * q],
                            p[1] + dx[3 * q + 1],
                            wrap(p[2] + dx[3 * q + 2]),
                        ]
                    })
                    .collect();
                let scale_n = if ns == 1 { scale + dx[3 * n] } else { scale };
                let (rn, bn) = self.residuals(&xn, &idx, scale_n);
                let new_cost = self.robust_cost(&rn, &bn);
                if new_cost < cost {
                    x = xn;
                    scale = scale_n;
                    cost = new_cost;
                    lam = (lam * 0.5).max(1e-9);
                    accepted = Some(dx.norm());
                    break;
                }
                lam *= 10.0;
            }
            let Some(step) = accepted else {
                // no step lowers the cost: at a minimum, or stuck
                converged = grad_norm < GRAD_TOL;
                break;
            };
            if grad_norm < GRAD_TOL || step < 1e-9 {
                converged = true;
                break;
            }
        }
        // the final weighted information (un-damped) for the covariance and the conditioning
        let (r0, block) = self.residuals(&x, &idx, scale);
        let rows = self.jacobian(&x, &idx, scale, &r0, npar);
        let sw = self.robust_weights(&r0, &block);
        let (info, _) = Self::normal(&rows, &r0, &sw, npar);
        let sym = (&info + info.transpose()) * 0.5;
        let evals = sym.symmetric_eigenvalues();
        let (lo, hi) = (evals.min(), evals.max());
        let cond = if lo <= 1e-12 || !lo.is_finite() {
            f64::INFINITY
        } else {
            hi / lo
        };
        Solution {
            order,
            poses: x,
            information: info + DMatrix::identity(npar, npar) * 1e-9,
            status: Status {
                converged,
                iterations: it,
                condition_number: cond,
                well_conditioned: cond.is_finite() && cond < 1e6,
                final_gradient_norm: grad_norm,
                final_cost: cost,
            },
            vo_scale: scale,
        }
    }

    /// The diagnostics of a 50-iteration solve.
    #[must_use]
    pub fn solve_status(&self) -> Status {
        self.solve(50).status
    }

    /// The poses of a 50-iteration solve.
    #[must_use]
    pub fn optimize(&self) -> BTreeMap<i64, [f64; 3]> {
        self.solve(50).pose_map()
    }

    /// The poses with each node's 1-sigma from the inverse information: translation is observable only with a
    /// prior or an absolute fix, heading only with a prior or a shadow yaw; an unanchored component's sigma is
    /// infinite rather than the damping ridge's finite, non-physical number (H-15).
    #[must_use]
    pub fn optimize_with_cov(&self) -> WithCov {
        let sol = self.solve(50);
        let translation =
            !(self.priors.is_empty() && self.abs.is_empty() && self.abs_cov.is_empty());
        let yaw = !(self.priors.is_empty() && self.shadow_yaw.is_empty());
        let (mut xy_sigma, mut yaw_sigma) = (BTreeMap::new(), BTreeMap::new());
        if !sol.order.is_empty() {
            let cov = sol.information.clone().try_inverse().unwrap_or_else(|| {
                DMatrix::from_element(sol.information.nrows(), sol.information.ncols(), f64::NAN)
            });
            for (k, nid) in sol.order.iter().enumerate() {
                let xy = (0.5 * (cov[(3 * k, 3 * k)] + cov[(3 * k + 1, 3 * k + 1)])).sqrt();
                xy_sigma.insert(*nid, if translation { xy } else { f64::INFINITY });
                let y = cov[(3 * k + 2, 3 * k + 2)].max(0.0).sqrt();
                yaw_sigma.insert(*nid, if yaw { y } else { f64::INFINITY });
            }
        }
        WithCov {
            pose: sol.pose_map(),
            xy_sigma,
            yaw_sigma,
            observable: translation && yaw,
        }
    }

    /// The poses jointly with the latent VO scale and its 1-sigma: the scale is observable only when the data (an
    /// independent absolute reference) tighten it below 0.9 of its prior sigma; otherwise the posterior is the prior.
    #[must_use]
    pub fn optimize_with_scale(&self) -> WithScale {
        let sol = self.solve(50);
        let ns = self.estimate_vo_scale && !self.vo_between.is_empty();
        let (mut sigma, mut observable_scale) = (None, false);
        if ns && !sol.order.is_empty() {
            let si = 3 * sol.order.len();
            let s = sol
                .information
                .clone()
                .try_inverse()
                .map_or(f64::NAN, |cov| cov[(si, si)].max(0.0).sqrt());
            sigma = Some(s);
            if let Some((_, w)) = self.vo_scale_prior {
                observable_scale = s < 0.9 * (1.0 / w.sqrt());
            }
        }
        WithScale {
            pose: sol.pose_map(),
            vo_scale: sol.vo_scale,
            vo_scale_sigma: sigma,
            scale_observable: observable_scale,
            observable: !self.priors.is_empty(),
            status: sol.status,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{py_sci3, wrap};
    use std::f64::consts::PI;

    #[test]
    fn wrap_is_the_pythons_floored_modulo() {
        // CPython: (a + pi) % (2 pi) - pi lands in [-pi, pi); a truncating % would leave -4.0 at -4.0 + ...
        assert_eq!(wrap(PI).to_bits(), (-PI).to_bits());
        assert_eq!(wrap(-PI).to_bits(), (-PI).to_bits());
        assert!((wrap(-4.0) - (2.0 * PI - 4.0)).abs() < 1e-15);
        assert!((wrap(4.0) - (4.0 - 2.0 * PI)).abs() < 1e-15);
        assert_eq!(wrap(0.5).to_bits(), (0.5_f64 + PI - PI).to_bits());
    }

    #[test]
    fn the_exponent_is_formatted_as_python_does() {
        assert_eq!(py_sci3(-1.0), "-1.000e+00");
        assert_eq!(py_sci3(-2.5e-5), "-2.500e-05");
        assert_eq!(py_sci3(-1.234e123), "-1.234e+123");
    }
}
