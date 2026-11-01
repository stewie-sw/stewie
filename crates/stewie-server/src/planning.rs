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
use stewie_plan::balance::Profile;
use stewie_plan::mission::{Mission, Registries, mission_from_value};
use stewie_plan::report::ReportParams;
use stewie_plan::trips::{BuildInputs, PlannerParams, SlipModel, context};
use stewie_traverse::route::Dem;

/// The configured planner parameters (gravity is the mission body's, from the registry).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PlannerConfig {
    pub reserve_frac: f64,
    pub charge_w: f64,
    pub dig_rate_kg_s: f64,
    pub drive_speed_ms: f64,
    pub rolling_resistance: f64,
    pub drivetrain_efficiency: f64,
    /// Continuous survival draw over a mission [W] (0 leaves it unmodelled).
    pub idle_power_w: f64,
    /// The wheel model the per-leg slip is solved with.
    pub slip: SlipModel,
    /// The report's sourced constants (gravity is filled per mission from the body registry).
    pub report: ReportParams,
    /// The math worksheet's `DIG_J_PER_KG` and `DRIVE_J_PER_M` (the Python's IPEx module constants).
    pub ipex_dig_j_per_kg: f64,
    pub ipex_drive_j_per_m: f64,
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
        let wheels = get("slip_n_wheels")?;
        if wheels.fract() != 0.0 || !(1.0..=64.0).contains(&wheels) {
            return Err(at(
                "slip_n_wheels.value must be a whole number of wheels".to_owned()
            ));
        }
        Ok(Self {
            reserve_frac: get("reserve_frac")?,
            charge_w: get("charge_w")?,
            dig_rate_kg_s: get("dig_rate_kg_s")?,
            drive_speed_ms: get("drive_speed_ms")?,
            rolling_resistance: get("rolling_resistance")?,
            drivetrain_efficiency: get("drivetrain_efficiency")?,
            idle_power_w: get("idle_power_w")?,
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // a checked whole count
            slip: SlipModel {
                n_wheels: wheels as u32,
                contact_len_m: get("slip_contact_len_m")?,
                contact_width_m: get("slip_contact_width_m")?,
                z_entrap_m: get("slip_z_entrap_m")?,
            },
            report: ReportParams {
                drum_rate_ratio: get("drum_rate_ratio")?,
                max_cut_per_pass_m: get("max_cut_per_pass_m")?,
                fill_mpe_frac: get("fill_mpe_frac")?,
                localization_margin_m: get("localization_margin_m")?,
                dem_cell_sigma_m: get("dem_cell_sigma_m")?,
                relocalize_drift_tol_m: get("relocalize_drift_tol_m")?,
                drift_frac: get("drift_frac")?,
                fix_maneuver_s: get("fix_maneuver_s")?,
                arm_lift_height_m: get("arm_lift_height_m")?,
                arm_lift_efficiency: get("arm_lift_efficiency")?,
                gravity_ms2: 0.0,
                default_return_buffer_frac: get("default_return_buffer_frac")?,
            },
            ipex_dig_j_per_kg: get("ipex_dig_j_per_kg")?,
            ipex_drive_j_per_m: get("ipex_drive_j_per_m")?,
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
    pub params: PlannerParams,
    pub profile: Profile,
    pub slip: SlipModel,
    /// The report constants with the mission body's gravity.
    pub report: ReportParams,
    pub idle_power_w: f64,
}

impl Inputs {
    /// The planner's build inputs on `dem` under the operator's slope budget.
    #[must_use]
    pub fn build<'a>(&'a self, dem: Dem<'a>, max_traverse_slope_deg: f64) -> BuildInputs<'a> {
        BuildInputs {
            dem,
            max_traverse_slope_deg,
            body_density: self.body_density,
            profile: &self.profile,
            soil: &self.soil,
            slip: &self.slip,
            params: &self.params,
        }
    }

    /// The mission body's loose density [kg/m^3].
    #[must_use]
    pub fn body_density(&self) -> f64 {
        self.body_density
    }

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
        let regolith = Regolith::new(body_density, &self.soil_base);
        let profile = Profile {
            rho_surface: body_density,
            rho_deep: regolith.rho_deep,
            z_t_m: regolith.z_t_m,
        };
        Ok(Inputs {
            body_density,
            regolith,
            soil,
            gravity_ms2,
            drum_kg: ctx.drum_kg,
            dig_j_per_kg: ctx.dig_j_per_kg,
            params,
            profile,
            slip: cfg.slip,
            report: ReportParams {
                gravity_ms2,
                ..cfg.report
            },
            idle_power_w: cfg.idle_power_w,
        })
    }
}
