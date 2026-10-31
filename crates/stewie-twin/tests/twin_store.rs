//! `TwinStore` against the Python oracle `twin_store_cases` (the REAL Haworth crop as base; patches
//! labelled SYNTHETIC where they are not the real unchanged resync): a Python journal replays to the same
//! map, mask and identity; the same edits written by Rust are byte-identical; a tampered patch value is
//! refused; a torn tail recovers and keeps journalling; malformed edits are refused.

use std::fs;
use std::path::PathBuf;

use serde_json::Value;
use stewie_twin::TwinError;
use stewie_twin::twin_store::TwinStore;

#[allow(clippy::cast_possible_truncation)]
fn setup() -> (Value, Vec<f64>, usize, usize) {
    let fx = stewie_oracle::load("twin_store_cases").unwrap().payload;
    let base: Vec<f64> = fx["base"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap())
        .collect();
    let (r, c) = (
        fx["rows"].as_u64().unwrap() as usize,
        fx["cols"].as_u64().unwrap() as usize,
    );
    (fx, base, r, c)
}

fn scratch(tag: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("stewie-twinstore-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    d
}

fn block(
    base: &[f64],
    cols: usize,
    r: std::ops::Range<usize>,
    c: std::ops::Range<usize>,
    add: f64,
) -> Vec<Vec<f64>> {
    r.map(|i| c.clone().map(|j| base[i * cols + j] + add).collect())
        .collect()
}

#[test]
fn a_python_journal_replays_and_rust_writes_the_same_bytes() {
    let (fx, base, rows, cols) = setup();
    let dir = scratch("parity");
    let py = dir.join("py.journal");
    fs::write(&py, fx["journal"].as_str().unwrap()).unwrap();
    let tw = TwinStore::from_journal(base.clone(), rows, cols, 5.0, &py).unwrap();
    assert!(tw.verify_chain());
    assert_eq!(
        tw.identity(),
        (
            fx["version"].as_u64().unwrap(),
            fx["identity_hash"].as_str().unwrap().to_owned()
        )
    );
    let cur: Vec<f64> = fx["current"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_f64().unwrap())
        .collect();
    assert_eq!(tw.current(), cur, "replayed map is bit-identical");
    let obs: Vec<bool> = fx["observed"]
        .as_array()
        .unwrap()
        .iter()
        .map(|v| v.as_bool().unwrap())
        .collect();
    assert_eq!(tw.observed_mask(), obs);

    let rs = dir.join("rs.journal");
    fs::write(&rs, b"").unwrap();
    let mut mine = TwinStore::from_journal(base.clone(), rows, cols, 5.0, &rs).unwrap();
    mine.apply_patch(
        &block(&base, cols, 4..10, 6..14, 0.0),
        (4, 6),
        "resync: unchanged real crop (not sensor evidence)",
    )
    .unwrap();
    mine.apply_patch(
        &block(&base, cols, 12..15, 20..25, 0.25),
        (12, 20),
        "SYNTHETIC +0.25 m offset (labelled)",
    )
    .unwrap();
    mine.undo().unwrap();
    mine.apply_patch(
        &vec![vec![1700.0; 3]; 2],
        (0, 0),
        "SYNTHETIC integral heights \u{e9}",
    )
    .unwrap();
    mine.apply_patch(
        &block(&base, cols, 29..32, 28..32, -0.5),
        (29, 28),
        "SYNTHETIC edge patch",
    )
    .unwrap();
    mine.undo().unwrap();
    mine.undo().unwrap();
    assert_eq!(
        fs::read_to_string(&rs).unwrap(),
        fx["journal"].as_str().unwrap(),
        "byte-identical journal"
    );
    assert_eq!(mine.identity(), tw.identity());
    fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn a_tampered_patch_is_refused_and_a_torn_tail_recovers() {
    let (fx, base, rows, cols) = setup();
    let lines: Vec<&str> = fx["journal"].as_str().unwrap().lines().collect();
    let dir = scratch("faults");
    let path = dir.join("twin.journal");
    let mut ev: Value = serde_json::from_str(lines[1]).unwrap();
    let v = ev["patch"][0][0].as_f64().unwrap();
    ev["patch"][0][0] = Value::from(v + 1e-9);
    let tampered = format!("{}\n{}\n", lines[0], serde_json::to_string(&ev).unwrap());
    fs::write(&path, &tampered).unwrap();
    assert!(matches!(
        TwinStore::from_journal(base.clone(), rows, cols, 5.0, &path),
        Err(TwinError::Tampered(_))
    ));
    assert_eq!(
        fs::read_to_string(&path).unwrap(),
        tampered,
        "a refused replay does not touch the file"
    );

    let intact: String = lines[..6].iter().fold(String::new(), |s, l| s + l + "\n");
    fs::write(
        &path,
        format!("{intact}{}", &lines[6][..lines[6].len() / 2]),
    )
    .unwrap();
    let mut tw = TwinStore::from_journal(base.clone(), rows, cols, 5.0, &path).unwrap();
    assert_eq!(
        tw.version(),
        6,
        "the torn seventh event was never acknowledged"
    );
    assert_eq!(fs::read_to_string(&path).unwrap(), intact);
    tw.undo().unwrap();
    let again = TwinStore::from_journal(base, rows, cols, 5.0, &path).unwrap();
    assert_eq!(
        again.identity(),
        tw.identity(),
        "the post-repair append survives a restart"
    );
    assert_eq!(
        again.identity().1,
        fx["identity_hash"].as_str().unwrap(),
        "and re-derives the original seventh event"
    );
    fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn malformed_edits_are_refused_like_python() {
    let (fx, base, rows, cols) = setup();
    let mut tw = TwinStore::new(base, rows, cols, 5.0).unwrap();
    assert!(fx["errors"]["nothing_to_undo"].is_string());
    assert!(matches!(tw.undo(), Err(TwinError::Invalid(m)) if m == "nothing to undo"));
    assert!(fx["errors"]["out_of_bounds"].is_string());
    assert!(
        tw.apply_patch(&vec![vec![0.0; 3]; 3], (30, 30), "x")
            .is_err()
    );
    assert!(
        matches!(tw.apply_patch(&[vec![0.0]], (0, 0), "  "), Err(TwinError::Invalid(m)) if m.contains("provenance"))
    );
    assert!(tw.apply_patch(&[vec![f64::NAN]], (0, 0), "x").is_err());
    assert!(
        tw.apply_patch(&[vec![0.0, 1.0], vec![2.0]], (0, 0), "x")
            .is_err(),
        "ragged"
    );
    assert_eq!(tw.version(), 0, "nothing refused was appended");
}
