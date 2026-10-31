//! Excavation (McKyes/Reece FEE) and the material model against the Python oracle `excavation_cases`, to
//! 1e-9 relative. The input grid is synthetic (labelled in the fixture). The material formula is checked
//! with the Python's own endpoints; the production endpoints come from the registry (D-R50).

use serde_json::Value;
use stewie_physics::excavation::{Dig, factors, solve};
use stewie_physics::material::MaterialModel;
use stewie_physics::soil::{SoilParams, bundled};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

#[track_caller]
fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1e-12),
        "{what}: {got} vs {want}"
    );
}

#[test]
fn n_factors_match_and_invalid_wedges_are_refused() {
    let fx = stewie_oracle::load("excavation_cases").unwrap().payload;
    let mut invalid = 0;
    for e in fx["factors"].as_array().unwrap() {
        let got = factors(
            f(&e["phi_deg"]).to_radians(),
            f(&e["beta_deg"]).to_radians(),
            f(&e["rake_deg"]).to_radians(),
            f(&e["delta_rad"]),
        );
        if let Some(w) = e["n"].as_array() {
            let (ng, nc, nq) = got.unwrap();
            close(ng, f(&w[0]), "N_gamma");
            close(nc, f(&w[1]), "N_c");
            close(nq, f(&w[2]), "N_q");
            close(nq, 2.0 * ng, "N_q == 2 N_gamma");
        } else {
            assert!(got.is_err(), "{e}");
            invalid += 1;
        }
    }
    assert!(invalid > 10, "invalid wedges exercised: {invalid}");
}

#[test]
fn least_draft_solves_match() {
    let fx = stewie_oracle::load("excavation_cases").unwrap().payload;
    let n_beta = u32::try_from(fx["n_beta"].as_u64().unwrap()).unwrap();
    for e in fx["reports"].as_array().unwrap() {
        let r = solve(
            &Dig {
                depth_m: f(&e["depth_m"]),
                width_m: f(&e["width_m"]),
                cohesion_pa: f(&e["c_pa"]),
                bulk_density_kg_m3: f(&e["rho"]),
                gravity_ms2: f(&e["g"]),
                phi_rad: f(&e["phi_deg"]).to_radians(),
                rake_rad: f(&e["rake_rad"]),
                soil_tool_friction_rad: f(&e["delta_rad"]),
                surcharge_pa: f(&e["q_pa"]),
            },
            n_beta,
        )
        .unwrap();
        close(r.draft_n, f(&e["draft_n"]), "draft");
        close(r.beta_rad, f(&e["beta_rad"]), "beta");
        close(r.n_gamma, f(&e["n_gamma"]), "N_gamma");
        close(r.n_c, f(&e["n_c"]), "N_c");
        close(
            r.specific_energy_j_per_kg,
            f(&e["specific_energy_j_per_kg"]),
            "energy",
        );
    }
    let ok = Dig {
        depth_m: 0.1,
        width_m: 0.5,
        cohesion_pa: 170.0,
        bulk_density_kg_m3: 1750.0,
        gravity_ms2: 1.62,
        phi_rad: 37f64.to_radians(),
        rake_rad: 45f64.to_radians(),
        soil_tool_friction_rad: 18.5f64.to_radians(),
        surcharge_pa: 0.0,
    };
    for bad in [
        Dig { depth_m: 0.0, ..ok },
        Dig {
            bulk_density_kg_m3: -1.0,
            ..ok
        },
        Dig { phi_rad: 1.6, ..ok },
        Dig {
            cohesion_pa: -1.0,
            ..ok
        },
    ] {
        assert!(solve(&bad, n_beta).is_err(), "{bad:?}");
    }
}

#[test]
fn material_formula_matches_and_production_uses_the_registry() {
    let fx = stewie_oracle::load("excavation_cases").unwrap().payload;
    let m = &fx["material"];
    let py = MaterialModel {
        rho_surface: f(&m["rho_surface"]),
        rho_deep: f(&m["rho_deep"]),
        phi_loose_deg: f(&m["phi_loose_deg"]),
        phi_dense_deg: f(&m["phi_dense_deg"]),
        cohesion_loose_pa: f(&m["cohesion_loose_pa"]),
        cohesion_dense_pa: f(&m["cohesion_dense_pa"]),
    };
    for (k, rho) in m["density"].as_array().unwrap().iter().map(f).enumerate() {
        let (phi, c) = py.cell_strength(rho);
        close(phi, f(&m["strength"][k][0]), "phi");
        close(c, f(&m["strength"][k][1]), "cohesion");
        let cell = py.cell(rho, f(&m["normal_load_n"]), f(&m["contact_area_m2"]));
        for (got, key) in [
            (cell.relative_density, "relative_density"),
            (cell.friction_deg, "friction_deg"),
            (cell.cohesion_pa, "cohesion_pa"),
            (cell.traction_capacity_n, "traction_capacity_n"),
            (cell.slip_susceptibility, "slip_susceptibility"),
            (cell.cut_difficulty, "cut_difficulty"),
        ] {
            let want = f(&m[key][k]);
            assert!(
                (got - want).abs() <= 1e-9 * want.abs().max(1.0),
                "{key}[{k}]: {got} vs {want}"
            );
        }
    }
    let (reg, base) = bundled();
    let moon = MaterialModel::for_soil(
        &SoilParams::for_body(&reg, &base, "moon", false).unwrap(),
        &base,
    );
    close(
        moon.phi_loose_deg,
        35.0,
        "registry loose friction (D-R50), not constants.PHI's 37",
    );
    close(moon.phi_dense_deg, 50.0, "baseline dense friction");
    close(moon.cohesion_dense_pa, 1000.0, "baseline dense cohesion");
}
