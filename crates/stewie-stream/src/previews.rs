//! The setup screen's real-site data (Python `stewie.stream.previews` over `dart.dem_site_compare`): the real
//! bundles for the site dropdown, each with its verbatim `dem_provenance` citation, and a real heightmap decimated
//! for the preview mesh. A SYNTHETIC (procedural) bundle is never listed or previewed. The Python's procedural
//! preview had no caller and is retired with the fbm fill (D-R72, D-R184).

use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};

use crate::py;

/// The preview grid side.
pub const PREVIEW_N: usize = 128;

/// A refusal: a bad name or a SYNTHETIC bundle (400), or no such bundle (404).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PreviewError {
    Invalid(String),
    NotFound(String),
}

fn load_meta(bundle: &Path) -> Result<Value, String> {
    let text = std::fs::read(bundle.join("metadata.json")).map_err(|e| e.to_string())?;
    serde_json::from_slice(&text).map_err(|e| e.to_string())
}

/// Whether a bundle's metadata marks it SYNTHETIC (top level or `dem_provenance`); unreadable metadata is not.
#[must_use]
pub fn is_synthetic_bundle(bundle: &Path) -> bool {
    load_meta(bundle).is_ok_and(|m| {
        m.get("synthetic").is_some_and(py::truthy)
            || m.get("dem_provenance")
                .and_then(|p| p.get("synthetic"))
                .is_some_and(py::truthy)
    })
}

/// The real bundle directories under `root` (a directory holding `metadata.json`), sorted by path; SYNTHETIC ones
/// are excluded.
#[must_use]
pub fn list_site_bundles(root: &Path) -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = std::fs::read_dir(root)
        .map(|rd| {
            rd.filter_map(Result::ok)
                // glob's `*` skips dot entries
                .filter(|e| !e.file_name().to_string_lossy().starts_with('.'))
                .map(|e| e.path())
                .filter(|p| p.is_dir() && p.join("metadata.json").exists())
                .collect()
        })
        .unwrap_or_default();
    dirs.sort_by(|a, b| {
        a.as_os_str()
            .as_encoded_bytes()
            .cmp(b.as_os_str().as_encoded_bytes())
    });
    dirs.retain(|d| !is_synthetic_bundle(d));
    dirs
}

/// The "About this DEM" pane: the bundle's region and its verbatim provenance.
///
/// # Errors
/// Unreadable metadata, or no grid cell size.
pub fn provenance_pane(bundle: &Path) -> Result<Map<String, Value>, String> {
    let meta = load_meta(bundle)?;
    let prov = meta
        .get("dem_provenance")
        .filter(|p| py::truthy(p))
        .cloned()
        .unwrap_or_else(|| json!({}));
    let s = |v: &Value, k: &str| v.get(k).map_or_else(String::new, py::str_of);
    let cell = meta["grid"]
        .get("cell_m")
        .and_then(py::float)
        .filter(|c| c.is_finite());
    let mut out = Map::new();
    out.insert(
        "name".into(),
        json!(bundle.file_name().map(|n| n.to_string_lossy().into_owned())),
    );
    out.insert("region".into(), json!(s(&meta, "region")));
    out.insert("source".into(), json!(s(&prov, "source")));
    out.insert("citation".into(), json!(s(&prov, "citation")));
    out.insert("frame".into(), json!(s(&prov, "frame")));
    out.insert("license_basis".into(), json!(s(&prov, "license_basis")));
    out.insert(
        "cell_m".into(),
        json!(cell.ok_or_else(|| format!("{}: no grid cell_m", bundle.display()))?),
    );
    Ok(out)
}

fn has_heightmap(bundle: &Path) -> bool {
    bundle.join("heightmap.rf32").is_file()
}

const PANE_KEYS: [&str; 6] = [
    "region",
    "cell_m",
    "source",
    "citation",
    "frame",
    "license_basis",
];

/// The site dropdown: one row per real bundle with its citation; `default` marks the real-mode default site.
///
/// # Errors
/// A bundle whose pane cannot be read.
pub fn list_real_bundles(root: &Path) -> Result<Vec<Value>, String> {
    list_site_bundles(root)
        .iter()
        .map(|b| {
            let pane = provenance_pane(b)?;
            let mut row = Map::new();
            row.insert("name".into(), pane["name"].clone());
            for k in PANE_KEYS {
                row.insert(k.into(), pane[k].clone());
            }
            row.insert("has_heightmap".into(), json!(has_heightmap(b)));
            row.insert("synthetic".into(), json!(false));
            row.insert(
                "default".into(),
                json!(pane["name"] == crate::protocol::DEFAULT_SITE),
            );
            Ok(Value::Object(row))
        })
        .collect()
}

/// numpy `linspace(0, len - 1, n).round()`: `n` picks keeping both ends, ties to even.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)] // grid indices
fn picks(len: usize, n: usize) -> Vec<usize> {
    let n = n.min(len);
    if n < 2 {
        return vec![0; n];
    }
    let step = (len - 1) as f64 / (n - 1) as f64;
    (0..n)
        .map(|i| {
            if i == n - 1 {
                len - 1
            } else {
                (i as f64 * step).round_ties_even() as usize
            }
        })
        .collect()
}

/// A real heightmap decimated to at most `n` x `n` by even index picks (corners kept, no invented heights), with
/// the full map's real statistics and the site's verbatim citation. A metadata-only bundle has an empty grid.
///
/// # Errors
/// A path-escaping or SYNTHETIC site, or one not under `root`.
pub fn real_heightmap_preview(
    site: &str,
    root: &Path,
    n: usize,
) -> Result<Map<String, Value>, PreviewError> {
    let bare = site.trim();
    if bare.is_empty() || bare.contains('/') || bare.contains('\\') || bare.starts_with('.') {
        return Err(PreviewError::Invalid(format!(
            "site must be a bare bundle name, got {}",
            stewie_twin::pyjson::repr_str(site)
        )));
    }
    let bundle = root.join(bare);
    let quoted = stewie_twin::pyjson::repr_str(bare);
    if !bundle.join("metadata.json").is_file() {
        return Err(PreviewError::NotFound(format!(
            "real site {quoted} not found under {}",
            root.display()
        )));
    }
    if is_synthetic_bundle(&bundle) {
        return Err(PreviewError::Invalid(format!(
            "site {quoted} is a SYNTHETIC bundle — refused on the real-preview path"
        )));
    }
    let pane = provenance_pane(&bundle).map_err(PreviewError::Invalid)?;
    let mut out = Map::new();
    out.insert("site".into(), pane["name"].clone());
    out.insert("synthetic".into(), json!(false));
    for k in PANE_KEYS {
        out.insert(k.into(), pane[k].clone());
    }
    out.insert("has_heightmap".into(), json!(has_heightmap(&bundle)));
    out.insert("n".into(), json!(0));
    out.insert("z".into(), json!([]));
    if !has_heightmap(&bundle) {
        out.insert(
            "note".into(),
            json!("metadata-only bundle (no heightmap.rf32) — no mesh preview for this tile"),
        );
        return Ok(out);
    }
    let meta = load_meta(&bundle).map_err(PreviewError::Invalid)?;
    let dim = |k: &str| {
        meta["grid"][k]
            .as_u64()
            .and_then(|x| usize::try_from(x).ok())
    };
    let (Some(w), Some(h)) = (dim("width"), dim("height")) else {
        return Err(PreviewError::Invalid(
            "metadata grid has no width/height".to_owned(),
        ));
    };
    let raw = std::fs::read(bundle.join("heightmap.rf32"))
        .map_err(|e| PreviewError::Invalid(e.to_string()))?;
    if raw.len() != w * h * 4 {
        return Err(PreviewError::Invalid(format!(
            "cannot reshape array of size {} into shape ({h},{w})",
            raw.len() / 4
        )));
    }
    let z: Vec<f64> = raw
        .chunks_exact(4)
        .map(|b| f64::from(f32::from_le_bytes([b[0], b[1], b[2], b[3]])))
        .collect();
    let (rows, cols) = if h <= n && w <= n {
        ((0..h).collect(), (0..w).collect())
    } else {
        (picks(h, n), picks(w, n))
    };
    let grid: Vec<f64> = rows
        .iter()
        .flat_map(|r| cols.iter().map(|c| z[r * w + c]).collect::<Vec<_>>())
        .collect();
    let lo = |v: &[f64]| v.iter().copied().fold(f64::INFINITY, f64::min);
    let hi = |v: &[f64]| v.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let (full_min, full_max) = (lo(&z), hi(&z));
    out.insert("n".into(), json!(rows.len()));
    out.insert("ncols".into(), json!(cols.len()));
    out.insert("z_min".into(), json!(lo(&grid)));
    out.insert("z_max".into(), json!(hi(&grid)));
    out.insert("z".into(), json!(grid));
    out.insert("full_min_m".into(), json!(full_min));
    out.insert("full_max_m".into(), json!(full_max));
    out.insert("relief_m".into(), json!(full_max - full_min));
    out.insert("full_shape".into(), json!([h, w]));
    Ok(out)
}

#[cfg(test)]
mod tests {
    #[test]
    fn picks_are_numpys_linspace_rounded() {
        // SYNTHETIC lengths (labelled): numpy.linspace(0, 9, 4).round() = [0, 3, 6, 9]; (0, 4, 4) = [0, 1, 3, 4]
        assert_eq!(super::picks(10, 4), vec![0, 3, 6, 9]);
        assert_eq!(super::picks(5, 4), vec![0, 1, 3, 4]);
        // linspace(0, 6, 5) = [0, 1.5, 3, 4.5, 6]: numpy rounds the ties to even
        assert_eq!(super::picks(7, 5), vec![0, 2, 3, 4, 6]);
    }

    #[test]
    fn a_synthetic_bundle_is_never_listed_or_previewed() {
        // SYNTHETIC bundles (labelled): a temporary root with one marked each way and one real-shaped
        let root =
            std::env::temp_dir().join(format!("stewie-stream-previews-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        let meta = |name: &str, doc: &str| {
            std::fs::create_dir_all(root.join(name)).unwrap();
            std::fs::write(root.join(name).join("metadata.json"), doc).unwrap();
        };
        meta(
            "procgen_top",
            r#"{"synthetic": true, "grid": {"cell_m": 1.0}}"#,
        );
        meta(
            "procgen_prov",
            r#"{"dem_provenance": {"synthetic": 1, "citation": null}, "grid": {"cell_m": 1.0}}"#,
        );
        meta(
            "tile",
            r#"{"region": "R", "dem_provenance": {"source": "S", "citation": "C"}, "grid": {"cell_m": 5}}"#,
        );
        meta(".hidden", r#"{"grid": {"cell_m": 1.0}}"#);
        let names: Vec<String> = super::list_site_bundles(&root)
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        assert_eq!(names, ["tile"]);
        for name in ["procgen_top", "procgen_prov"] {
            assert_eq!(
                super::real_heightmap_preview(name, &root, 128),
                Err(super::PreviewError::Invalid(format!(
                    "site '{name}' is a SYNTHETIC bundle — refused on the real-preview path"
                )))
            );
        }
        let pane = super::provenance_pane(&root.join("tile")).unwrap();
        assert_eq!(
            (pane["citation"].as_str(), pane["cell_m"].as_f64()),
            (Some("C"), Some(5.0))
        );
        std::fs::remove_dir_all(&root).unwrap();
    }
}
