//! Release binding (RW-33f, D-R100) on a REAL plan: a mission over the real Haworth route window is planned, lowered
//! to its IR and released against real world-model identities (the route window's heights, an observed twin over
//! them, a Terrain Memory for the site). Execution is allowed only in the identical context: another site, other
//! terrain, a changed world model, a tampered IR, a moved keep-out, a changed constraint or physics configuration is
//! refused, naming the field. An infeasible IR is never released; there is no IR without real terrain (#3). The
//! small-order layout is a SYNTHETIC placement on the real terrain (labelled in the oracle `plan_ir_cases`).

use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use stewie_contracts::fleet::Fleet;
use stewie_physics::soil::SoilParams;
use stewie_plan::assemble::{PlanConfig, plan_and_simulate};
use stewie_plan::balance::Profile;
use stewie_plan::ir::plan_ir;
use stewie_plan::mission::{Keepout, Mission, Registries, mission_from_value};
use stewie_plan::release::{Binding, bind, check};
use stewie_plan::trips::{BuildInputs, PlannerParams, SlipModel, context};
use stewie_traverse::route::Dem;
use stewie_twin::terrain_memory::TerrainMemory;
use stewie_twin::twin_store::TwinStore;

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::new(), |mut s, b| {
            use std::fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        })
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

/// A named change to apply to a copy.
type Drift<T> = (&'static str, fn(&mut T));

struct World {
    heights: Vec<f64>,
    side: usize,
    cell_m: f64,
    origin: (f64, f64),
    fleet: Fleet,
    reg_bodies: stewie_contracts::body::BodyRegistry,
    params: PlannerParams,
    pp_json: Value,
    profile: Profile,
    rho: f64,
    slip: SlipModel,
    soil: SoilParams,
    cases: Value,
}

fn world() -> World {
    let tc = stewie_oracle::load("trips_cases").unwrap().payload;
    let heights: Vec<f64> = stewie_oracle::load("route_cases").unwrap().payload["z"]
        .as_array()
        .unwrap()
        .iter()
        .map(f)
        .collect();
    let bv: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let base: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/soil_baseline.json"
    ))
    .unwrap();
    let rho = f(&bv["moon"]["bulk_density"]);
    let pp = &tc["params"];
    let sl = &tc["slip"];
    let main = tc["missions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|m| m["name"] == "haul_two_pairs")
        .unwrap()
        .clone();
    World {
        side: usize::try_from(tc["window"][2].as_u64().unwrap()).unwrap(),
        cell_m: f(&tc["cell_m"]),
        origin: (f(&tc["origin"][0]), f(&tc["origin"][1])),
        heights,
        fleet: serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json"))
            .unwrap(),
        reg_bodies: serde_json::from_str(include_str!(
            "../../stewie-contracts/fixtures/bodies.json"
        ))
        .unwrap(),
        params: PlannerParams {
            reserve_frac: f(&pp["reserve_frac"]),
            charge_w: f(&pp["charge_w"]),
            dig_rate_kg_s: f(&pp["dig_rate_kg_s"]),
            drive_speed_ms: f(&pp["drive_speed_ms"]),
            rolling_resistance: f(&pp["rolling_resistance"]),
            drivetrain_efficiency: f(&pp["drivetrain_efficiency"]),
            gravity_ms2: f(&pp["gravity_ms2"]),
        },
        pp_json: pp.clone(),
        profile: Profile {
            rho_surface: rho,
            rho_deep: f(&base["rho_deep"]["value"]),
            z_t_m: f(&base["z_t_m"]["value"]),
        },
        rho,
        slip: SlipModel {
            n_wheels: u32::try_from(sl["n_wheels"].as_u64().unwrap()).unwrap(),
            contact_len_m: f(&sl["contact_len_m"]),
            contact_width_m: f(&sl["contact_width_m"]),
            z_entrap_m: f(&sl["z_entrap_m"]),
        },
        soil: soil(&main["soil"]),
        cases: stewie_oracle::load("plan_ir_cases").unwrap().payload["cases"].clone(),
    }
}

impl World {
    fn dem(&self) -> Dem<'_> {
        Dem {
            z: &self.heights,
            width: self.side,
            height: self.side,
            cell_m: self.cell_m,
            origin: self.origin,
        }
    }

    fn mission(&self, name: &str) -> Mission {
        let reg = Registries::new(&self.reg_bodies, &self.fleet);
        let c = self
            .cases
            .as_array()
            .unwrap()
            .iter()
            .find(|c| c["name"] == name)
            .unwrap();
        mission_from_value(&c["payload"], &reg).unwrap()
    }

    fn ir(&self, m: &Mission, dem: Dem<'_>) -> Result<Value, String> {
        let inp = BuildInputs {
            dem,
            max_traverse_slope_deg: 25.0,
            body_density: self.rho,
            profile: &self.profile,
            soil: &self.soil,
            slip: &self.slip,
            params: &self.params,
        };
        let cfg = PlanConfig {
            algorithm: "nearest",
            objective: "time",
            vehicles: 1,
            idle_power_w: 0.0,
            reallocate_stranded: true,
        };
        let plan = plan_and_simulate(m, &self.fleet, &inp, &cfg)?;
        let ctx = context(m, &self.fleet, &self.params)?;
        plan_ir(m, &plan, &ctx, dem, 25.0)
    }

    /// The live context: the terrain's own bytes, an observed twin over it, the site's Terrain Memory.
    fn binding(&self, twin: &TwinStore, memory: &TerrainMemory) -> Binding {
        let bytes: Vec<u8> = self.heights.iter().flat_map(|h| h.to_le_bytes()).collect();
        let (twin_version, twin_hash) = twin.identity();
        Binding {
            site_id: "haworth".to_owned(),
            dem_sha256: hex(&bytes),
            terrain_memory_version: memory.version(),
            terrain_memory_head: memory
                .chain()
                .last()
                .map_or_else(|| "genesis".to_owned(), |r| r.hash.clone()),
            twin_version,
            twin_hash,
            physics_backend_id: "tier2_numpy".to_owned(),
            physics_config_sha256: hex(stewie_twin::pyjson::dumps(&self.pp_json)
                .unwrap()
                .as_bytes()),
        }
    }
}

#[test]
#[allow(clippy::too_many_lines)] // one released plan, every way its context can drift
fn a_release_runs_only_in_the_context_it_was_bound_to() {
    let w = world();
    let m = w.mission("small_orders");
    let ir = w.ir(&m, w.dem()).unwrap();
    assert_eq!(
        ir["feasible"],
        Value::Bool(true),
        "vacuity: a releasable plan"
    );
    let twin = TwinStore::new(w.heights.clone(), w.side, w.side, w.cell_m).unwrap();
    let memory = TerrainMemory::new("haworth", w.side, w.side, w.cell_m, w.origin).unwrap();
    let live = w.binding(&twin, &memory);
    let rel = bind(&m, &ir, live.clone()).unwrap();

    // the contract: the released document validates against its schema, and a broken one does not
    let schema: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/schema/release.schema.json"
    ))
    .unwrap();
    let v = jsonschema::validator_for(&schema).unwrap();
    let doc = rel.to_value();
    assert!(
        v.is_valid(&doc),
        "{:?}",
        v.iter_errors(&doc)
            .map(|e| e.to_string())
            .collect::<Vec<_>>()
    );
    let mut broken = doc.clone();
    broken["binding"]["dem_sha256"] = json!("not-a-hash");
    assert!(!v.is_valid(&broken));

    // the identical context runs
    assert_eq!(check(&rel, &m, &ir, &live), Ok(()));

    // every bound identity, changed alone, is refused by name
    let drift: [Drift<Binding>; 8] = [
        ("site_id", |b| b.site_id = "shackleton_rim".into()),
        ("dem_sha256", |b| b.dem_sha256 = "0".repeat(64)),
        ("terrain_memory_version", |b| b.terrain_memory_version += 1),
        ("terrain_memory_head", |b| {
            b.terrain_memory_head = "f".repeat(64);
        }),
        ("twin_version", |b| b.twin_version += 1),
        ("twin_hash", |b| b.twin_hash = "e".repeat(64)),
        ("physics_backend_id", |b| {
            b.physics_backend_id = "chrono".into();
        }),
        ("physics_config_sha256", |b| {
            b.physics_config_sha256 = "1".repeat(64);
        }),
    ];
    for (field, change) in drift {
        let mut other = live.clone();
        change(&mut other);
        assert_eq!(
            check(&rel, &m, &ir, &other),
            Err(vec![field.to_owned()]),
            "{field}"
        );
    }

    // a real world-model change: an observed patch moves the twin's version and hash
    let mut observed = twin.clone();
    observed
        .apply_patch(
            &vec![vec![w.heights[0] + 0.25; 2]; 2],
            (0, 0),
            "rover stereo pass",
        )
        .unwrap();
    let after = w.binding(&observed, &memory);
    let err = check(&rel, &m, &ir, &after).unwrap_err();
    assert_eq!(err, vec!["twin_hash".to_owned(), "twin_version".to_owned()]);

    // a tampered IR: one action's expected energy edited
    let mut tampered = ir.clone();
    tampered["actions"][1]["expect"]["energy_J"] = json!(1.0);
    assert_eq!(
        check(&rel, &m, &tampered, &live),
        Err(vec!["ir_sha256".to_owned()])
    );

    // another mission's plan cannot run under this release
    let other_m = w.mission("deficit");
    let other_ir = w.ir(&other_m, w.dem()).unwrap();
    assert_eq!(
        other_ir["feasible"],
        Value::Bool(true),
        "vacuity: the other plan is releasable"
    );
    let err = check(&rel, &other_m, &other_ir, &live).unwrap_err();
    assert!(
        err.contains(&"plan_id".to_owned()) && err.contains(&"ir_sha256".to_owned()),
        "{err:?}"
    );

    // a keep-out added after release, and a changed budget
    let mut fenced = m.clone();
    fenced.keepouts.push(Keepout::Circle {
        x: 500.0,
        y: 500.0,
        r: 1.0,
    });
    assert_eq!(
        check(&rel, &fenced, &ir, &live),
        Err(vec!["keepouts_sha256".to_owned()])
    );
    let constraint_drift: [Drift<Mission>; 5] = [
        ("budget", |m| {
            m.objective_constraints.insert("max_time_s".into(), 1.0);
        }),
        ("precedence", |m| m.precedence.clear()),
        ("window", |m| {
            m.mission_windows.insert("work".into(), vec![(0.0, 3600.0)]);
        }),
        ("vehicle", |m| m.vehicle = "rassor2".into()),
        ("charger capacity", |m| m.charger_capacity += 1),
    ];
    assert!(
        !m.precedence.is_empty(),
        "vacuity: the released mission has precedence to drop"
    );
    for (what, change) in constraint_drift {
        let mut changed = m.clone();
        change(&mut changed);
        assert_eq!(
            check(&rel, &changed, &ir, &live),
            Err(vec!["constraints_sha256".to_owned()]),
            "{what}"
        );
    }

    // a forged release id
    let mut forged = rel.clone();
    forged.binding.site_id = "shackleton_rim".into();
    let err = check(&forged, &m, &ir, &live).unwrap_err();
    assert!(
        err.contains(&"release_id".to_owned()) && err.contains(&"site_id".to_owned()),
        "{err:?}"
    );

    // an infeasible plan is never released
    let walled = w.mission("blocked_waypoint");
    let blocked = w.ir(&walled, w.dem()).unwrap();
    assert_eq!(
        blocked["feasible"],
        Value::Bool(false),
        "vacuity: a blocked plan"
    );
    assert!(bind(&walled, &blocked, live.clone()).is_err());
}

#[test]
fn there_is_no_plan_ir_without_real_terrain() {
    let w = world();
    let m = w.mission("small_orders");
    let empty: Vec<f64> = Vec::new();
    let none = Dem {
        z: &empty,
        width: 0,
        height: 0,
        cell_m: w.cell_m,
        origin: w.origin,
    };
    assert!(w.ir(&m, none).is_err(), "an empty DEM gives no IR");
    let mut holed = w.heights.clone();
    holed[w.side * 10 + 10] = f64::NAN;
    let hole = Dem {
        z: &holed,
        ..w.dem()
    };
    let err = plan_ir(
        &m,
        &{
            let inp = BuildInputs {
                dem: w.dem(),
                max_traverse_slope_deg: 25.0,
                body_density: w.rho,
                profile: &w.profile,
                soil: &w.soil,
                slip: &w.slip,
                params: &w.params,
            };
            let cfg = PlanConfig {
                algorithm: "nearest",
                objective: "time",
                vehicles: 1,
                idle_power_w: 0.0,
                reallocate_stranded: true,
            };
            plan_and_simulate(&m, &w.fleet, &inp, &cfg).unwrap()
        },
        &context(&m, &w.fleet, &w.params).unwrap(),
        hole,
        25.0,
    )
    .unwrap_err();
    assert!(err.contains("real terrain"), "{err}");
}
