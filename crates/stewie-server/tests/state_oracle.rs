//! RW-55b3b against the Python oracle (`state_cases`): the per-site DEM cache and anchors, the observed-twin
//! registry (journal names, identity markers, the SR-03 migration refusals) and the composed terrain view, by
//! the same steps in a temporary data dir. The DEMs are the real bundles; the memory delta, the observed patch
//! and the planted legacy journals are SYNTHETIC test inputs.

use std::path::Path;

use lunar_frames::Sphere;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use stewie_server::state::{DEFAULT_TWIN_SOURCE, Terrain};
use stewie_twin::terrain_memory::{TerrainMemory, save_site};

fn moon() -> Sphere {
    let reg: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/bodies.json")).unwrap();
    Sphere::new(reg["moon"]["ellipsoid_radius_m"].as_f64().unwrap()).unwrap()
}

fn twin(t: &Terrain, data: &Path, site: &str, source: &str) -> Value {
    let args = if source == DEFAULT_TWIN_SOURCE && site != "  HAWORTH " {
        json!([site])
    } else {
        json!([site, source])
    };
    match t.twin(site, source) {
        Ok(tw) => {
            let tw = tw.lock().unwrap();
            let default = std::sync::Arc::ptr_eq(
                &t.twin("haworth", DEFAULT_TWIN_SOURCE).unwrap(),
                &t.twin(site, source).unwrap(),
            );
            json!({"args": args, "ok": {
                "journal": tw.journal_path().unwrap().strip_prefix(data).unwrap().display().to_string(),
                "version": tw.version(), "shape": [tw.shape().0, tw.shape().1], "is_default": default}})
        }
        Err(e) => {
            json!({"args": args, "error": e.replace(&data.display().to_string(), "<data>")})
        }
    }
}

#[test]
#[allow(clippy::too_many_lines, clippy::cast_possible_truncation)] // one scenario as the oracle's; grid indices
fn the_python_state_scenario_replays_exactly() {
    let fx = stewie_oracle::load("state_cases").unwrap().payload;
    let data = std::env::temp_dir().join(format!("stewie-state-oracle-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&data);
    std::fs::create_dir_all(&data).unwrap();
    let sites: Value =
        serde_json::from_str(include_str!("../../stewie-contracts/fixtures/sites.json")).unwrap();
    let samples = stewie_oracle::repo_root().join("samples/lunar_dem");
    let t = Terrain::new(data.clone(), samples, None, sites, moon());

    let mut dems = Vec::new();
    for site in ["haworth", "shackleton_rim", "amundsen_rim", "atlantis"] {
        dems.push(match t.moon_dem(site) {
            Some((d, a)) => json!({"site": site, "has_dem": true, "shape": [d.rows, d.cols],
                                   "cell_m": d.cell_m, "anchor": [a.0, a.1]}),
            None => json!({"site": site, "has_dem": false, "shape": null, "cell_m": null, "anchor": [0.0, 0.0]}),
        });
    }
    assert_eq!(Value::Array(dems), fx["dems"], "the DEM cache");

    let jdir = data.join("twin");
    let mut twins = vec![
        twin(&t, &data, "haworth", DEFAULT_TWIN_SOURCE),
        twin(&t, &data, "Haworth", DEFAULT_TWIN_SOURCE),
        twin(&t, &data, "  HAWORTH ", "Stereo_SGBM"),
        twin(&t, &data, "haworth", "lidar"),
        twin(&t, &data, "shackleton_rim", DEFAULT_TWIN_SOURCE),
    ];
    std::fs::write(jdir.join("haworth__stereo_sgbm.journal"), "").unwrap();
    twins.push(twin(&t, &data, "haworth", "Stereo_SGBM"));
    std::fs::remove_file(jdir.join("haworth__stereo_sgbm.journal")).unwrap();
    std::fs::write(jdir.join("malapert_massif.journal"), "").unwrap();
    twins.push(twin(&t, &data, "Malapert Massif", DEFAULT_TWIN_SOURCE));
    // the oracle wrote this marker with the Python's own writer; the bytes are the same format
    let marker = |site: &str, source: &str| {
        format!(
            "{{\n \"schema\": \"stewie.twin-journal-identity/v1\",\n \"site\": \"{site}\",\n \"source\": \"{source}\"\n}}\n"
        )
    };
    std::fs::write(
        jdir.join("malapert_massif.journal.identity.json"),
        marker("malapert_massif", "stereo_sgbm"),
    )
    .unwrap();
    twins.push(twin(&t, &data, "Malapert Massif", DEFAULT_TWIN_SOURCE));
    std::fs::write(jdir.join("atlantis.journal"), "").unwrap();
    twins.push(twin(&t, &data, "atlantis", DEFAULT_TWIN_SOURCE));
    std::fs::write(
        jdir.join("nobile_rim1__radar.journal.identity.json"),
        marker("nobile_rim1", "lidar"),
    )
    .unwrap();
    twins.push(twin(&t, &data, "nobile_rim1", "radar"));
    let want = fx["twins"].as_array().unwrap();
    assert_eq!(twins.len(), want.len());
    for (k, (g, w)) in twins.iter().zip(want).enumerate() {
        assert_eq!(g, w, "twin step {k}");
    }
    let mut markers = serde_json::Map::new();
    let mut names: Vec<String> = std::fs::read_dir(&jdir)
        .unwrap()
        .flatten()
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".identity.json"))
        .collect();
    names.sort();
    for n in names {
        let text = std::fs::read_to_string(jdir.join(&n)).unwrap();
        markers.insert(n, serde_json::from_str(&text).unwrap());
    }
    assert_eq!(
        Value::Object(markers),
        fx["markers"],
        "the identity markers"
    );

    // the composed view: an as-built memory, then an observed patch over part of it
    let (dem, anchor) = t.moon_dem("haworth").unwrap();
    let mut mem = TerrainMemory::new("haworth", 4, 6, 5.0, (-10.0, -5.0)).unwrap();
    let mut delta = vec![0.0; 24];
    for r in 1..3 {
        for c in 1..5 {
            delta[r * 6 + c] = -0.25;
        }
    }
    delta[0] = 0.00005;
    mem.apply(&delta, "oracle-pad", 120.0).unwrap();
    save_site(&data, &mem).unwrap();
    let c = &fx["composed"];
    let (r0, c0) = (
        usize::try_from(c["patch_origin_rc"][0].as_u64().unwrap()).unwrap(),
        usize::try_from(c["patch_origin_rc"][1].as_u64().unwrap()).unwrap(),
    );
    assert_eq!(
        (r0, c0),
        (
            usize::try_from((anchor.1 / 5.0).round() as i64 - 1).unwrap(),
            usize::try_from((anchor.0 / 5.0).round() as i64).unwrap()
        )
    );
    let h0 = dem.z[r0 * dem.cols + c0] + 0.5;
    t.twin("haworth", DEFAULT_TWIN_SOURCE)
        .unwrap()
        .lock()
        .unwrap()
        .apply_patch(&[vec![h0; 3], vec![h0; 3]], (r0, c0), "oracle-observation")
        .unwrap();
    let view = t.current_terrain_view("haworth", &dem, anchor);
    let bytes: Vec<u8> = view.heights.iter().flat_map(|h| h.to_le_bytes()).collect();
    let digest = Sha256::digest(&bytes)
        .iter()
        .fold(String::new(), |mut h, b| {
            use std::fmt::Write as _;
            let _ = write!(h, "{b:02x}");
            h
        });
    let changed: Vec<Value> = view
        .source
        .iter()
        .enumerate()
        .filter(|(_, s)| **s as u8 != 0)
        .map(|(i, s)| {
            json!({"row": i / dem.cols, "col": i % dem.cols, "height": view.heights[i], "source": *s as u8})
        })
        .collect();
    assert_eq!(Value::Array(changed), c["changed"], "the changed cells");
    assert_eq!(
        view.as_built_version,
        c["as_built_version"].as_u64().unwrap()
    );
    assert_eq!(view.twin_version, c["twin_version"].as_u64().unwrap());
    assert_eq!(json!(view.observed_fraction), c["observed_fraction"]);
    assert_eq!(
        digest,
        c["heights_sha256"].as_str().unwrap(),
        "the composed heights, bit for bit"
    );
    std::fs::remove_dir_all(&data).unwrap();
}
