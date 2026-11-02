//! The SE(2) pose graph against the Python's (`oracle/build_fixtures.py::pose_graph_se2_cases`, SYNTHETIC graphs,
//! and `::pose_graph_se2_s3li`, the real S3LI loop-closure recipe). Tolerances, set before any comparison ran:
//! poses 1e-8 (synthetic) absolute; the final cost and the VO scale 1e-9 relative; sigmas 1e-7 relative; the
//! condition number 1e-9 relative plus 256 cond eps (its smallest eigenvalue is only that accurate); iterations,
//! convergence, conditioning flags and refusal messages exact. The S3LI poses were set at the RW-40 acceptance's
//! 1e-6 m and measured at its noise floor (D-R163): the graph's condition number is 3.4e9, so the order the normal
//! equations are summed in alone moves the converged poses by 3.5e-7 m (Rust forward against reversed rows), and the
//! Python's blocked BLAS order lands 1.04e-6 m away at an equal cost (2.8e-15 relative). They are held to 1e-5 m.

use std::collections::BTreeMap;

use serde_json::Value;
use stewie_perceive::pose_graph_se2::{GraphError, PoseGraphSe2, Status, yaw_from_shadow};

/// A fixture number, `"inf"`/`"-inf"`/`"nan"` included (the fixture is strict JSON).
fn num(v: &Value) -> f64 {
    match v.as_str() {
        Some("inf") => f64::INFINITY,
        Some("-inf") => f64::NEG_INFINITY,
        Some("nan") => f64::NAN,
        _ => v.as_f64().unwrap(),
    }
}

fn arr<const N: usize>(v: &Value) -> [f64; N] {
    let a = v.as_array().unwrap();
    assert_eq!(a.len(), N);
    std::array::from_fn(|k| num(&a[k]))
}

fn node(v: &Value) -> i64 {
    v.as_i64().unwrap()
}

/// Replay the recorded add calls in order (factor order is behaviour).
fn replay(calls: &Value, opts: &Value) -> Result<PoseGraphSe2, GraphError> {
    let mut g = PoseGraphSe2::new(
        opts.get("robust").and_then(Value::as_bool).unwrap_or(true),
        opts.get("huber_delta")
            .and_then(Value::as_f64)
            .unwrap_or(1.345),
        opts.get("estimate_vo_scale")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    for c in calls.as_array().unwrap() {
        let a = c.as_array().unwrap();
        match a[0].as_str().unwrap() {
            "prior" => g.add_prior(node(&a[1]), arr(&a[2]), num(&a[3]), num(&a[4]))?,
            "between" => {
                g.add_between(node(&a[1]), node(&a[2]), arr(&a[3]), num(&a[4]), num(&a[5]))?;
            }
            "vo_between" => {
                g.add_vo_between(node(&a[1]), node(&a[2]), arr(&a[3]), num(&a[4]), num(&a[5]))?;
            }
            "vo_scale_prior" => g.set_vo_scale_prior(num(&a[1]), num(&a[2]))?,
            "imu_yaw" => g.add_imu_yaw(node(&a[1]), node(&a[2]), num(&a[3]), num(&a[4]))?,
            "shadow_yaw" => g.add_shadow_yaw(node(&a[1]), num(&a[2]), num(&a[3]))?,
            "absolute" => g.add_absolute(node(&a[1]), arr(&a[2]), num(&a[3]))?,
            "absolute_cov" => {
                let m = a[3].as_array().unwrap();
                g.add_absolute_cov(
                    node(&a[1]),
                    arr(&a[2]),
                    [arr(&m[0]), arr(&m[1])],
                    num(&a[4]),
                )?;
            }
            other => panic!("unknown call {other}"),
        }
    }
    Ok(g)
}

fn close_rel(got: f64, want: f64, rel: f64) -> bool {
    if want.is_infinite() || got.is_infinite() {
        return got.to_bits() == want.to_bits(); // an infinity matches only the same infinity
    }
    (got - want).abs() <= rel * want.abs().max(got.abs())
}

fn assert_status(got: &Status, want: &Value, what: &str) {
    assert_eq!(
        (
            got.converged,
            got.iterations,
            got.well_conditioned,
            got.final_gradient_norm < 1e-4
        ),
        (
            want["converged"].as_bool().unwrap(),
            usize::try_from(want["iterations"].as_u64().unwrap()).unwrap(),
            want["well_conditioned"].as_bool().unwrap(),
            want["gradient_below_tol"].as_bool().unwrap()
        ),
        "{what}: converged, iterations, well_conditioned, gradient below 1e-4"
    );
    let cond = num(&want["condition_number"]);
    let tol = 1e-9 + 256.0 * cond * f64::EPSILON;
    assert!(
        close_rel(got.condition_number, cond, tol),
        "{what}: condition {} vs {cond}",
        got.condition_number
    );
    let cost = num(&want["final_cost"]);
    // a cost at machine zero (an exactly consistent graph) is compared absolutely
    assert!(
        close_rel(got.final_cost, cost, 1e-9)
            || (got.final_cost.abs() < 1e-20 && cost.abs() < 1e-20),
        "{what}: cost {} vs {cost}",
        got.final_cost
    );
}

fn assert_poses(got: &BTreeMap<i64, [f64; 3]>, want: &Value, tol: f64, what: &str) {
    let want = want.as_object().unwrap();
    assert_eq!(got.len(), want.len(), "{what}: node count");
    for (k, w) in want {
        let p = got[&k.parse::<i64>().unwrap()];
        let w: [f64; 3] = arr(w);
        for c in 0..3 {
            assert!(
                (p[c] - w[c]).abs() <= tol,
                "{what}: node {k} component {c}: {} vs {}",
                p[c],
                w[c]
            );
        }
    }
}

fn assert_sigmas(got: &BTreeMap<i64, f64>, want: &Value, what: &str) {
    for (k, w) in want.as_object().unwrap() {
        let (g, w) = (got[&k.parse::<i64>().unwrap()], num(w));
        assert!(close_rel(g, w, 1e-7), "{what}: node {k}: {g} vs {w}");
    }
}

#[test]
fn the_synthetic_graphs_solve_as_the_pythons() {
    let fx = stewie_oracle::load("pose_graph_se2_cases").unwrap().payload;
    let cases = fx["cases"].as_array().unwrap();
    assert!(cases.len() >= 8, "vacuity: the recorded graphs");
    for c in cases {
        let name = c["name"].as_str().unwrap();
        let g = replay(&c["calls"], &c["opts"]).unwrap();
        let out = &c["out"];
        assert_status(&g.solve_status(), &out["status"], name);
        assert_poses(&g.optimize(), &out["pose"], 1e-8, name);
        let cov = g.optimize_with_cov();
        assert_poses(&cov.pose, &out["cov"]["pose"], 1e-8, name);
        assert_sigmas(
            &cov.xy_sigma,
            &out["cov"]["xy_sigma"],
            &format!("{name} xy sigma"),
        );
        assert_sigmas(
            &cov.yaw_sigma,
            &out["cov"]["yaw_sigma"],
            &format!("{name} yaw sigma"),
        );
        assert_eq!(
            cov.observable,
            out["cov"]["observable"].as_bool().unwrap(),
            "{name}"
        );
        let sc = g.optimize_with_scale();
        let want = &out["scale"];
        assert!(
            close_rel(sc.vo_scale, num(&want["vo_scale"]), 1e-9),
            "{name}: scale {}",
            sc.vo_scale
        );
        match (sc.vo_scale_sigma, want["vo_scale_sigma"].is_null()) {
            (None, true) => {}
            (Some(s), false) => assert!(
                close_rel(s, num(&want["vo_scale_sigma"]), 1e-7),
                "{name}: scale sigma {s}"
            ),
            other => panic!("{name}: scale sigma presence {other:?}"),
        }
        assert_eq!(
            (sc.scale_observable, sc.observable),
            (
                want["scale_observable"].as_bool().unwrap(),
                want["observable"].as_bool().unwrap()
            ),
            "{name}"
        );
        assert_status(&sc.status, &want["status"], name);
    }
}

#[test]
fn invalid_measurements_are_refused_with_the_pythons_messages() {
    let fx = stewie_oracle::load("pose_graph_se2_cases").unwrap().payload;
    let refusals = fx["refusals"].as_array().unwrap();
    assert!(!refusals.is_empty());
    for r in refusals {
        let e = replay(&r["calls"], &Value::Null).unwrap_err();
        assert_eq!(e.0, r["error"].as_str().unwrap());
    }
}

#[test]
fn the_shadow_heading_wraps_as_the_pythons() {
    let fx = stewie_oracle::load("pose_graph_se2_cases").unwrap().payload;
    for y in fx["yaw_from_shadow"].as_array().unwrap() {
        let [az, bearing, want] = arr(y);
        assert_eq!(
            yaw_from_shadow(az, bearing).to_bits(),
            want.to_bits(),
            "{az} {bearing}"
        );
    }
}

#[test]
fn the_s3li_loop_closure_graph_solves_as_the_pythons() {
    // the real recipe: 538 keyframes of stride-3 stereo VO odometry and five accepted visual loop closures
    let fx = stewie_oracle::load("pose_graph_se2_s3li").unwrap().payload;
    let g = replay(&fx["calls"], &Value::Null).unwrap();
    let sol = g.solve(usize::try_from(fx["iters"].as_u64().unwrap()).unwrap());
    assert_eq!(sol.order.len(), 538, "vacuity: the recipe's keyframes");
    assert_status(&sol.status, &fx["status"], "s3li");
    assert_poses(&sol.pose_map(), &fx["pose"], 1e-5, "s3li");
}
