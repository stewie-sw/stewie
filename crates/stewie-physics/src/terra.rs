//! Bekker pressure-sinkage, Janosi-Hanamoto shear and the slip-sinkage equilibrium (Python
//! `stewie_forge.terramechanics` and `stewie.physics.slip`).
//!
//! Bekker: `p = (k_c/b + k_phi*s) * z^n`, inverted for the sinkage `z`; `s >= 1` stiffens denser soil.
//! Traction ceiling `H_max = c*A + N*tan(phi)`; developed thrust `H(s) = H_max*(1 - (1-e^-x)/x)`,
//! `x = s*L/K`. Entrapment is a demand the curve cannot develop at any allowed slip.

use crate::PhysicsError;
use crate::soil::SoilParams;

/// Bearing stiffening `s(rho) = max(1, rho/rho_surface)`: a repeated pass on compacted soil sinks less.
#[must_use]
pub fn density_stiffening(density: f64, rho_surface: f64) -> f64 {
    (density / rho_surface).max(1.0)
}

/// Static Bekker sinkage [m] under `pressure_pa` on a plate of width `b_m`.
///
/// # Errors
/// A non-positive plate width or bearing modulus.
pub fn bekker_sinkage(
    pressure_pa: f64,
    b_m: f64,
    p: &SoilParams,
    stiffening: f64,
) -> Result<f64, PhysicsError> {
    if pressure_pa <= 0.0 {
        return Ok(0.0);
    }
    if b_m <= 0.0 {
        return Err(PhysicsError::InvalidInput(format!(
            "plate width {b_m} m must be > 0"
        )));
    }
    let k = p.k_c / b_m + p.k_phi * stiffening.max(1.0);
    if k <= 0.0 {
        return Err(PhysicsError::InvalidInput(
            "bearing modulus k_c/b + k_phi*s must be > 0".into(),
        ));
    }
    Ok((pressure_pa / k).powf(1.0 / p.n))
}

/// Static sinkage [m] of one rectangular contact under `load_n`; `density` (the cell's) stiffens it.
///
/// # Errors
/// As [`bekker_sinkage`].
pub fn contact_static_sinkage(
    load_n: f64,
    contact_len_m: f64,
    contact_width_m: f64,
    density: Option<f64>,
    p: &SoilParams,
) -> Result<f64, PhysicsError> {
    if load_n <= 0.0 {
        return Ok(0.0);
    }
    let pressure = load_n / (contact_len_m * contact_width_m).max(1e-9);
    let s = density.map_or(1.0, |d| density_stiffening(d, p.rho_surface));
    bekker_sinkage(pressure, contact_len_m.min(contact_width_m), p, s)
}

/// Density increase `f` (apply `density *= 1 + f`) that thins a column of `thickness_m` by `z_m` at fixed
/// areal mass, so compaction conserves mass. `z` is clamped below the thickness.
#[must_use]
pub fn sinkage_to_density_factor(z_m: f64, thickness_m: f64) -> f64 {
    if z_m <= 0.0 || thickness_m <= 0.0 {
        return 0.0;
    }
    let z = z_m.min(0.999 * thickness_m);
    z / (thickness_m - z)
}

/// Sinkage multiplier (>= 1) from slip: `1 + (c1 + c2*s) * s/(1-s)`, slip clamped to `[0, 0.95]`.
#[must_use]
pub fn slip_sinkage_multiplier(slip: f64, p: &SoilParams) -> f64 {
    let s = slip.clamp(0.0, 0.95);
    1.0 + (p.slip_c1 + p.slip_c2 * s) * (s / (1.0 - s))
}

/// Coulomb-Mohr traction ceiling [N]: `c*A + N*tan(phi)`.
#[must_use]
pub fn traction_budget(normal_load_n: f64, contact_area_m2: f64, p: &SoilParams) -> f64 {
    p.cohesion_pa * contact_area_m2 + normal_load_n * p.phi_rad.tan()
}

/// Janosi-Hanamoto thrust [N] at `slip`; 0 for no slip, rising monotonically toward `h_max`.
#[must_use]
pub fn developed_thrust(slip: f64, h_max: f64, contact_len_m: f64, k_shear_m: f64) -> f64 {
    if slip <= 0.0 {
        return 0.0;
    }
    let x = slip * contact_len_m / k_shear_m;
    h_max * (1.0 - (-(-x).exp_m1()) / x)
}

/// Upper end of the allowed slip range.
pub const SLIP_MAX: f64 = 0.99;

/// Slip that develops `demand_n`, and whether the wheel is entrapped (the demand is beyond what the
/// curve develops at [`SLIP_MAX`]). Bisection, 60 halvings.
#[must_use]
pub fn slip_for_demand(
    demand_n: f64,
    h_max: f64,
    contact_len_m: f64,
    k_shear_m: f64,
) -> (f64, bool) {
    if demand_n <= 0.0 {
        return (0.0, false);
    }
    let h = |s| developed_thrust(s, h_max, contact_len_m, k_shear_m);
    if demand_n >= h_max || demand_n >= h(SLIP_MAX) {
        return (SLIP_MAX, true);
    }
    let (mut lo, mut hi) = (1e-6, SLIP_MAX);
    for _ in 0..60 {
        let mid = 0.5 * (lo + hi);
        if h(mid) < demand_n {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    (0.5 * (lo + hi), false)
}

/// Bekker compaction (motion) resistance [N] of a contact `width_m` wide sunk by `sinkage_m`.
#[must_use]
pub fn compaction_resistance(sinkage_m: f64, width_m: f64, p: &SoilParams) -> f64 {
    if sinkage_m <= 0.0 {
        return 0.0;
    }
    (width_m / (p.n + 1.0)) * (p.k_c / width_m + p.k_phi) * sinkage_m.powf(p.n + 1.0)
}

/// The vehicle and the request for one [`slip_sinkage_equilibrium`] solve.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DriveCase {
    pub total_weight_n: f64,
    pub slope_rad: f64,
    pub n_wheels: u32,
    pub contact_len_m: f64,
    pub contact_width_m: f64,
    /// The contacted cell's density; `None` is the loose surface.
    pub density: Option<f64>,
    /// Fraction of the along-slope demand commanded (the operator's recovery lever).
    pub demand_frac: f64,
    /// Extra whole-vehicle horizontal demand [N] (e.g. an excavation draft), split per wheel.
    pub extra_demand_n: f64,
    /// Slip at which the loop is declared a runaway.
    pub s_entrap: f64,
    /// Sinkage at which the loop is declared a runaway [m].
    pub z_entrap_m: f64,
}

/// Outcome of the per-wheel slip-sinkage fixed point.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Equilibrium {
    pub slip: f64,
    pub sinkage_m: f64,
    pub static_sinkage_m: f64,
    pub resistance_n: f64,
    pub demand_n: f64,
    pub budget_n: f64,
    pub entrapped: bool,
    pub iters: u32,
}

/// Iterate demand -> slip -> sinkage -> resistance per wheel until the sinkage settles (to 1e-7 m, at most
/// 200 rounds) or runs away (entrapment): the Spirit-rover failure mode.
///
/// # Errors
/// As [`bekker_sinkage`], or zero wheels.
pub fn slip_sinkage_equilibrium(
    c: &DriveCase,
    p: &SoilParams,
) -> Result<Equilibrium, PhysicsError> {
    if c.n_wheels == 0 {
        return Err(PhysicsError::InvalidInput("n_wheels must be >= 1".into()));
    }
    let nw = f64::from(c.n_wheels);
    let normal = c.total_weight_n * c.slope_rad.cos() / nw;
    let along = c.total_weight_n * c.slope_rad.sin() / nw;
    let h_max = traction_budget(normal, c.contact_len_m * c.contact_width_m, p);
    let z_static =
        contact_static_sinkage(normal, c.contact_len_m, c.contact_width_m, c.density, p)?;
    let extra = c.extra_demand_n / nw;
    let (mut sink, mut slip, mut resistance) = (z_static, 0.0, 0.0);
    let mut demand = c.demand_frac * along + extra;
    let (mut entrapped, mut iters) = (false, 0);
    for i in 0..200 {
        iters = i + 1;
        resistance = compaction_resistance(sink, c.contact_width_m, p);
        demand = c.demand_frac * along + extra + resistance;
        let (s, ent) = slip_for_demand(demand, h_max, c.contact_len_m, p.k_shear_m);
        slip = s;
        if ent {
            entrapped = true;
            // report the runaway sinkage, not the near-static value
            sink = z_static * slip_sinkage_multiplier(slip.max(c.s_entrap), p);
            break;
        }
        let new_sink = z_static * slip_sinkage_multiplier(slip, p);
        if new_sink >= c.z_entrap_m || slip >= c.s_entrap {
            entrapped = true;
            sink = new_sink;
            break;
        }
        let settled = (new_sink - sink).abs() < 1e-7;
        sink = new_sink;
        if settled {
            break;
        }
    }
    Ok(Equilibrium {
        slip,
        sinkage_m: sink,
        static_sinkage_m: z_static,
        resistance_n: resistance,
        demand_n: demand,
        budget_n: h_max,
        entrapped,
        iters,
    })
}

/// Steady-drive electrical power from the Bekker motion resistance and grade.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DrivePower {
    pub drive_power_w: f64,
    pub tractive_n: f64,
    pub slip: f64,
    pub sinkage_m: f64,
    /// When true, steady drive cannot proceed and the power figure is not meaningful.
    pub entrapped: bool,
}

/// Electrical power to hold `v_ms` up or down `slope_rad` (descent needs braking traction of the same
/// magnitude). A lower bound: compaction resistance and grade only, no bulldozing or hysteresis.
///
/// # Errors
/// As [`slip_sinkage_equilibrium`], or a non-positive efficiency.
pub fn bekker_drive_power(
    c: &DriveCase,
    v_ms: f64,
    efficiency: f64,
    p: &SoilParams,
) -> Result<DrivePower, PhysicsError> {
    if efficiency <= 0.0 {
        return Err(PhysicsError::InvalidInput(format!(
            "efficiency {efficiency} must be > 0"
        )));
    }
    let eq = slip_sinkage_equilibrium(
        &DriveCase {
            slope_rad: c.slope_rad.abs(),
            ..*c
        },
        p,
    )?;
    let tractive_n = eq.demand_n * f64::from(c.n_wheels);
    let s = eq.slip.min(SLIP_MAX);
    Ok(DrivePower {
        // holding ground speed at slip s spins the wheels 1/(1-s) faster
        drive_power_w: tractive_n * v_ms / ((1.0 - s) * efficiency),
        tractive_n,
        slip: eq.slip,
        sinkage_m: eq.sinkage_m,
        entrapped: eq.entrapped,
    })
}
