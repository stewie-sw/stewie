//! The mission trust boundary against the Python oracle `mission_cases`: the three committed sample missions and
//! SYNTHETIC variants (labelled in the oracle). Every payload the Python accepts parses to the same mission here;
//! every payload it refuses is refused. One divergence is deliberate: a coordinate sent as a numeric string, which
//! the Python's `float()` accepted, is refused (numbers must be JSON numbers).

use serde_json::Value;
use stewie_contracts::fleet::Fleet;
use stewie_plan::mission::{Keepout, Mission, OrderKind, Registries, mission_from_value};

const STRICTER: [&str; 1] = ["string_coordinate"];

fn registries() -> Registries {
    let bodies: stewie_contracts::body::BodyRegistry =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    let fleet: Fleet =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/fleet.json")).unwrap();
    Registries::new(&bodies, &fleet)
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn pair(v: &Value) -> (f64, f64) {
    (f(&v[0]), f(&v[1]))
}

fn keepout(k: &Keepout) -> Value {
    match k {
        Keepout::Circle { x, y, r } => serde_json::json!({"x": x, "y": y, "r": r}),
        Keepout::Rect { x0, y0, x1, y1 } => {
            serde_json::json!({"x0": x0, "y0": y0, "x1": x1, "y1": y1})
        }
        Keepout::Polygon(p) => {
            serde_json::json!({"points": p.iter().map(|(x, y)| vec![*x, *y]).collect::<Vec<_>>()})
        }
    }
}

#[track_caller]
fn same(m: &Mission, want: &Value, payload: &Value, tag: &str) {
    assert_eq!(m.name, want["name"].as_str().unwrap(), "{tag} name");
    assert_eq!(m.body, want["body"].as_str().unwrap(), "{tag} body");
    assert_eq!(
        m.vehicle,
        want["vehicle"].as_str().unwrap(),
        "{tag} vehicle"
    );
    let tools: Vec<&str> = want["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|t| t.as_str().unwrap())
        .collect();
    assert_eq!(m.tools, tools, "{tag} tools");
    assert_eq!(m.soil, want["soil"].as_str().unwrap(), "{tag} soil");
    assert_eq!(
        m.physics_backend_id,
        want["physics_backend_id"].as_str().unwrap(),
        "{tag} backend"
    );
    assert_eq!(m.charger, pair(&want["charger"]), "{tag} charger");
    assert_eq!(
        m.charger_capacity,
        want["charger_capacity"].as_u64().unwrap(),
        "{tag} charger capacity"
    );
    assert_eq!(
        m.lander,
        (!want["lander"].is_null()).then(|| pair(&want["lander"])),
        "{tag} lander"
    );
    // fields the Python defaults when absent (a date, the return buffer) are compared when the payload sent them
    if payload.get("date").is_some() {
        assert_eq!(m.date.as_deref(), want["date"].as_str(), "{tag} date");
    } else {
        assert!(m.date.is_none());
    }
    match payload.get("return_buffer_frac") {
        Some(_) => assert_eq!(
            m.return_buffer_frac,
            want["return_buffer_frac"].as_f64(),
            "{tag} return buffer"
        ),
        None => assert!(
            m.return_buffer_frac.is_none(),
            "{tag}: no compiled return buffer"
        ),
    }
    let prec: Vec<(String, String)> = want["precedence"]
        .as_array()
        .unwrap()
        .iter()
        .map(|p| {
            (
                p[0].as_str().unwrap().to_owned(),
                p[1].as_str().unwrap().to_owned(),
            )
        })
        .collect();
    assert_eq!(m.precedence, prec, "{tag} precedence");
    let kos: Vec<Value> = m.keepouts.iter().map(keepout).collect();
    assert_eq!(Value::from(kos), want["keepouts"], "{tag} keepouts");
    same_orders(m, want, tag);
    same_blocks(m, want, tag);
}

#[track_caller]
fn same_orders(m: &Mission, want: &Value, tag: &str) {
    let orders = want["orders"].as_array().unwrap();
    assert_eq!(m.orders.len(), orders.len(), "{tag} orders");
    for (o, w) in m.orders.iter().zip(orders) {
        let kind = match o.kind {
            OrderKind::Cut => "cut",
            OrderKind::Fill => "fill",
            OrderKind::Sinter => "sinter",
            OrderKind::Goto => "goto",
        };
        assert_eq!(kind, w["kind"].as_str().unwrap(), "{tag} kind");
        assert_eq!(o.action, w["action"].as_str().unwrap(), "{tag} action");
        for (got, key) in [
            (o.x, "x"),
            (o.y, "y"),
            (o.footprint_m2, "footprint_m2"),
            (o.depth_m, "depth_m"),
        ] {
            assert_eq!(
                got.to_bits(),
                f(&w[key]).to_bits(),
                "{tag} {} {key}",
                o.action
            );
        }
        assert_eq!(o.note, w["note"].as_str().unwrap(), "{tag} note");
        assert_eq!(
            o.shape.as_ref().unwrap_or(&Value::Null),
            &w["shape"],
            "{tag} shape"
        );
        assert_eq!(
            o.insitu_density_kg_m3,
            w["insitu_density_kg_m3"].as_f64(),
            "{tag} insitu"
        );
    }
}

#[track_caller]
fn same_blocks(m: &Mission, want: &Value, tag: &str) {
    let opt_map = |v: &Value| {
        if v.is_null() {
            serde_json::json!({})
        } else {
            v.clone()
        }
    };
    let oc: serde_json::Map<String, Value> = m
        .objective_constraints
        .iter()
        .map(|(k, v)| (k.clone(), Value::from(*v)))
        .collect();
    assert_eq!(
        Value::from(oc),
        opt_map(&want["objective_constraints"]),
        "{tag} constraints"
    );
    let mw: serde_json::Map<String, Value> = m
        .mission_windows
        .iter()
        .map(|(k, v)| {
            (
                k.clone(),
                Value::from(v.iter().map(|(a, b)| vec![*a, *b]).collect::<Vec<_>>()),
            )
        })
        .collect();
    assert_eq!(
        Value::from(mw),
        opt_map(&want["mission_windows"]),
        "{tag} windows"
    );
    let sr: Vec<Value> = m
        .shared_resources
        .iter()
        .map(|r| {
            serde_json::json!({"id": r.id, "kind": r.kind, "capacity": r.capacity,
            "sites": r.sites.iter().map(|(x, y)| vec![*x, *y]).collect::<Vec<_>>()})
        })
        .collect();
    let opt_list = |v: &Value| {
        if v.is_null() {
            serde_json::json!([])
        } else {
            v.clone()
        }
    };
    assert_eq!(
        Value::from(sr),
        opt_list(&want["shared_resources"]),
        "{tag} resources"
    );
    let ob: Vec<Value> = m
        .observations
        .iter()
        .map(|o| serde_json::json!({"vehicle": o.vehicle, "x": o.x, "y": o.y, "t_start": o.t_start, "t_end": o.t_end, "kind": o.kind}))
        .collect();
    assert_eq!(
        Value::from(ob),
        opt_list(&want["observations"]),
        "{tag} observations"
    );
    assert_eq!(
        m.dig_energy_factor,
        want["dig_energy_factor"].as_f64(),
        "{tag} dig factor"
    );
    assert_eq!(
        m.accept_flatness_tol_m,
        want["accept_flatness_tol_m"].as_f64(),
        "{tag} flatness"
    );
}

#[test]
fn every_payload_is_accepted_or_refused_as_the_python_does() {
    let fx = stewie_oracle::load("mission_cases").unwrap().payload;
    let reg = registries();
    let (mut accepted, mut refused) = (0, 0);
    for c in fx["cases"].as_array().unwrap() {
        let name = c["name"].as_str().unwrap();
        let got = mission_from_value(&c["payload"], &reg);
        if STRICTER.contains(&name) {
            assert!(
                c["ok"].as_bool().unwrap() && got.is_err(),
                "{name}: the Python accepts, Rust refuses"
            );
            continue;
        }
        if c["ok"].as_bool().unwrap() {
            let m =
                got.unwrap_or_else(|e| panic!("{name}: refused but the Python accepts it: {e}"));
            same(&m, &c["mission"], &c["payload"], name);
            accepted += 1;
        } else {
            assert!(
                got.is_err(),
                "{name}: accepted but the Python refuses ({})",
                c["error"]
            );
            refused += 1;
        }
    }
    assert_eq!((accepted, refused), (14, 38), "vacuity: every case ran");
}
