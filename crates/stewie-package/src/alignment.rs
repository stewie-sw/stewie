//! A package's LOLA alignment record (RW-60c, navigator N32, D-R105): every layer fitted to the pinned LOLA RDR
//! extract that covers it, or, for a local crop, the parent it is a window of. `Package::open` refuses a package
//! whose record is missing a layer, carries another policy than the code's, or holds a layer that fails.

use std::path::{Path, PathBuf};

use lunar_dem::align::{
    MAX_SHIFT_PX, OUTLIER_SIGMAS, RMS_BASE_M, RMS_PER_RESOLUTION, admits, align, parse_shots,
};
use lunar_dem::{GlobalGrid, PolarGrid, TerrainSource};
use lunar_frames::{LatLon, Sphere};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

/// The record's file name inside a package directory.
pub const ALIGNMENT_FILE: &str = "alignment.json";

/// Shots a layer must cover for its fit to count.
pub const MIN_SHOTS: usize = 1000;

/// The admission policy as the record states it (and `Package::open` requires it to state).
#[must_use]
pub fn policy() -> Value {
    json!({"outlier_sigmas": OUTLIER_SIGMAS, "max_shift_px": MAX_SHIFT_PX,
           "rms_base_m": RMS_BASE_M, "rms_per_resolution": RMS_PER_RESOLUTION})
}

fn hex(b: &[u8]) -> String {
    Sha256::digest(b).iter().fold(String::new(), |mut s, x| {
        use std::fmt::Write as _;
        let _ = write!(s, "{x:02x}");
        s
    })
}

/// A layer of the package directory `dir` opened from its own files.
fn open_layer(dir: &Path, layer: &Value, sphere: Sphere) -> Result<Box<dyn TerrainSource>, String> {
    let id = layer["id"].as_str().ok_or("layer without an id")?;
    let path = |f: &str| -> Result<PathBuf, String> {
        Ok(dir.join(
            layer[f]["path"]
                .as_str()
                .ok_or_else(|| format!("{id}: no {f} file"))?,
        ))
    };
    let label = std::fs::read_to_string(path("label")?).map_err(|e| format!("{id}: {e}"))?;
    let image = std::fs::read(path("image")?).map_err(|e| format!("{id}: {e}"))?;
    Ok(match layer["kind"].as_str() {
        Some("pds_simple_cylindrical") => Box::new(
            GlobalGrid::from_label_bytes(id, &label, &image, sphere).map_err(|e| e.to_string())?,
        ),
        Some("pds_polar_stereographic") => Box::new(
            PolarGrid::from_label_bytes(id, &label, &image, sphere).map_err(|e| e.to_string())?,
        ),
        other => return Err(format!("{id}: kind {other:?}")),
    })
}

/// Align every layer of the package in `dir` to the pinned LOLA `boxes` (name, extract path) and return the
/// record. A crop (`crop_of`) inherits its parent's alignment: from this package when the parent is installed
/// here, else carried over from `parents` (the record of the package the parent is in). Any other layer is fitted
/// to the box whose shots it covers most.
///
/// # Errors
/// An unreadable manifest, layer or extract, a layer that no box covers with `MIN_SHOTS` shots, or a crop whose
/// parent has no direct fit here or in `parents`.
pub fn align_package(
    dir: &Path,
    sphere: Sphere,
    boxes: &[(String, PathBuf)],
    parents: Option<&Value>,
) -> Result<Value, String> {
    let manifest: Value = serde_json::from_str(
        &std::fs::read_to_string(dir.join("manifest.json"))
            .map_err(|e| format!("manifest: {e}"))?,
    )
    .map_err(|e| format!("manifest: {e}"))?;
    let mut shots = Vec::with_capacity(boxes.len());
    for (name, path) in boxes {
        let bytes = std::fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let text = String::from_utf8(bytes.clone()).map_err(|e| format!("{name}: {e}"))?;
        shots.push((name.clone(), hex(&bytes), parse_shots(&text)?));
    }
    let mut layers = serde_json::Map::new();
    for layer in manifest["layers"].as_array().ok_or("manifest: no layers")? {
        let id = layer["id"].as_str().ok_or("layer without an id")?;
        if let Some(parent) = layer["crop_of"].as_str() {
            layers.insert(id.to_owned(), json!({"inherited_from": parent}));
            continue;
        }
        let src = open_layer(dir, layer, sphere)?;
        let covered = |s: &[lunar_dem::align::Shot]| {
            s.iter()
                .filter(|p| {
                    src.sample_latlon(LatLon {
                        lat_deg: p.lat_deg,
                        lon_deg: p.lon_deg,
                    })
                    .is_some()
                })
                .count()
        };
        let (name, sha, s) = shots
            .iter()
            .max_by_key(|(_, _, s)| covered(s))
            .filter(|(_, _, s)| covered(s) >= MIN_SHOTS)
            .ok_or_else(|| format!("{id}: no pinned LOLA box covers it with {MIN_SHOTS} shots"))?;
        let a = align(src.as_ref(), s, 3, MIN_SHOTS)?;
        layers.insert(
            id.to_owned(),
            json!({"box": name, "shots_sha256": sha, "shift_east_m": a.shift_east_m,
                   "shift_north_m": a.shift_north_m, "vertical_offset_m": a.vertical_offset_m,
                   "residual_rms_m": a.residual_rms_m, "shots_used": a.shots_used,
                   "shots_rejected": a.shots_rejected, "admitted": admits(&a, src.resolution_m())}),
        );
    }
    // a crop's parent that is not installed here travels with the record, from the package it is in
    let needed: Vec<String> = layers
        .values()
        .filter_map(|e| e["inherited_from"].as_str().map(str::to_owned))
        .filter(|p| !layers.contains_key(p))
        .collect();
    for parent in needed {
        let fit = parents
            .and_then(|r| r["layers"].get(&parent))
            .filter(|e| e["inherited_from"].is_null())
            .ok_or_else(|| format!("{parent}: a crop's parent with no direct LOLA fit"))?;
        layers.insert(parent, fit.clone());
    }
    Ok(json!({"package": manifest["name"], "policy": policy(), "layers": layers}))
}
