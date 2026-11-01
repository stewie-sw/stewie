//! The conserved as-built record against the Python oracle `record_cases`, for missions over the REAL Haworth route
//! window (layouts, error envelopes and drum readings SYNTHETIC, labelled in the oracle). Assessment #4: the change
//! Terrain Memory records is the change the physics executed, cell for cell, and its mass is the executed cut.

use serde_json::Value;
use stewie_build::record::{
    DrumBand, EstimateInputs, estimate_moved_regolith, mission_terrain_delta, record_mission,
    volume_evidence,
};
use stewie_contracts::fleet::Fleet;
use stewie_physics::column::Regolith;
use stewie_physics::soil::{SoilParams, bundled};
use stewie_plan::acceptance::{AcceptanceInputs, AcceptanceParams};
use stewie_plan::mission::{Registries, mission_from_value};
use stewie_plan::trips::{PlannerParams, context};
use stewie_traverse::route::Dem;
use stewie_twin::terrain_memory::TerrainMemory;

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

#[track_caller]
fn same(got: &Value, want: &Value, what: &str) {
    match (got, want) {
        (Value::Number(a), Value::Number(b)) => {
            let (a, b) = (a.as_f64().unwrap(), b.as_f64().unwrap());
            assert!(
                (a - b).abs() <= 1e-9 * b.abs().max(1.0),
                "{what}: {a} vs {b}"
            );
        }
        (Value::Object(a), Value::Object(b)) => {
            for (k, v) in b {
                same(&a[k], v, &format!("{what}.{k}"));
            }
            assert_eq!(a.len(), b.len(), "{what} keys");
        }
        _ => assert_eq!(got, want, "{what}"),
    }
}

fn soil(s: &Value) -> SoilParams {
    SoilParams {
        k_c: f(&s["k_c"]),
        k_phi: f(&s["k_phi"]),
        n: f(&s["n_sinkage"]),
        cohesion_pa: f(&s["cohesion"]),
        phi_rad: f(&s["phi_rad"]),
        k_shear_m: f(&s["k_shear"]),
        slip_c1: f(&s["slip_c1"]),
        slip_c2: f(&s["slip_c2"]),
        rho_surface: f(&s["rho_surface"]),
        rho_deep: f(&s["rho_deep"]),
        analog: false,
    }
}

#[test]
#[allow(clippy::too_many_lines, clippy::many_single_char_names)] // setup, then record, memory and evidence
fn the_recorded_change_is_the_executed_change() {
    let fx = stewie_oracle::load("record_cases").unwrap().payload;
    let tc = stewie_oracle::load("trips_cases").unwrap().payload;
    let heights: Vec<f64> = stewie_oracle::load("route_cases").unwrap().payload["z"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    let side = usize::try_from(tc["window"][2].as_u64().unwrap()).unwrap();
    let dem = Dem {
        z: &heights,
        width: side,
        height: side,
        cell_m: f(&tc["cell_m"]),
        origin: (f(&tc["origin"][0]), f(&tc["origin"][1])),
    };
    let fleet: Fleet =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json")).unwrap();
    let bodies: stewie_contracts::body::BodyRegistry =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let reg = Registries::new(&bodies, &fleet);
    let (breg, base) = bundled();
    let rho = breg["moon"].bulk_density.unwrap();
    let regolith = Regolith::new(rho, &base);
    let pp = &tc["params"];
    let params = PlannerParams {
        reserve_frac: f(&pp["reserve_frac"]),
        charge_w: f(&pp["charge_w"]),
        dig_rate_kg_s: f(&pp["dig_rate_kg_s"]),
        drive_speed_ms: f(&pp["drive_speed_ms"]),
        rolling_resistance: f(&pp["rolling_resistance"]),
        drivetrain_efficiency: f(&pp["drivetrain_efficiency"]),
        gravity_ms2: f(&pp["gravity_ms2"]),
    };
    let k = &stewie_oracle::load("acceptance_cases").unwrap().payload["cases"][0]["params"];
    let p = AcceptanceParams {
        cell_m: f(&k["cell_m"]),
        max_cells: usize::try_from(k["max_cells"].as_u64().unwrap()).unwrap(),
        regolith_depth_m: f(&k["regolith_depth_m"]),
        max_slope_deg: f(&k["max_slope_deg"]),
        accept_flatness_tol_m: f(&k["accept_flatness_tol_m"]),
        bearing_load_pa: None,
        bearing_fs: f(&k["bearing_fs"]),
    };
    let dj = &fx["drum"];
    let drum = DrumBand {
        mpe_all: f(&dj["mpe_all"]),
        mpe_with_outliers: f(&dj["mpe_with_outliers"]),
        mpe_half_full: f(&dj["mpe_half_full"]),
        half_full_kg: f(&dj["half_full_kg"]),
    };
    let missions = tc["missions"].as_array().unwrap();
    let main_soil = soil(
        &missions
            .iter()
            .find(|m| m["name"] == "haul_two_pairs")
            .unwrap()["soil"],
    );
    let mut memories: Vec<TerrainMemory> = Vec::new();
    let mut stacked = false;
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let m = mission_from_value(&c["payload"], &reg).unwrap();
        let sp = missions
            .iter()
            .find(|x| x["name"] == name)
            .map_or_else(|| main_soil, |x| soil(&x["soil"]));
        let ctx = context(&m, &fleet, &params).unwrap();
        let ai = AcceptanceInputs {
            body_density: rho,
            regolith: &regolith,
            soil: &sp,
            gravity_ms2: params.gravity_ms2,
            drum_kg: ctx.drum_kg,
            dig_j_per_kg: ctx.dig_j_per_kg,
        };
        let d = mission_terrain_delta(&m, Some(dem), &ai, &p).unwrap();
        for (got, key) in [(d.x0, "x0"), (d.y0, "y0"), (d.cell_m, "cell_m")] {
            same(&got.into(), &c[key], &format!("{name} {key}"));
        }
        assert_eq!(
            (d.rows as u64, d.cols as u64),
            (c["rows"].as_u64().unwrap(), c["cols"].as_u64().unwrap())
        );
        assert!(
            (d.mass_moved_kg - f(&c["mass_moved_kg"])).abs() <= 1e-9 * d.mass_moved_kg.max(1.0),
            "{name} mass"
        );
        let changed: Vec<(usize, f64)> = d
            .delta
            .iter()
            .copied()
            .enumerate()
            .filter(|(_, v)| v.abs() > 1e-12)
            .collect();
        let want = c["delta"].as_array().unwrap();
        assert_eq!(changed.len(), want.len(), "{name} changed cells");
        for ((i, v), w) in changed.iter().zip(want) {
            assert_eq!(*i as u64, w[0].as_u64().unwrap(), "{name} cell index");
            assert!((v - f(&w[1])).abs() <= 1e-9, "{name} cell {i}");
        }
        // the site memory: built as the oracle built it, shared by missions on one cell size
        let mj = &c["memory"];
        let (mrows, mcols) = (
            usize::try_from(mj["rows"].as_u64().unwrap()).unwrap(),
            usize::try_from(mj["cols"].as_u64().unwrap()).unwrap(),
        );
        let morigin = (f(&mj["origin"][0]), f(&mj["origin"][1]));
        let at = memories
            .iter()
            .position(|mm| (mm.cell_area() - d.cell_m * d.cell_m).abs() < 1e-12);
        let i = at.unwrap_or_else(|| {
            memories.push(TerrainMemory::new("haworth", mrows, mcols, d.cell_m, morigin).unwrap());
            memories.len() - 1
        });
        let mem = &mut memories[i];
        let before = mem.cumulative_delta().to_vec();
        let placed = record_mission(mem, &m, &d).unwrap();
        let pj = &c["placement"];
        assert_eq!(
            placed.version,
            pj["version"].as_u64().unwrap(),
            "{name} version"
        );
        assert_eq!(
            placed.placed_cells as u64,
            pj["placed_cells"].as_u64().unwrap(),
            "{name} placed"
        );
        assert_eq!(
            placed.clipped,
            pj["clipped"].as_bool().unwrap(),
            "{name} clipped"
        );
        stacked |= placed.version > 1;
        // assessment #4: what the memory gained is exactly the executed delta, at the mission's offset
        let gained: Vec<f64> = mem
            .cumulative_delta()
            .iter()
            .zip(&before)
            .map(|(a, b)| a - b)
            .collect();
        // the memory's origin is a whole number of cells below the mission's (the oracle's 6-cell rim or more)
        let cells = |v: f64| {
            let n = (v / d.cell_m).round();
            assert!(n >= 0.0, "{name} mission inside the site memory");
            #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
            let u = n as usize;
            u
        };
        let (roff, coff) = (cells(d.y0 - morigin.1), cells(d.x0 - morigin.0));
        for r in 0..d.rows {
            for col in 0..d.cols {
                let g = gained[(r + roff) * mcols + col + coff];
                assert!(
                    (g - d.delta[r * d.cols + col]).abs() <= 1e-12,
                    "{name} recorded cell ({r},{col})"
                );
            }
        }
        // the record keeps the mass to 6 decimals (as the Python's chain does)
        assert!(
            (mem.chain().last().unwrap().mass_moved_kg - d.mass_moved_kg).abs() <= 5e-7,
            "{name} record mass"
        );
        let s = mem.summary();
        let sj = &mj["summary"];
        assert_eq!(
            s.version,
            sj["version"].as_u64().unwrap(),
            "{name} summary version"
        );
        assert_eq!(
            s.cells_changed as u64,
            sj["cells_changed"].as_u64().unwrap(),
            "{name} summary cells"
        );
        same(
            &s.net_volume_m3.into(),
            &sj["net_volume_m3"],
            &format!("{name} net volume"),
        );
        assert_eq!(
            mem.chain().last().unwrap().hash,
            mj["head"].as_str().unwrap(),
            "{name} chain head"
        );
        // the moved-regolith evidence, every envelope the oracle tried
        for (k, e) in c["estimates"].as_array().unwrap().iter().enumerate() {
            let i = &e["inputs"];
            let ei = EstimateInputs {
                density_kg_m3: f(&i["density_kg_m3"]),
                spoil_density_kg_m3: i["spoil_density_kg_m3"].as_f64(),
                height_rmse_m: f(&i["height_rmse_m"]),
                density_frac: f(&i["density_frac"]),
                conserved_mass_kg: i["conserved_mass_kg"].as_f64(),
                drum_inferred_kg: i["drum_inferred_kg"].as_f64(),
            };
            let est = estimate_moved_regolith(&d.base, &d.as_built, d.cell_m, &ei, &drum).unwrap();
            same(&est, &e["estimate"], &format!("{name} estimate {k}"));
            // the contract takes the cut density for fills as well
            let ec = EstimateInputs {
                spoil_density_kg_m3: None,
                ..ei
            };
            let ev = volume_evidence(
                &d.base,
                &d.as_built,
                d.cell_m,
                &ec,
                &drum,
                &format!("wo-{name}"),
                ("conserved:base", "conserved:as_built"),
                &format!("tx-{name}"),
            )
            .unwrap();
            same(&ev, &e["evidence"], &format!("{name} evidence {k}"));
        }
        // with exact conserved surfaces the observed mass is the executed cut (assessment #4)
        assert_eq!(
            c["estimates"][0]["estimate"]["agreement_conserved"],
            Value::Bool(true),
            "{name}"
        );
    }
    assert!(
        stacked,
        "vacuity: a second mission recorded on one site memory"
    );
}
