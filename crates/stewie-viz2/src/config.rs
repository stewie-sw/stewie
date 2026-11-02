//! The runtime's production figures, each from its committed source: the vehicle and drums from the IPEx profile
//! (`rover_ipex.json`, D-R54), the terramechanics from `terramechanics_constants.json`, the body from the registry,
//! the CALIB values from the planner file (`STEWIE_PLANNER_CONFIG`, RW-30: no compiled calibration), and the drum-fill
//! error bands from `plan_report.json`.

use std::path::Path;

use serde_json::Value;
use stewie_physics::column::Regolith;
use stewie_physics::drive::Vehicle;
use stewie_physics::drum_sensor::ErrorBands;
use stewie_physics::soil::SoilParams;
use stewie_physics::worksite::Setup;

use crate::runtime::{Calib, Drum};

fn num(v: &Value, what: &str) -> Result<f64, String> {
    v.as_f64()
        .filter(|x| x.is_finite())
        .ok_or_else(|| format!("{what} must be a finite number"))
}

/// The world setup for `body` on the IPEx profile.
///
/// # Errors
/// A committed source that does not parse, or a body the registry lacks.
pub fn production_setup(body: &str) -> Result<Setup, String> {
    let profile: stewie_contracts::rover_profile::RoverProfile = serde_json::from_str(
        include_str!("../../stewie-contracts/fixtures/rover_ipex.json"),
    )
    .map_err(|e| format!("rover_ipex.json: {e}"))?;
    let c: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/terramechanics_constants.json"
    ))
    .map_err(|e| format!("terramechanics_constants.json: {e}"))?;
    let f = |k: &str| num(&c[k], k);
    let (reg, base) = stewie_physics::soil::bundled();
    let b = reg
        .get(body)
        .ok_or_else(|| format!("the body registry has no {body:?}"))?;
    Ok(Setup {
        vehicle: Vehicle::from_profile(&profile),
        soil: SoilParams {
            k_c: f("k_c")?,
            k_phi: f("k_phi")?,
            n: f("n_sinkage")?,
            cohesion_pa: f("cohesion")?,
            phi_rad: f("phi_rad")?,
            k_shear_m: f("k_shear")?,
            slip_c1: f("slip_c1")?,
            slip_c2: f("slip_c2")?,
            rho_surface: f("rho_surface")?,
            rho_deep: f("rho_deep")?,
            analog: false,
        },
        material: None,
        regolith: Regolith::new(b.bulk_density.ok_or("the body has no bulk density")?, &base),
        gravity_ms2: b.g,
        v_max: profile.drive_speed_ms.value,
        tile_base_cells: 4,
        fine_cell_m: None,
    })
}

/// The reported figures for `drum` (`small` or `medium`: the IPEx drums) with the planner file at `planner`.
///
/// # Errors
/// Another drum; a planner file that is unreadable, of another schema, or missing a value.
pub fn production_calib(drum: &str, planner: &Path) -> Result<Calib, String> {
    if !matches!(drum, "small" | "medium") {
        return Err("IPEx runtime requires a small or medium drum".to_owned());
    }
    let profile: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/rover_ipex.json"
    ))
    .map_err(|e| format!("rover_ipex.json: {e}"))?;
    let report: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/plan_report.json"
    ))
    .map_err(|e| format!("plan_report.json: {e}"))?;
    let at = |e: String| format!("{}: {e}", planner.display());
    let p: Value = serde_json::from_slice(&std::fs::read(planner).map_err(|e| at(e.to_string()))?)
        .map_err(|e| at(e.to_string()))?;
    if p["schema"] != "stewie.planner-params/v1" {
        return Err(at("schema is not stewie.planner-params/v1".to_owned()));
    }
    let pv = |k: &str| num(&p[k]["value"], &format!("{k}.value")).map_err(at);
    let d = &profile["drums"][drum];
    Ok(Calib {
        drum: Drum {
            width_m: num(&d["width_m"]["value"], "drum width_m")?,
            capacity_kg: num(&d["capacity_kg"]["value"], "drum capacity_kg")?,
            scoop_height_m: num(&d["scoop_height_m"]["value"], "drum scoop_height_m")?,
        },
        max_cut_depth_frac: num(
            &profile["max_cut_depth_frac"]["value"],
            "max_cut_depth_frac",
        )?,
        dig_energy_per_kg: pv("ipex_dig_j_per_kg")?,
        fdc_baseline_a: pv("fdc_baseline_a")?,
        fdc_slope_a_per_kg: pv("fdc_slope_a_per_kg")?,
        bands: ErrorBands {
            mpe_all: num(&report["fdc_mpe_all"], "fdc_mpe_all")?,
            mpe_half_full: num(&report["fdc_mpe_half_full"], "fdc_mpe_half_full")?,
        },
    })
}
