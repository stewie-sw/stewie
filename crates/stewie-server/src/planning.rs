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
    /// Slip energy multiplier versus tan(slope) [CALIB] (the endurance reach field).
    pub slip_alpha: f64,
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
            slip_alpha: get("slip_alpha")?,
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
    /// Wheel slip on a grade, empty, for a rover of `rover_mass_kg` on this mission's body, in `soil` (Python
    /// `slip_alpha_to_slip(slope, params=soil)`).
    ///
    /// # Errors
    /// The slip equilibrium's refusal.
    pub fn slip(
        &self,
        soil: &SoilParams,
        slope_deg: f64,
        rover_mass_kg: f64,
    ) -> Result<f64, String> {
        stewie_plan::trips::slip_at(
            slope_deg,
            0.0,
            rover_mass_kg,
            self.gravity_ms2,
            soil,
            &self.slip,
        )
    }

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
    /// The endurance report's timescale and `ConOps` tables.
    pub endurance: stewie_plan::endurance::Tables,
    /// What a plan's provenance needs beyond the mission.
    pub provenance: stewie_plan::provenance::Defaults,
    /// The closed-loop overlay's map-channel constants and learned slip model.
    pub autonomy: stewie_plan::autonomy::Tables,
    /// What the Markdown report quotes: the Assumptions Register and the drum-fill sensing bands.
    pub report: ReportTables,
}

/// `plan_report.json`: the Assumptions Register (`planner_views.assumptions_register`) and the drum-fill sensing
/// error bands (`rassor_mass_model`).
#[derive(Debug, Clone, serde::Deserialize)]
pub struct ReportTables {
    pub assumptions_register: Vec<Value>,
    pub fdc_mpe_half_full: f64,
    pub fdc_mpe_all: f64,
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
        let endurance = serde_json::from_str(include_str!(
            "../../stewie-contracts/fixtures/endurance.json"
        ))
        .map_err(|e| format!("the endurance tables: {e}"))?;
        let autonomy = serde_json::from_str(include_str!(
            "../../stewie-contracts/fixtures/autonomy.json"
        ))
        .map_err(|e| format!("the autonomy tables: {e}"))?;
        let provenance = serde_json::from_str(include_str!(
            "../../stewie-contracts/fixtures/plan_provenance.json"
        ))
        .map_err(|e| format!("the plan provenance defaults: {e}"))?;
        let report = serde_json::from_str(include_str!(
            "../../stewie-contracts/fixtures/plan_report.json"
        ))
        .map_err(|e| format!("the plan report tables: {e}"))?;
        Ok(Self {
            fleet,
            bodies,
            soil_base,
            config,
            endurance,
            provenance,
            autonomy,
            report,
        })
    }

    /// The endurance report of `m`'s vehicle (Python `planner_endurance.endurance`), on `dem` when there is one.
    ///
    /// # Errors
    /// Planner parameters not configured, an unknown power kind, or a registry without the IPEx pack or the Moon.
    pub fn endurance(
        &self,
        m: &Mission,
        inputs: &Inputs,
        dem: Option<&Dem<'_>>,
        power_site: &str,
        temp_c: Option<f64>,
    ) -> Result<serde_json::Value, String> {
        let cfg = self.config.as_ref().map_err(Clone::clone)?;
        let ctx = context(m, &self.fleet, &inputs.params)?;
        let ipex_battery_j = self.ipex_battery_j()?;
        let lunar_g = self
            .bodies
            .get("moon")
            .map(|b| b.g)
            .ok_or("the body registry has no moon")?;
        let inp = stewie_plan::endurance::Inputs {
            body: &m.body,
            gravity_ms2: inputs.params.gravity_ms2,
            slip_gravity_ms2: lunar_g,
            charge_w: cfg.charge_w,
            ipex_battery_j,
            slip_alpha: cfg.slip_alpha,
            soil: &inputs.soil,
            slip: &inputs.slip,
            tables: &self.endurance,
        };
        stewie_plan::endurance::endurance(&ctx, dem, power_site, temp_c, &inp)
    }

    /// The IPEx pack [J] (the Python's module `BATTERY_J`).
    ///
    /// # Errors
    /// A fleet registry without it.
    pub fn ipex_battery_j(&self) -> Result<f64, String> {
        self.fleet
            .power_sources
            .get("ipex_battery")
            .map(|p| p.capacity_j)
            .ok_or_else(|| "the fleet registry has no ipex_battery".to_owned())
    }

    /// The provenance and playback timeline of `plan` (Python `_plan_provenance` and `build_timeline`); `commit`
    /// names the source the server was built from.
    ///
    /// # Errors
    /// Planner parameters not configured, or a non-finite number in the mission.
    pub fn timeline(
        &self,
        m: &Mission,
        plan: &stewie_plan::assemble::Plan,
        origin: (f64, f64),
        (algorithm, objective, vehicles): (&str, &str, usize),
        commit: &str,
    ) -> Result<serde_json::Value, String> {
        let cfg = self.config.as_ref().map_err(Clone::clone)?;
        let req = stewie_plan::provenance::Request {
            origin,
            algorithm,
            objective,
            vehicles,
            default_return_buffer_frac: cfg.report.default_return_buffer_frac,
        };
        let prov = stewie_plan::provenance::provenance(
            m,
            &req,
            &self.provenance,
            commit,
            env!("CARGO_PKG_VERSION"),
        )?;
        Ok(stewie_plan::provenance::timeline(
            plan,
            m,
            self.ipex_battery_j()?,
            &prov,
        ))
    }

    /// The `/plan` response's `autonomy` and `perception` blocks: the closed-loop overlay on `plan` (one rover)
    /// over `dem` (Python `routers.plan._autonomy_perception`).
    ///
    /// # Errors
    /// The slip ladder refusing a leg's inputs.
    pub fn autonomy_perception(
        &self,
        m: &Mission,
        inputs: &Inputs,
        plan: &stewie_plan::assemble::Plan,
        dem: &Dem<'_>,
    ) -> Result<(serde_json::Value, serde_json::Value), String> {
        let ctx = context(m, &self.fleet, &inputs.params)?;
        let inp = stewie_plan::autonomy::Inputs {
            ctx: &ctx,
            gravity_ms2: inputs.params.gravity_ms2,
            soil: &inputs.soil,
            slip: &inputs.slip,
            map: &self.autonomy.map_channel,
            model: &self.autonomy.learned_model,
        };
        stewie_plan::autonomy::autonomy_perception(m, plan, dem, &inp)
    }

    /// The closed loop over `plan` on `dem` (Python `lode.autonomy.run_closed_loop`), with a `perception` fix
    /// precision [m] or none (a training session's dead-reckoned run).
    ///
    /// # Errors
    /// The slip ladder refusing a leg's inputs.
    pub fn closed_loop(
        &self,
        m: &Mission,
        inputs: &Inputs,
        plan: &stewie_plan::assemble::Plan,
        dem: &Dem<'_>,
        perception: Option<f64>,
    ) -> Result<stewie_plan::autonomy::ClosedLoop, String> {
        let ctx = context(m, &self.fleet, &inputs.params)?;
        let inp = stewie_plan::autonomy::Inputs {
            ctx: &ctx,
            gravity_ms2: inputs.params.gravity_ms2,
            soil: &inputs.soil,
            slip: &inputs.slip,
            map: &self.autonomy.map_channel,
            model: &self.autonomy.learned_model,
        };
        stewie_plan::autonomy::run_closed_loop(m, plan, dem, &inp, perception)
    }

    /// The Markdown report of `plan` (Python `planner_views.report`, its Markdown half), with its `totals` and
    /// endurance report `endu`.
    ///
    /// # Errors
    /// Planner parameters not configured, or a registry without the IPEx pack or vehicle.
    pub fn markdown(
        &self,
        m: &Mission,
        inputs: &Inputs,
        plan: &stewie_plan::assemble::Plan,
        totals: &Value,
        endu: &Value,
    ) -> Result<String, String> {
        let cfg = self.config.as_ref().map_err(Clone::clone)?;
        let ctx = context(m, &self.fleet, &inputs.params)?;
        let ipex = self
            .fleet
            .vehicles
            .get("ipex")
            .ok_or("the fleet registry has no ipex")?;
        let c = stewie_plan::report_md::Consts {
            battery_j: self.ipex_battery_j()?,
            dig_j_per_kg: cfg.ipex_dig_j_per_kg,
            drive_j_per_m: cfg.ipex_drive_j_per_m,
            recharge_w: cfg.charge_w,
            drum_kg: ctx.drum_kg,
            fdc_mpe_half_full: self.report.fdc_mpe_half_full,
            fdc_mpe_all: self.report.fdc_mpe_all,
            geometry: (ipex.gauge_m, ipex.wheelbase_m, ipex.cg_height_m),
            register: &self.report.assumptions_register,
            default_date: &self.provenance.default_date,
        };
        Ok(stewie_plan::report_md::markdown(m, plan, totals, endu, &c))
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

#[cfg(test)]
mod tests {
    use serde_json::Value;

    use super::ReportTables;

    /// The report quotes the Assumptions Register exported from the spec sources, while the planner runs on
    /// `deploy/planner.json`: every configured value whose source names a register constant must equal it, so the
    /// report cannot describe values the plan was not computed with.
    #[test]
    fn the_report_register_agrees_with_the_configured_planner_values() {
        let tables: ReportTables = serde_json::from_str(include_str!(
            "../../stewie-contracts/fixtures/plan_report.json"
        ))
        .unwrap();
        let cfg: Value =
            serde_json::from_str(include_str!("../../../deploy/planner.json")).unwrap();
        let mut checked = 0;
        for (key, entry) in cfg.as_object().unwrap() {
            let (Some(v), Some(src)) = (entry["value"].as_f64(), entry["source"].as_str()) else {
                continue;
            };
            for r in &tables.assumptions_register {
                let name = r["name"].as_str().unwrap();
                let named = src
                    .split(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
                    .any(|w| w == name);
                if let (true, Ok(rv)) = (named, r["value"].as_str().unwrap().parse::<f64>()) {
                    assert!(
                        (rv - v).abs() <= 1e-12 * v.abs(),
                        "{key} = {v}, but the register's {name} = {rv}"
                    );
                    checked += 1;
                }
            }
        }
        assert!(checked > 0, "no configured value names a register constant");
    }
}
