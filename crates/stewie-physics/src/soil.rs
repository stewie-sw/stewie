//! One soil parameter set per body (Python `body_params.params_for_body`). The Bekker moduli, cohesion,
//! friction and surface density come from the body registry; a body without sourced moduli or cohesion
//! takes the Moon's as a flagged analog. The shear modulus, slip-sinkage coefficients and compacted
//! density come from the soil baseline. There is no other source.

use stewie_contracts::body::{Body, BodyBekkerRegime, BodyRegistry};
use stewie_contracts::soil_baseline::SoilBaseline;

use crate::PhysicsError;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SoilParams {
    /// Bekker cohesive modulus [Pa/m^(n-1)].
    pub k_c: f64,
    /// Bekker frictional modulus [Pa/m^n].
    pub k_phi: f64,
    pub n: f64,
    pub cohesion_pa: f64,
    pub phi_rad: f64,
    /// Janosi-Hanamoto shear deformation modulus [m].
    pub k_shear_m: f64,
    pub slip_c1: f64,
    pub slip_c2: f64,
    /// Loose surface bulk density [kg/m^3].
    pub rho_surface: f64,
    /// Compacted ceiling [kg/m^3].
    pub rho_deep: f64,
    /// True when any value is another body's stand-in (results must be labelled analog).
    pub analog: bool,
}

/// The registry and baseline compiled into this crate (the committed contract fixtures).
///
/// # Panics
/// Never for the committed fixtures; the contract tests prove they parse.
#[must_use]
pub fn bundled() -> (BodyRegistry, SoilBaseline) {
    let reg = serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json"))
        .expect("committed body registry parses");
    let base = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/soil_baseline.json"
    ))
    .expect("committed soil baseline parses");
    (reg, base)
}

/// The body's own sourced value, else the Moon's as a flagged analog.
fn or_moon(
    own: Option<f64>,
    moon: Option<f64>,
    what: &str,
    analog: &mut bool,
) -> Result<f64, PhysicsError> {
    if let Some(v) = own {
        return Ok(v);
    }
    *analog = true;
    moon.ok_or_else(|| PhysicsError::InvalidInput(format!("the Moon has no sourced {what}")))
}

fn body<'a>(reg: &'a BodyRegistry, name: &str) -> Result<&'a Body, PhysicsError> {
    let key = name.trim().to_lowercase();
    reg.get(&key)
        .ok_or_else(|| PhysicsError::UnknownBody(name.to_owned()))
}

impl SoilParams {
    /// Parameters for `name` from `reg` and `base`.
    ///
    /// # Errors
    /// An unknown body; a microgravity body unless `allow_analog`; a registry with no sourced lunar
    /// values to stand in.
    pub fn for_body(
        reg: &BodyRegistry,
        base: &SoilBaseline,
        name: &str,
        allow_analog: bool,
    ) -> Result<Self, PhysicsError> {
        let b = body(reg, name)?;
        let micro = matches!(b.bekker_regime, BodyBekkerRegime::Microgravity);
        if micro && !allow_analog {
            return Err(PhysicsError::OutOfRegime {
                body: b.name.to_string(),
                g: b.g,
            });
        }
        let moon = body(reg, "moon")?;
        let lunar = moon.bekker.as_ref().ok_or_else(|| {
            PhysicsError::InvalidInput("the Moon has no sourced Bekker moduli".into())
        })?;
        let (bk, mut analog) = match &b.bekker {
            Some(k) => (k, micro),
            None => (lunar, true),
        };
        let cohesion_pa = or_moon(b.cohesion_pa, moon.cohesion_pa, "cohesion", &mut analog)?;
        let phi_deg = or_moon(
            b.friction_deg,
            moon.friction_deg,
            "friction angle",
            &mut analog,
        )?;
        let rho_surface = or_moon(
            b.bulk_density,
            moon.bulk_density,
            "bulk density",
            &mut analog,
        )?;
        Ok(Self {
            k_c: bk.k_c,
            k_phi: bk.k_phi,
            n: bk.n,
            cohesion_pa,
            phi_rad: phi_deg.to_radians(),
            k_shear_m: base.k_shear_m.value,
            slip_c1: base.slip_c1.value,
            slip_c2: base.slip_c2.value,
            rho_surface,
            rho_deep: base.rho_deep.value,
            analog,
        })
    }
}
