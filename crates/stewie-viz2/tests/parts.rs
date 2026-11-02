//! RW-51e1a: the viz2 runtime's building blocks equal the Python's (`viz2_parts_cases`): the stream session over a
//! SYNTHETIC send/ack/tick script, the runtime's drum sensor at both IPEx vehicle holds, the LIVE resolver over every
//! model and body, the arm engagement, and the flattest-interior spawn on every real bundle with a heightmap.

use serde_json::{Value, json};
use stewie_contracts::stream::StreamSession;
use stewie_physics::drum_sensor::{DrumSensor, ErrorBands};

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn close(got: f64, want: f64, what: &str) {
    assert!(
        (got - want).abs() <= 1e-9 * want.abs().max(1.0),
        "{what}: {got} vs {want}"
    );
}

fn fx() -> Value {
    stewie_oracle::load("viz2_parts_cases").unwrap().payload
}

#[test]
fn the_stream_session_matches() {
    let fx = fx();
    let mut s = StreamSession::new(3, 2.0).unwrap();
    for (i, step) in fx["stream"].as_array().unwrap().iter().enumerate() {
        let x = f(&step["x"]);
        let out = match step["op"].as_str().unwrap() {
            "send" => s.send(json!({"n": i}), x).unwrap_or(Value::Null),
            "ack" => {
                #[allow(clippy::cast_possible_truncation)] // a sequence number
                s.ack(x as i64);
                Value::Null
            }
            _ => json!(s.tick(x)),
        };
        assert_eq!(out, step["out"], "step {i}");
        assert_eq!(s.status(), step["status"], "step {i}");
    }
    assert!(StreamSession::new(0, 1.0).is_err() && StreamSession::new(1, 0.0).is_err());
}

#[test]
fn the_drum_sensor_matches_at_both_vehicle_holds() {
    let fx = fx();
    let report: Value = serde_json::from_str(include_str!(
        "../../stewie-contracts/fixtures/plan_report.json"
    ))
    .unwrap();
    let bands = ErrorBands {
        mpe_all: f(&report["fdc_mpe_all"]),
        mpe_half_full: f(&report["fdc_mpe_half_full"]),
    };
    let planner: Value = serde_json::from_str(
        &std::fs::read_to_string(stewie_oracle::repo_root().join("deploy/planner.json")).unwrap(),
    )
    .unwrap();
    let (base, slope) = (
        f(&planner["fdc_baseline_a"]["value"]),
        f(&planner["fdc_slope_a_per_kg"]["value"]),
    );
    for (drum, want) in fx["drums"].as_object().unwrap() {
        let hold = f(&want["hold_kg"]);
        let fills: Vec<f64> = [0.0, 0.25, 0.5, 0.75, 1.0]
            .iter()
            .map(|x| x * hold)
            .collect();
        let s = DrumSensor::calibrated(&fills, base, slope, hold, bands).unwrap();
        close(s.model.slope, f(&want["slope"]), drum);
        close(s.model.intercept, f(&want["intercept"]), drum);
        for r in want["rows"].as_array().unwrap() {
            let i = s.current(f(&r["mass_kg"])).unwrap();
            close(i, f(&r["current_a"]), drum);
            let inferred = s.infer(i);
            close(inferred, f(&r["inferred_kg"]), drum);
            let d = s.offload(inferred);
            assert_eq!(json!(d.offload), r["offload"], "{drum} {r}");
            close(d.uncertainty_frac, f(&r["uncertainty_frac"]), drum);
            close(d.upper_kg, f(&r["upper_kg"]), drum);
        }
    }
    assert!(
        DrumSensor::calibrated(&[1.0, 1.0], base, slope, 1.0, bands).is_err(),
        "constant features"
    );
}

#[test]
fn the_live_resolver_and_arm_engagement_match() {
    let fx = fx();
    let (reg, _) = stewie_physics::soil::bundled();
    for c in fx["resolve"].as_array().unwrap() {
        let got = stewie_physics::model_control::resolve_live_backend(
            c["model"].as_str(),
            c["body"].as_str(),
            &reg,
        );
        match c.get("backend") {
            Some(b) => assert_eq!(got.as_deref(), Ok(b.as_str().unwrap()), "{c}"),
            None => assert_eq!(got, Err(c["error"].as_str().unwrap().to_owned()), "{c}"),
        }
    }
    for c in fx["engagement"].as_array().unwrap() {
        let o = c["offset"]
            .as_f64()
            .unwrap_or_else(|| c["offset"].as_str().unwrap().parse().unwrap());
        assert_eq!(
            stewie_physics::arm::dig_engagement(o).to_bits(),
            f(&c["e"]).to_bits(),
            "{c}"
        );
    }
}

#[test]
fn the_flattest_interior_spawn_matches_on_every_real_bundle() {
    let fx = fx();
    let (reg, base) = stewie_physics::soil::bundled();
    let regolith = stewie_physics::column::Regolith::new(reg["moon"].bulk_density.unwrap(), &base);
    let spawns = fx["spawns"].as_array().unwrap();
    assert_eq!(
        spawns.len(),
        10,
        "vacuity: every real bundle with a heightmap"
    );
    for s in spawns {
        let name = s["bundle"].as_str().unwrap();
        let dir = stewie_oracle::repo_root()
            .join("samples/lunar_dem")
            .join(name);
        let (cs, origin) =
            stewie_physics::worksite::coarse_base_from_bundle(&dir, &regolith).unwrap();
        let height = cs.derive_height();
        let (r, c) =
            stewie_viz2::spawn::flattest_interior_rc(&height, cs.height(), cs.width(), cs.cell_m());
        #[allow(clippy::cast_precision_loss)] // grid indices
        let (x, y) = (
            origin.0 + c as f64 * cs.cell_m(),
            origin.1 + r as f64 * cs.cell_m(),
        );
        assert_eq!((x, y), (f(&s["x"]), f(&s["y"])), "{name}");
    }
}

#[test]
fn the_running_sum_filter_is_scipys_to_the_bit() {
    for c in fx()["uniform"].as_array().unwrap() {
        let line: Vec<f64> = c["line"].as_array().unwrap().iter().map(f).collect();
        let got: Vec<u64> = stewie_viz2::spawn::uniform_1d(&line, 9)
            .iter()
            .map(|x| x.to_bits())
            .collect();
        let want: Vec<u64> = c["out"]
            .as_array()
            .unwrap()
            .iter()
            .map(|x| f(x).to_bits())
            .collect();
        assert_eq!(got, want, "{line:?}");
    }
}
