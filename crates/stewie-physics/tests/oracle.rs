//! stewie-physics against the Python oracle `terramechanics_cases` (`stewie_forge` terramechanics and bearing,
//! `stewie.physics` slip, `body_params`) to 1e-9 relative. The input grid is synthetic (labelled in the
//! fixture); the expected outputs are the Python implementation's.

use serde_json::Value;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_physics::{PhysicsError, bearing, terra};

fn fx() -> Value {
    stewie_oracle::load("terramechanics_cases").unwrap().payload
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

#[track_caller]
fn close(got: f64, want: f64, what: &str) {
    let tol = 1e-9 * want.abs().max(1e-12);
    assert!((got - want).abs() <= tol, "{what}: {got} vs {want}");
}

fn params(name: &str) -> SoilParams {
    let (reg, base) = bundled();
    SoilParams::for_body(&reg, &base, name, false).unwrap()
}

#[test]
fn every_body_gets_the_python_parameter_set_and_microgravity_is_refused() {
    let fx = fx();
    let (reg, base) = bundled();
    for (name, b) in fx["bodies"].as_object().unwrap() {
        let analog = b["analog"].as_bool().unwrap();
        if analog {
            assert!(matches!(
                SoilParams::for_body(&reg, &base, name, false),
                Err(PhysicsError::OutOfRegime { .. })
            ));
        }
        let p = SoilParams::for_body(&reg, &base, name, analog).unwrap();
        let w = &b["params"];
        for (got, key) in [
            (p.k_c, "k_c"),
            (p.k_phi, "k_phi"),
            (p.n, "n_sinkage"),
            (p.cohesion_pa, "cohesion"),
            (p.phi_rad, "phi_rad"),
            (p.k_shear_m, "k_shear"),
            (p.slip_c1, "slip_c1"),
            (p.slip_c2, "slip_c2"),
            (p.rho_surface, "rho_surface"),
            (p.rho_deep, "rho_deep"),
        ] {
            close(got, f(&w[key]), &format!("{name}.{key}"));
        }
        assert_eq!(p.analog, analog || name == "ceres", "{name} analog flag");
    }
    assert!(matches!(
        SoilParams::for_body(&reg, &base, "pluto", true),
        Err(PhysicsError::UnknownBody(_))
    ));
}

#[test]
fn sinkage_density_and_slip_multiplier_match() {
    let fx = fx();
    let c = &fx["cases"];
    for e in c["bekker"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        let got =
            terra::bekker_sinkage(f(&e["pressure_pa"]), f(&e["b_m"]), &p, f(&e["stiffening"]))
                .unwrap();
        close(got, f(&e["z_m"]), "bekker");
    }
    for e in c["contact"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        let got = terra::contact_static_sinkage(
            f(&e["load_n"]),
            f(&e["len_m"]),
            f(&e["width_m"]),
            e["density"].as_f64(),
            &p,
        )
        .unwrap();
        close(got, f(&e["z_m"]), "contact");
    }
    for e in c["density_factor"].as_array().unwrap() {
        let got = terra::sinkage_to_density_factor(f(&e["z_m"]), f(&e["thickness_m"]));
        close(got, f(&e["f"]), "density factor");
    }
    for e in c["slip_multiplier"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        close(
            terra::slip_sinkage_multiplier(f(&e["slip"]), &p),
            f(&e["m"]),
            "multiplier",
        );
    }
    assert!(terra::bekker_sinkage(10.0, 0.0, &params("moon"), 1.0).is_err());
}

#[test]
fn traction_thrust_slip_and_resistance_match() {
    let fx = fx();
    let c = &fx["cases"];
    for e in c["traction"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        close(
            terra::traction_budget(f(&e["normal_n"]), f(&e["area_m2"]), &p),
            f(&e["h_max_n"]),
            "traction",
        );
    }
    for e in c["thrust"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        let got =
            terra::developed_thrust(f(&e["slip"]), f(&e["h_max_n"]), f(&e["len_m"]), p.k_shear_m);
        close(got, f(&e["h_n"]), "thrust");
    }
    for e in c["slip_for_demand"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        let (s, ent) = terra::slip_for_demand(
            f(&e["demand_n"]),
            f(&e["h_max_n"]),
            f(&e["len_m"]),
            p.k_shear_m,
        );
        close(s, f(&e["slip"]), "slip");
        assert_eq!(ent, e["entrapped"].as_bool().unwrap());
    }
    for e in c["resistance"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        close(
            terra::compaction_resistance(f(&e["z_m"]), f(&e["width_m"]), &p),
            f(&e["r_n"]),
            "resistance",
        );
    }
}

fn case(e: &Value, slope_rad: f64, weight_n: f64) -> terra::DriveCase {
    terra::DriveCase {
        total_weight_n: weight_n,
        slope_rad,
        n_wheels: 4,
        contact_len_m: 0.10,
        contact_width_m: 0.18,
        density: e["density"].as_f64(),
        demand_frac: e["demand_frac"].as_f64().unwrap_or(1.0),
        extra_demand_n: e["extra_n"].as_f64().unwrap_or(0.0),
        s_entrap: 0.95,
        z_entrap_m: 0.36,
    }
}

#[test]
fn slip_sinkage_equilibrium_and_drive_power_match_in_both_regimes() {
    let fx = fx();
    let c = &fx["cases"];
    let mut entrapped = 0;
    for e in c["equilibrium"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        let dc = case(e, f(&e["slope_deg"]).to_radians(), f(&e["weight_n"]));
        let q = terra::slip_sinkage_equilibrium(&dc, &p).unwrap();
        for (got, key) in [
            (q.slip, "slip"),
            (q.sinkage_m, "sinkage_m"),
            (q.static_sinkage_m, "static_sinkage_m"),
            (q.resistance_n, "resistance_n"),
            (q.demand_n, "demand_n"),
            (q.budget_n, "budget_n"),
        ] {
            close(got, f(&e[key]), key);
        }
        assert_eq!(q.entrapped, e["entrapped"].as_bool().unwrap(), "{e}");
        assert_eq!(u64::from(q.iters), e["iters"].as_u64().unwrap(), "{e}");
        entrapped += usize::from(q.entrapped);
    }
    assert!(entrapped > 10, "runaway cases exercised: {entrapped}");
    for e in c["drive_power"].as_array().unwrap() {
        let p = params(e["body"].as_str().unwrap());
        let dc = case(e, f(&e["slope_deg"]).to_radians(), 30.0 * 1.62);
        let d = terra::bekker_drive_power(&dc, 0.3, 0.5, &p).unwrap();
        close(d.drive_power_w, f(&e["drive_power_w"]), "power");
        close(d.tractive_n, f(&e["tractive_n"]), "tractive");
        assert_eq!(d.entrapped, e["entrapped"].as_bool().unwrap());
    }
}

#[test]
fn bearing_capacity_matches() {
    let fx = fx();
    for e in fx["cases"]["bearing"].as_array().unwrap() {
        let phi = f(&e["phi_deg"]).to_radians();
        let (nc, nq, ng) = bearing::factors(phi);
        let w = e["factors"].as_array().unwrap();
        close(nc, f(&w[0]), "Nc");
        close(nq, f(&w[1]), "Nq");
        close(ng, f(&w[2]), "Ngamma");
        let args = (
            f(&e["c_pa"]),
            phi,
            f(&e["gamma_n_m3"]),
            f(&e["width_m"]),
            f(&e["depth_m"]),
        );
        close(
            bearing::ultimate_pa(args.0, args.1, args.2, args.3, args.4),
            f(&e["q_ult_pa"]),
            "q_ult",
        );
        close(
            bearing::allowable_pa(args.0, args.1, args.2, args.3, args.4, 3.0),
            f(&e["q_allow_pa"]),
            "q_allow",
        );
    }
}
