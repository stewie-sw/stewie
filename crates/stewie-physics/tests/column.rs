//! `ColumnState` against the Python oracle `column_ops` (a real 32x32 Haworth crop through flatten, dump,
//! deposit, cut, fill and sinter), plus the mass invariant over seeded random operation sequences
//! (synthetic masks and amounts, labelled) and the construction domain checks.

use serde_json::Value;
use stewie_physics::column::{ColumnState, Fields, Regolith};
use stewie_physics::soil::bundled;

fn regolith() -> Regolith {
    let (reg, base) = bundled();
    Regolith::new(reg["moon"].bulk_density.unwrap(), &base)
}

fn fx() -> Value {
    stewie_oracle::load("column_ops").unwrap().payload
}

fn vf(v: &Value) -> Vec<f64> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_f64().unwrap())
        .collect()
}

#[allow(clippy::cast_possible_truncation)]
fn vu8(v: &Value) -> Vec<u8> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_u64().unwrap() as u8)
        .collect()
}

#[track_caller]
fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

#[allow(clippy::cast_possible_truncation)]
fn initial(p: &Value) -> ColumnState {
    let i = &p["initial"];
    ColumnState::new(
        p["width"].as_u64().unwrap() as usize,
        p["height"].as_u64().unwrap() as usize,
        p["cell_m"].as_f64().unwrap(),
        Fields {
            mass_areal: vf(&i["mass_areal"]),
            density: vf(&i["density"]),
            state_label: vu8(&i["state_label"]),
            disturbance: vf(&i["disturbance"]),
            datum: vf(&i["datum"]),
            ice: None,
        },
        0.0,
        &regolith(),
    )
    .unwrap()
}

#[allow(clippy::cast_possible_truncation)]
fn rect(cs: &ColumnState, r: &Value) -> Vec<bool> {
    let r: Vec<usize> = r
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_u64().unwrap() as usize)
        .collect();
    (0..cs.width() * cs.height())
        .map(|i| {
            let (row, col) = (i / cs.width(), i % cs.width());
            (r[0]..r[1]).contains(&row) && (r[2]..r[3]).contains(&col)
        })
        .collect()
}

#[test]
fn the_real_crop_sequence_matches_the_oracle_step_by_step() {
    let p = fx();
    let mut cs = initial(&p);
    let n = cs.width() * cs.height();
    let start = cs.total_mass();
    for s in p["steps"].as_array().unwrap() {
        let m = rect(&cs, &s["rect"]);
        let f = |k: &str| s[k].as_f64().unwrap();
        let ret = match s["op"].as_str().unwrap() {
            "flatten" => {
                let (kg, hi) = cs.flatten_to_level(&m, f("target_m")).unwrap();
                assert_eq!(
                    hi.iter().filter(|&&b| b).count() as u64,
                    s["cut_cells"].as_u64().unwrap()
                );
                kg
            }
            "dump" => cs.dump_from_inventory(&m, f("kg"), f("spoil")).unwrap(),
            "deposit" => cs
                .deposit_field(&m, &vec![f("kg_m2"); n], f("spoil"))
                .unwrap(),
            "cut" => cs.cut_to_inventory(&m, &vec![f("kg_m2"); n]).unwrap(),
            "fill" => cs
                .fill_toward(
                    &m,
                    &vec![f("target_m"); n],
                    Some(f("max_lift_m")),
                    f("spoil"),
                )
                .unwrap(),
            "sinter" => cs.sinter(&m, f("density")).unwrap(),
            other => panic!("unknown op {other}"),
        };
        assert!(
            ret > 0.0,
            "{} moved nothing: the step would prove nothing",
            s["op"]
        );
        close(ret, f("ret"), s["op"].as_str().unwrap());
        close(cs.total_mass(), f("total_kg"), "total mass");
        close(cs.total_mass(), start, "conserved");
        cs.check_invariants().unwrap();
    }
    let fin = &p["final"];
    let got = cs.fields();
    for (g, w, k) in [
        (&got.mass_areal, vf(&fin["mass_areal"]), "mass"),
        (&got.density, vf(&fin["density"]), "density"),
        (&got.disturbance, vf(&fin["disturbance"]), "disturbance"),
        (&cs.derive_height(), vf(&fin["height"]), "height"),
    ] {
        for (a, b) in g.iter().zip(&w) {
            close(*a, *b, k);
        }
    }
    assert_eq!(got.state_label, vu8(&fin["state_label"]));
    close(
        cs.drum_inventory(),
        fin["drum_kg"].as_f64().unwrap(),
        "drum",
    );
    let lifted: Vec<f64> = cs.derive_height().iter().map(|h| h + 0.01).collect();
    let loose = cs.loose_mask(&regolith());
    let want: Vec<bool> = p["loose"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_bool().unwrap())
        .collect();
    assert_eq!(loose, want);
    cs.set_height_via_mass(&lifted).unwrap();
    for (a, b) in cs
        .fields()
        .mass_areal
        .iter()
        .zip(vf(&p["after_set_height_mass"]))
    {
        close(*a, b, "set_height_via_mass");
    }
}

/// splitmix64: synthetic operation sequences only.
struct Rng(u64);

impl Rng {
    #[allow(clippy::cast_precision_loss)]
    fn unit(&mut self) -> f64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        (z ^ (z >> 31)) as f64 / u64::MAX as f64
    }
}

#[test]
#[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
fn total_mass_is_invariant_over_random_operation_sequences() {
    let rg = regolith();
    let fixture = fx();
    for seed in 0..20u64 {
        let mut cs = initial(&fixture);
        let n = cs.width() * cs.height();
        let start = cs.total_mass();
        let mut rng = Rng(seed);
        let mut moved = 0.0;
        for _ in 0..100 {
            let mask: Vec<bool> = (0..n).map(|_| rng.unit() < 0.3).collect();
            let amount: Vec<f64> = (0..n).map(|_| 400.0 * rng.unit()).collect();
            let kg = match (rng.unit() * 6.0) as u32 {
                0 => cs.cut_to_inventory(&mask, &amount).unwrap(),
                1 => cs
                    .dump_from_inventory(&mask, 1e6 * rng.unit(), rg.rho_spoil)
                    .unwrap(),
                2 => cs.deposit_field(&mask, &amount, rg.rho_spoil).unwrap(),
                3 => {
                    let h = cs.derive_height();
                    let t: Vec<f64> = h.iter().map(|x| x + 0.3 * rng.unit()).collect();
                    cs.fill_toward(&mask, &t, Some(0.05), rg.rho_spoil).unwrap()
                }
                4 => {
                    cs.flatten_to_level(&mask, cs.derive_height()[0] - 0.1)
                        .unwrap()
                        .0
                }
                _ => cs.sinter(&mask, rg.rho_sintered).unwrap(),
            };
            moved += kg;
            close(cs.total_mass(), start, &format!("seed {seed}"));
            cs.check_invariants().unwrap();
        }
        assert!(moved > 0.0, "seed {seed} moved nothing");
    }
}

#[test]
fn out_of_domain_fields_and_bad_transfers_are_refused() {
    let r = regolith();
    let p = fx();
    let good = initial(&p);
    let mk = |edit: &dyn Fn(&mut Fields)| {
        let mut f = good.fields().clone();
        edit(&mut f);
        ColumnState::new(good.width(), good.height(), good.cell_m(), f, 0.0, &r)
    };
    assert!(mk(&|f| f.mass_areal[3] = -1.0).is_err());
    assert!(mk(&|f| f.density[3] = r.rho_grain + 1.0).is_err());
    assert!(mk(&|f| f.density[3] = 0.0).is_err());
    assert!(mk(&|f| f.disturbance[3] = 1.5).is_err());
    assert!(mk(&|f| f.datum[3] = f64::NAN).is_err());
    assert!(mk(&|f| f.state_label[3] = 9).is_err());
    assert!(mk(&|f| f.ice = Some(vec![r.w_ice_max * 2.0; f.datum.len()])).is_err());
    assert!(mk(&|f| f.mass_areal.pop().map_or((), |_| ())).is_err());
    let mut cs = good.clone();
    let n = cs.width() * cs.height();
    let all = vec![true; n];
    assert!(cs.cut_to_inventory(&all, &vec![-1.0; n]).is_err());
    assert!(cs.dump_from_inventory(&all, f64::NAN, r.rho_spoil).is_err());
    assert!(cs.deposit_field(&all, &vec![1.0; n], 0.0).is_err());
    assert!(cs.cut_to_inventory(&all[1..], &vec![1.0; n - 1]).is_err());
    assert_eq!(cs, good, "a refused transfer leaves the state untouched");
    let u = ColumnState::uniform(4, 3, 0.5, &r).unwrap();
    close(u.derive_height()[0], r.z_t_m, "uniform layer is z_t thick");
}
