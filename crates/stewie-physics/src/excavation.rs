//! Excavation draft force from the McKyes/Reece Fundamental Earthmoving Equation (Python
//! `stewie.physics.excavation`; McKyes 1985 ch. 3-4; Reece 1964; Wilkinson & DeGennaro 2007, eq. 1):
//!
//! `F = (gamma*g*d^2*N_gamma + c*d*N_c + q*d*N_q) * w`, with the N-factors of a planar wedge failing at
//! `beta` below horizontal, and `beta` the angle that minimises `F` over `(0, pi/2 - phi)`.
//!
//! The tool rake angle and soil-tool friction for the IPEx bucket-drum are unpublished ([CALIB-PENDING]
//! in the Python), so they are required arguments here, never defaults.

use crate::PhysicsError;

/// `(N_gamma, N_c, N_q)` for a wedge failing at `beta_rad`, tool rake `rake_rad`, soil-tool friction
/// `delta_rad`.
///
/// # Errors
/// `beta` outside `(0, pi/2)`, `beta + phi >= pi/2`, or a non-positive denominator.
pub fn factors(
    phi_rad: f64,
    beta_rad: f64,
    rake_rad: f64,
    delta_rad: f64,
) -> Result<(f64, f64, f64), PhysicsError> {
    use std::f64::consts::FRAC_PI_2;
    if !(beta_rad > 0.0 && beta_rad < FRAC_PI_2) || beta_rad + phi_rad >= FRAC_PI_2 {
        return Err(PhysicsError::InvalidInput(format!(
            "no positive wedge at beta {beta_rad} rad, phi {phi_rad} rad"
        )));
    }
    let (cot_a, cot_b, cot_bp) = (
        1.0 / rake_rad.tan(),
        1.0 / beta_rad.tan(),
        1.0 / (beta_rad + phi_rad).tan(),
    );
    let denom = (rake_rad + delta_rad).cos() + (rake_rad + delta_rad).sin() * cot_bp;
    if denom <= 0.0 {
        return Err(PhysicsError::InvalidInput(
            "earthmoving denominator must be > 0".into(),
        ));
    }
    Ok((
        (cot_a + cot_b) / (2.0 * denom),
        (1.0 + cot_b * cot_bp) / denom,
        (cot_a + cot_b) / denom,
    ))
}

/// One dig: the cut, the soil and the tool.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Dig {
    pub depth_m: f64,
    pub width_m: f64,
    pub cohesion_pa: f64,
    pub bulk_density_kg_m3: f64,
    pub gravity_ms2: f64,
    pub phi_rad: f64,
    pub rake_rad: f64,
    pub soil_tool_friction_rad: f64,
    pub surcharge_pa: f64,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DigReport {
    pub draft_n: f64,
    pub n_gamma: f64,
    pub n_c: f64,
    pub n_q: f64,
    pub beta_rad: f64,
    /// Ideal cutting work per kg excavated, `F / (rho*w*d)`: a lower bound on electrical dig energy.
    pub specific_energy_j_per_kg: f64,
}

/// Solve the FEE: scan `beta` over `n_beta + 1` knots of `(1e-3, pi/2 - phi - 1e-3)` and keep the least
/// draft (the wedge fails along the least-force surface).
///
/// # Errors
/// Non-positive depth, width or density; `phi` outside `(0, pi/2)`; negative cohesion or surcharge; no
/// valid wedge in the window.
#[allow(clippy::cast_precision_loss)] // knot counts are far below 2^52
pub fn solve(dig: &Dig, n_beta: u32) -> Result<DigReport, PhysicsError> {
    let d = dig;
    let bad = |m: &str| Err(PhysicsError::InvalidInput(m.to_owned()));
    if d.depth_m <= 0.0 || d.width_m <= 0.0 || d.bulk_density_kg_m3 <= 0.0 {
        return bad("depth, width and density must be > 0");
    }
    if !(d.phi_rad > 0.0 && d.phi_rad < std::f64::consts::FRAC_PI_2) {
        return bad("phi must be in (0, pi/2)");
    }
    if d.cohesion_pa < 0.0 || d.surcharge_pa < 0.0 {
        return bad("cohesion and surcharge must be >= 0");
    }
    let (lo, hi) = (1e-3, std::f64::consts::FRAC_PI_2 - d.phi_rad - 1e-3);
    if hi <= lo {
        return bad("no valid rupture-angle window");
    }
    let mut best: Option<DigReport> = None;
    for i in 0..=n_beta {
        let beta = lo + (hi - lo) * f64::from(i) / f64::from(n_beta);
        let Ok((ng, nc, nq)) = factors(d.phi_rad, beta, d.rake_rad, d.soil_tool_friction_rad)
        else {
            continue;
        };
        let f = (d.bulk_density_kg_m3 * d.gravity_ms2 * d.depth_m * d.depth_m * ng
            + d.cohesion_pa * d.depth_m * nc
            + d.surcharge_pa * d.depth_m * nq)
            * d.width_m;
        if best.is_none_or(|b| f < b.draft_n) {
            best = Some(DigReport {
                draft_n: f,
                n_gamma: ng,
                n_c: nc,
                n_q: nq,
                beta_rad: beta,
                specific_energy_j_per_kg: f / (d.bulk_density_kg_m3 * d.width_m * d.depth_m),
            });
        }
    }
    best.ok_or_else(|| {
        PhysicsError::InvalidInput("no valid earthmoving wedge in the beta window".into())
    })
}
