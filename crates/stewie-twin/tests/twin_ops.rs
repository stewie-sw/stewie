//! The twin's server-side operations against the Python oracle `twin_ops_cases`: the composed terrain view over
//! a REAL Haworth crop (as-built from Terrain Memory, observed from twin patches), the Python's own backup and
//! stamped (deflated) snapshots restoring here, Rust snapshots the Python can verify, and the version and time
//! retention ladders and snapshot triggers (names and times SYNTHETIC, labelled in the oracle).

use std::collections::BTreeMap;

use serde_json::Value;
use stewie_twin::cadence::{self, Ladder, Scheduler};
use stewie_twin::terrain_view::{Source, compose};
use stewie_twin::twin_store::TwinStore;
use stewie_twin::{backup, numpy};

fn fx() -> Value {
    stewie_oracle::load("twin_ops_cases").unwrap().payload
}

fn f(v: &Value) -> f64 {
    v.as_f64().unwrap()
}

fn vf(v: &Value) -> Vec<f64> {
    v.as_array().unwrap().iter().map(f).collect()
}

fn path(fx: &Value, key: &str) -> std::path::PathBuf {
    stewie_oracle::repo_root().join(fx[key].as_str().unwrap())
}

fn tmp(tag: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("stewie_ops_{tag}_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[test]
fn the_view_composes_observed_over_as_built_over_pristine() {
    let fx = fx();
    let dem = vf(&fx["dem"]);
    let as_built = vf(&fx["as_built"]);
    let observed = vf(&fx["observed"]);
    let mask: Vec<bool> = fx["mask"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_bool().unwrap())
        .collect();
    let (abv, twv) = (
        fx["as_built_version"].as_u64().unwrap(),
        fx["twin_version"].as_u64().unwrap(),
    );
    let v = compose(
        &dem,
        5.0,
        Some((&as_built, abv)),
        Some((&observed, &mask, twv)),
    );
    let w = &fx["view"];
    assert_eq!(v.heights, vf(&w["heights"]));
    let src: Vec<u8> = v.source.iter().map(|s| *s as u8).collect();
    let want: Vec<u8> = w["source"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| u8::try_from(x.as_u64().unwrap()).unwrap())
        .collect();
    assert_eq!(src, want);
    assert_eq!((v.as_built_version, v.twin_version), (abv, twv));
    assert_eq!(
        v.observed_fraction.to_bits(),
        f(&w["observed_fraction"]).to_bits()
    );
    for s in [Source::Pristine, Source::AsBuilt, Source::Observed] {
        assert!(v.source.contains(&s), "vacuity: {s:?} present");
    }
    // SR-17: sub-centimetre edge changes of the volume-conserving coarse imprint count as built
    let coarse = compose(&dem, 5.0, Some((&vf(&fx["coarse_as_built"]), 1)), None);
    assert_eq!(coarse.heights, vf(&fx["coarse_view"]["heights"]));
    let src: Vec<u8> = coarse.source.iter().map(|s| *s as u8).collect();
    let want: Vec<u8> = fx["coarse_view"]["source"]
        .as_array()
        .unwrap()
        .iter()
        .map(|x| u8::try_from(x.as_u64().unwrap()).unwrap())
        .collect();
    assert_eq!(src, want);
    // a wrong-sized as-built layer and an empty observed mask contribute nothing
    let none = vec![false; dem.len()];
    let ig = compose(
        &dem,
        5.0,
        Some((&as_built[1..], abv)),
        Some((&observed, &none, twv)),
    );
    assert_eq!(ig.heights, vf(&fx["ignored"]["heights"]));
    assert_eq!((ig.as_built_version, ig.twin_version), (0, 0));
}

#[test]
fn python_snapshots_restore_here_and_rust_snapshots_round_trip() {
    let fx = fx();
    let want_id = (
        fx["identity"][0].as_u64().unwrap(),
        fx["identity"][1].as_str().unwrap().to_owned(),
    );
    let py = backup::restore(&path(&fx, "snapshot")).unwrap();
    assert_eq!(py.identity(), want_id);
    assert_eq!(py.current(), vf(&fx["observed"]));
    // the stamped snapshot is deflated (numpy.savez_compressed) and still restores, with its stamp
    let stamped = path(&fx, "stamped");
    assert_eq!(backup::restore(&stamped).unwrap().identity(), want_id);
    assert_eq!(
        cadence::snapshot_time(&stamped).unwrap(),
        Some(f(&fx["stamped_t"]))
    );
    assert_eq!(
        cadence::snapshot_time(&path(&fx, "snapshot")).unwrap(),
        None
    );
    // Rust writes: the stored event bytes are Python's json.dumps form, so its checksum verifies there too
    let d = tmp("snap");
    let p = backup::snapshot(&py, &d).unwrap();
    assert_eq!(p.file_name().unwrap(), "twin_v000002.npz");
    let again = backup::restore(&p).unwrap();
    assert_eq!(again.identity(), want_id);
    let arrays = numpy::read_npz(std::fs::File::open(&p).unwrap()).unwrap();
    let Some(numpy::Array::U8 { data, .. }) = arrays.get("events") else {
        panic!("events")
    };
    let ours: Value = serde_json::from_slice(data).unwrap();
    assert_eq!(ours, fx["events"], "the stored event log is the Python's");
    let stamped_rust = cadence::snapshot_at(&py, &d.join("stamped"), 77.0).unwrap();
    assert_eq!(cadence::snapshot_time(&stamped_rust).unwrap(), Some(77.0));
    // a corrupted base is refused (SYNTHETIC tamper of a valid file, labelled)
    let mut a = numpy::read_npz(std::fs::File::open(&p).unwrap()).unwrap();
    if let Some(numpy::Array::F64 { data, .. }) = a.get_mut("base") {
        data[7] += 1.0;
    }
    let order = ["base", "cell_m", "events", "checksum"];
    let named: Vec<(&str, numpy::Array)> = order.iter().map(|k| (*k, a[*k].clone())).collect();
    let bad = d.join("bad.npz");
    numpy::write_npz(std::fs::File::create(&bad).unwrap(), &named).unwrap();
    assert!(backup::restore(&bad).is_err());
    std::fs::remove_dir_all(&d).unwrap();
}

#[test]
fn the_ladders_and_the_scheduler_keep_what_the_python_keeps() {
    let fx = fx();
    let d = tmp("ladder");
    for v in 1..24 {
        std::fs::write(d.join(format!("twin_v{v:06}.npz")), b"").unwrap();
    }
    std::fs::write(d.join(".twin_v000003.npz.tmp"), b"").unwrap(); // a crash-left temp is not a snapshot
    let kept = backup::apply_retention(&d, 5, 10).unwrap();
    let want: Vec<&str> = fx["kept_versions"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert_eq!(kept, want);
    std::fs::remove_dir_all(&d).unwrap();

    let times: BTreeMap<String, f64> = fx["times"]
        .as_object()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), f(v)))
        .collect();
    let ladder = Ladder {
        keep_hourly: 24,
        keep_daily: 7,
        keep_weekly: 4,
        hour_s: 3600.0,
        day_s: 86_400.0,
        week_s: 7.0 * 86_400.0,
    };
    let got: Vec<String> = cadence::select_retained(&times, f(&fx["now"]), &ladder)
        .into_iter()
        .collect();
    let want: Vec<&str> = fx["retained"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_str().unwrap())
        .collect();
    assert_eq!(got, want);

    let s = Scheduler {
        sol_seconds: f(&fx["sol_seconds"]),
        every_n_events: fx["every_n_events"].as_u64().unwrap(),
    };
    for c in fx["due"].as_array().unwrap() {
        let due = s
            .due(
                f(&c["t"]),
                c["n"].as_u64().unwrap(),
                f(&c["last_t"]),
                c["last_n"].as_u64().unwrap(),
            )
            .unwrap();
        assert_eq!(due, c["due"].as_bool().unwrap(), "{c}");
    }
    assert!(
        Scheduler {
            sol_seconds: 0.0,
            every_n_events: 5
        }
        .due(0.0, 0, 0.0, 0)
        .is_err()
    );
}

#[test]
fn time_retention_prunes_stamped_snapshots_and_never_unstamped_ones() {
    let fx = fx();
    let tw = backup::restore(&path(&fx, "snapshot")).unwrap();
    let d = tmp("time");
    let stamped = cadence::snapshot_at(&tw, &d, 0.0).unwrap();
    let mut store =
        TwinStore::new(tw.base().to_vec(), tw.shape().0, tw.shape().1, tw.cell_m()).unwrap();
    for ev in tw.events() {
        store.apply_event(ev).unwrap();
    }
    std::fs::rename(&stamped, d.join("twin_v000001.npz")).unwrap();
    backup::snapshot(&store, &d).unwrap(); // twin_v000002.npz, unstamped
    let ladder = Ladder {
        keep_hourly: 1,
        keep_daily: 0,
        keep_weekly: 0,
        hour_s: 3600.0,
        day_s: 86_400.0,
        week_s: 604_800.0,
    };
    let kept = cadence::apply_time_retention(&d, 10.0 * 3600.0, &ladder).unwrap();
    assert_eq!(
        kept,
        vec!["twin_v000002.npz".to_owned()],
        "the old stamped one goes; the unstamped one stays"
    );
    assert!(!d.join("twin_v000001.npz").exists());
    let replica = tmp("replica");
    std::fs::rename(&d, replica.join("snapshots")).ok();
    let dest = tmp("dest");
    let items = backup::replicate(&replica, &dest).unwrap();
    assert_eq!(items, vec!["snapshots".to_owned()]);
    assert!(dest.join("snapshots/twin_v000002.npz").exists());
    assert!(backup::replicate(&dest.join("missing"), &dest).is_err());
    std::fs::remove_dir_all(&replica).unwrap();
    std::fs::remove_dir_all(&dest).unwrap();
}
