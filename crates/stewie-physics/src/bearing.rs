//! Terzaghi/Vesic static bearing capacity of a built pad or berm under a structural load (Python
//! `stewie_forge.bearing`): `q_ult = c*Nc + (gamma*D)*Nq + 0.5*gamma*B*Ngamma` with the Prandtl-Reissner
//! factors and Vesic (1973) `Ngamma`. For rover trafficability use [`crate::terra`]; slip-sinkage, not
//! static bearing, limits a light rover. Sources: Terzaghi (1943); Vesic (1973), JSMFD 99(SM1).

/// Prandtl's `Nc` for a purely cohesive (phi = 0) soil.
pub const NC_PHI0: f64 = 5.14;

/// `(Nc, Nq, Ngamma)` for friction angle `phi_rad`; the cohesive limit `(5.14, 1, 0)` at phi -> 0.
#[must_use]
pub fn factors(phi_rad: f64) -> (f64, f64, f64) {
    if phi_rad <= 1e-9 {
        return (NC_PHI0, 1.0, 0.0);
    }
    let t = phi_rad.tan();
    let nq = (std::f64::consts::PI * t).exp()
        * (std::f64::consts::FRAC_PI_4 + phi_rad / 2.0).tan().powi(2);
    ((nq - 1.0) / t, nq, 2.0 * (nq + 1.0) * t)
}

/// Ultimate bearing capacity [Pa] of a footing `width_m` wide at `surcharge_depth_m`.
#[must_use]
pub fn ultimate_pa(
    cohesion_pa: f64,
    phi_rad: f64,
    unit_weight_n_m3: f64,
    width_m: f64,
    surcharge_depth_m: f64,
) -> f64 {
    let (nc, nq, ng) = factors(phi_rad);
    cohesion_pa * nc
        + unit_weight_n_m3 * surcharge_depth_m.max(0.0) * nq
        + 0.5 * unit_weight_n_m3 * width_m.max(0.0) * ng
}

/// Allowable bearing pressure [Pa]: `q_ult / factor_of_safety` (3.0 is the standard shallow-foundation
/// factor, Das/Bowles; the caller chooses).
#[must_use]
pub fn allowable_pa(
    cohesion_pa: f64,
    phi_rad: f64,
    unit_weight_n_m3: f64,
    width_m: f64,
    surcharge_depth_m: f64,
    factor_of_safety: f64,
) -> f64 {
    ultimate_pa(
        cohesion_pa,
        phi_rad,
        unit_weight_n_m3,
        width_m,
        surcharge_depth_m,
    ) / factor_of_safety.max(1e-9)
}
