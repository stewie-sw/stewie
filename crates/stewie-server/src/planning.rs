//! The planning context the planner and acceptance routes share (RW-55b4b-2): the body and fleet registries, the
//! soil baseline, and the planner parameters D-R85 requires to be given. Those come from a configuration file
//! (`STEWIE_PLANNER_CONFIG`, `deploy/planner.json` in a deployment), never compiled in; without one, the planning
//! routes answer 503 naming what is missing (D-R115).

use std::path::Path;

use serde_json::Value;
use stewie_contracts::body::BodyRegistry;
use stewie_contracts::fleet::Fleet;
use stewie_contracts::soil_baseline::SoilBaseline;
use stewie_physics::column::Regolith;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_plan::acceptance::AcceptanceInputs;
use stewie_plan::mission::{Mission, Registries, mission_from_value};
use stewie_plan::trips::{PlannerParams, context};

/// The configured planner parameters (gravity is the mission body's, from the registry).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlannerConfig {
    pub reserve_frac: f64,
    pub charge_w: f64,
    pub dig_rate_kg_s: f64,
    pub drive_speed_ms: f64,
    pub rolling_resistance: f64,
    pub drivetrain_efficiency: f64,
}

impl PlannerConfig {
    /// Read `stewie.planner-params/v1`: each parameter a `{value, source}` with a finite value.
    ///
    /// # Errors
    /// An unreadable file, another schema, or a missing or non-finite value.
    pub fn load(path: &Path) -> Result<Self, String> {
        let at = |e: String| format!("planner parameters {}: {e}", path.display());
        let body: Value =
            serde_json::from_str(&std::fs::read_to_string(path).map_err(|e| at(e.to_string()))?)
                .map_err(|e| at(e.to_string()))?;
        if body["schema"] != "stewie.planner-params/v1" {
            return Err(at("schema is not stewie.planner-params/v1".to_owned()));
        }
        let get = |k: &str| {
            body[k]["value"]
                .as_f64()
                .filter(|v| v.is_finite())
                .ok_or_else(|| at(format!("{k}.value must be a finite number")))
        };
        Ok(Self {
            reserve_frac: get("reserve_frac")?,
            charge_w: get("charge_w")?,
            dig_rate_kg_s: get("dig_rate_kg_s")?,
            drive_speed_ms: get("drive_speed_ms")?,
            rolling_resistance: get("rolling_resistance")?,
            drivetrain_efficiency: get("drivetrain_efficiency")?,
        })
    }
}

/// The acceptance inputs of one mission, owned (borrow them with [`Inputs::acceptance`]).
#[derive(Debug, Clone)]
pub struct Inputs {
    body_density: f64,
    regolith: Regolith,
    soil: SoilParams,
    gravity_ms2: f64,
    drum_kg: f64,
    dig_j_per_kg: f64,
}

impl Inputs {
    #[must_use]
    pub fn acceptance(&self) -> AcceptanceInputs<'_> {
        AcceptanceInputs {
            body_density: self.body_density,
            regolith: &self.regolith,
            soil: &self.soil,
            gravity_ms2: self.gravity_ms2,
            drum_kg: self.drum_kg,
            dig_j_per_kg: self.dig_j_per_kg,
        }
    }
}

/// The registries, soil baseline and (when configured) planner parameters.
#[derive(Debug)]
pub struct Planning {
    pub fleet: Fleet,
    pub bodies: BodyRegistry,
    pub soil_base: SoilBaseline,
    /// The planner parameters, or why there are none.
    pub config: Result<PlannerConfig, String>,
}

impl Planning {
    /// The context from the committed registries and `STEWIE_PLANNER_CONFIG`.
    ///
    /// # Errors
    /// A configured planner file that does not load (a set but broken path is a startup error, not a 503).
    pub fn from_env(get: &dyn Fn(&str) -> Option<String>) -> Result<Self, String> {
        let fleet: Fleet =
            serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json"))
                .map_err(|e| format!("the fleet registry: {e}"))?;
        let (bodies, soil_base) = bundled();
        let config = match get("STEWIE_PLANNER_CONFIG").filter(|p| !p.trim().is_empty()) {
            Some(p) => Ok(PlannerConfig::load(Path::new(&p))?),
            None => Err(
                "the planner parameters are not configured: set STEWIE_PLANNER_CONFIG to a \
                         stewie.planner-params/v1 file (deploy/planner.json)"
                    .to_owned(),
            ),
        };
        Ok(Self {
            fleet,
            bodies,
            soil_base,
            config,
        })
    }

    /// A mission from its JSON, checked against the registries (the Python's `mission_from_dict`).
    ///
    /// # Errors
    /// The boundary's refusal, in the Python's words.
    pub fn mission(&self, payload: &Value) -> Result<Mission, String> {
        mission_from_value(payload, &Registries::new(&self.bodies, &self.fleet)).map_err(|e| e.0)
    }

    /// The acceptance inputs of `m`: its body's density and gravity, its regolith model (the `soil` override, else
    /// the body's), and the selected vehicle's drum and dig energy.
    ///
    /// # Errors
    /// Planner parameters not configured (the first element is true then: a 503), or a body or vehicle the
    /// registries do not describe.
    pub fn inputs(&self, m: &Mission) -> Result<Inputs, (bool, String)> {
        let cfg = self.config.as_ref().map_err(|e| (true, e.clone()))?;
        let fail = |e: String| (false, e);
        let body = self
            .bodies
            .get(&m.body.trim().to_lowercase())
            .ok_or_else(|| fail(format!("unknown body {}", m.body)))?;
        let body_density = body
            .bulk_density
            .ok_or_else(|| fail(format!("body {} has no bulk density", m.body)))?;
        let gravity_ms2 = body.g;
        let params = PlannerParams {
            reserve_frac: cfg.reserve_frac,
            charge_w: cfg.charge_w,
            dig_rate_kg_s: cfg.dig_rate_kg_s,
            drive_speed_ms: cfg.drive_speed_ms,
            rolling_resistance: cfg.rolling_resistance,
            drivetrain_efficiency: cfg.drivetrain_efficiency,
            gravity_ms2,
        };
        let ctx = context(m, &self.fleet, &params).map_err(fail)?;
        let soil_key = if m.soil.trim().is_empty() {
            m.body.as_str()
        } else {
            m.soil.as_str()
        };
        let soil = SoilParams::for_body(&self.bodies, &self.soil_base, soil_key, false)
            .map_err(|e| fail(e.to_string()))?;
        Ok(Inputs {
            body_density,
            regolith: Regolith::new(body_density, &self.soil_base),
            soil,
            gravity_ms2,
            drum_kg: ctx.drum_kg,
            dig_j_per_kg: ctx.dig_j_per_kg,
        })
    }
}
