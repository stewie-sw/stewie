//! RW-55b3c against the Python oracle (`world_state_cases`): the same transitions through the world-state
//! authority give the same linked records (world and chain hashes), the same refusal, timeline and cold
//! restore, and a journal identical byte for byte. Identities, beliefs and the patch are SYNTHETIC test inputs;
//! the twins sit on the real site DEMs.

use lunar_frames::Sphere;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use stewie_server::state::{DEFAULT_TWIN_SOURCE, Terrain};
use stewie_server::world::{Stamp, WorldState};
use stewie_twin::world_log::WorldTransaction;

fn moon() -> Sphere {
    let reg: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn txn(t: &WorldTransaction) -> Value {
    json!({"seq": t.seq, "world_sha": t.world_sha, "chain_hash": t.chain_hash, "twin_version": t.twin_version,
           "twin_hash": t.twin_hash, "plan_id": t.plan_id, "authority_sha": t.authority_sha, "belief": t.belief,
           "mission": t.mission, "site": t.site, "body": t.body, "mission_t_s": t.mission_t_s,
           "uncertainty_m": t.uncertainty_m})
}

fn step(op: &str, r: Result<Value, String>) -> Value {
    match r {
        Ok(v) => json!({"op": op, "ok": v}),
        Err(e) => json!({"op": op, "error": format!("ValueError: {e}")}),
    }
}

fn belief(v: Value) -> Map<String, Value> {
    match v {
        Value::Object(m) => m,
        other => panic!("a belief is an object, got {other}"),
    }
}

#[test]
#[allow(clippy::too_many_lines)] // one scenario, step for step as the oracle's
fn the_python_world_state_scenario_replays_exactly() {
    let fx = stewie_oracle::load("world_state_cases").unwrap().payload;
    let data = std::env::temp_dir().join(format!("stewie-world-oracle-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&data);
    std::fs::create_dir_all(data.join("twin")).unwrap();
    let sites: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/sites.json")).unwrap();
    let t = Terrain::new(
        data.clone(),
        stewie_oracle::repo_root().join("samples/lunar_dem"),
        None,
        sites,
        moon(),
    );
    let jp = data.join("twin/world.journal");
    let w = WorldState::open(&jp).unwrap();
    let mut s = vec![step(
        "record_plan",
        w.record_plan(
            &t,
            "plan-0001",
            "plan accepted",
            &Stamp {
                mission: Some("pad-a"),
                site: Some("haworth"),
                body: Some("moon"),
                mission_t_s: Some(10.0),
            },
        )
        .map(|x| txn(&x)),
    )];
    s.push(step(
        "record_terrain",
        w.record_terrain(&t, &"a1".repeat(32), "terrain recorded", &Stamp::default())
            .map(|x| txn(&x)),
    ));
    let other = t.twin("shackleton_rim", DEFAULT_TWIN_SOURCE).unwrap();
    let (dem, _) = t.moon_dem("shackleton_rim").unwrap();
    let h = dem.z[100 * dem.cols + 200] + 0.75;
    let mut tw = other.lock().unwrap();
    tw.apply_patch(&[vec![h; 2], vec![h; 2]], (100, 200), "oracle resync")
        .unwrap();
    s.push(step(
        "record_resync",
        w.record_resync(
            &t,
            "resync at shackleton_rim",
            Some("shackleton_rim"),
            0.3,
            Some(&tw),
        )
        .map(|x| txn(&x)),
    ));
    drop(tw);
    s.push(step(
        "record_belief",
        w.record_belief(
            &t,
            belief(json!({"pose_xy": [1.5, -2.0], "confidence": 0.8})),
            "belief update",
            Some(20.5),
        )
        .map(|x| txn(&x)),
    ));
    s.push(step(
        "record_execution_event",
        w.record_execution_event(
            &t,
            "SIM leg: leg 1 complete [ok]",
            Some(&"b2".repeat(32)),
            Some(belief(json!({"pose_xy": [3.0, 4.0]}))),
            &Stamp {
                mission: Some("pad-a"),
                mission_t_s: Some(30.25),
                ..Stamp::default()
            },
            0.1,
        )
        .map(|x| txn(&x)),
    ));
    s.push(step(
        "record_plan",
        w.record_plan(&t, "plan-0002", "   ", &Stamp::default())
            .map(|x| txn(&x)),
    ));
    s.push(step(
        "record_belief",
        w.record_belief(
            &t,
            belief(json!({"pose_xy": [3.0, 4.5]})),
            "after refusal",
            None,
        )
        .map(|x| txn(&x)),
    ));
    s.push(step("recent", Ok(Value::Array(w.recent(3)))));
    s.push(step("recent", Ok(Value::Array(w.recent(0)))));
    s.push(step("count", Ok(json!(w.transaction_count()))));
    s.push(step("verify_chain", Ok(json!(w.verify_chain()))));
    let restored = WorldState::open(&jp).unwrap();
    s.push(step(
        "restored_count",
        Ok(json!(restored.transaction_count())),
    ));
    s.push(step(
        "record_plan",
        restored
            .record_plan(&t, "plan-0003", "after restart", &Stamp::default())
            .map(|x| txn(&x)),
    ));
    s.push(step("latest", Ok(txn(&restored.latest().unwrap()))));
    let want = fx["steps"].as_array().unwrap();
    assert_eq!(s.len(), want.len());
    for (k, (g, w)) in s.iter().zip(want).enumerate() {
        assert_eq!(g, w, "step {k}");
    }
    let raw = std::fs::read(&jp).unwrap();
    let digest = Sha256::digest(&raw).iter().fold(String::new(), |mut h, b| {
        use std::fmt::Write as _;
        let _ = write!(h, "{b:02x}");
        h
    });
    assert_eq!(
        digest,
        fx["journal"]["sha256"].as_str().unwrap(),
        "the journal, byte for byte"
    );
    std::fs::remove_dir_all(&data).unwrap();
}
