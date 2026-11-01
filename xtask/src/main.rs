//! `cargo run -p xtask -- no-stubs`: fail when Rust or web sources carry a stub or placeholder marker.

use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

/// Markers that mean "not really implemented". Built with `concat!` so this file never matches itself.
const MARKERS: [&str; 4] = [
    concat!("to", "do!("),
    concat!("unimpl", "emented!("),
    concat!("TO", "DO"),
    concat!("FIX", "ME"),
];
/// Top-level directories holding Rust and web sources; Python is out of scope until it is retired.
const ROOTS: [&str; 3] = ["crates", "xtask", "web"];
const SKIP_DIRS: [&str; 4] = ["target", "node_modules", "dist", ".git"];
const EXTS: [&str; 5] = ["rs", "toml", "ts", "tsx", "js"];

/// Write the native R10 golden scenario that the WASM build must reproduce.
fn wasm_golden(root: &Path) -> ExitCode {
    let out =
        stewie_wasm::scenario::Inputs::from_repo().and_then(|i| stewie_wasm::scenario::run(&i));
    match out.and_then(|o| serde_json::to_string_pretty(&o).map_err(|e| e.to_string())) {
        Ok(json) => {
            let path = root.join("crates/stewie-wasm/golden/scenario.json");
            if let Err(e) = fs::write(&path, json + "\n") {
                eprintln!("{}: {e}", path.display());
                return ExitCode::FAILURE;
            }
            println!("{}", path.display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("wasm-golden: {e}");
            ExitCode::FAILURE
        }
    }
}

/// Real engine output for web tests: windows at three catalog sites, each on its own tile over `LDEM_16`,
/// plus the Haworth site on `LDEM_16` alone (a different terrain stack).
fn web_fixtures(root: &Path) -> ExitCode {
    match comparison(root) {
        Ok(json) => {
            let path = root.join("web/src/fixtures/engine_comparison.json");
            if let Err(e) = fs::create_dir_all(path.parent().unwrap_or(root))
                .and_then(|()| fs::write(&path, json + "\n"))
            {
                eprintln!("{}: {e}", path.display());
                return ExitCode::FAILURE;
            }
            println!("{}", path.display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("web-fixtures: {e}");
            ExitCode::FAILURE
        }
    }
}

fn comparison(root: &Path) -> Result<String, String> {
    let read = |p: &str| fs::read(root.join(p)).map_err(|e| format!("{p}: {e}"));
    let text = |p: &str| fs::read_to_string(root.join(p)).map_err(|e| format!("{p}: {e}"));
    let bodies = text("crates/stewie-contracts/fixtures/bodies.json")?;
    let sites: serde_json::Value =
        serde_json::from_str(&text("crates/stewie-contracts/fixtures/sites.json")?)
            .map_err(|e| e.to_string())?;
    let (label, img) = (
        text(".cache/terrain/ldem_16.lbl")?,
        read(".cache/terrain/ldem_16.img")?,
    );
    let (start, end) = ("2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z");
    let mut out = Vec::new();
    for (site, tile) in [
        ("haworth", Some("haworth_10km_5m")),
        ("shackleton_rim", Some("shackleton_rim_10km_5m")),
        ("malapert_massif", Some("malapert_massif_10km_5m")),
        ("haworth", None),
    ] {
        let mut e = stewie_wasm::Engine::new(&bodies)?;
        if let Some(t) = tile {
            let dir = format!("samples/lunar_dem/{t}");
            e.add_tile(
                1,
                t,
                &text(&format!("{dir}/metadata.json"))?,
                &read(&format!("{dir}/heightmap.rf32"))?,
            )?;
        }
        e.add_global(9, "ldem_16", &label, &img)?;
        let (lat, lon) = (
            sites[site]["lat_deg"].as_f64().ok_or("site lat")?,
            sites[site]["lon_deg"].as_f64().ok_or("site lon")?,
        );
        let h = e.horizon(lat, lon, 720, 200_000.0, 50.0, 1.5)?;
        let mut windows = serde_json::Map::new();
        for body in ["SUN", "EARTH"] {
            let w = e.windows(body, lat, lon, start, end, 600.0, 1.5, &h)?;
            let t0 = w.first().map_or(0.0, |x| x.start_tdb);
            windows.insert(
                body.into(),
                w.iter()
                    .map(|x| serde_json::json!({"start_s": x.start_tdb - t0, "end_s": x.end_tdb - t0, "verdict": format!("{:?}", x.verdict)}))
                    .collect(),
            );
        }
        out.push(serde_json::json!({
            "name": tile.map_or_else(|| format!("{site} (LDEM_16 only)"), |t| format!("{site} ({t} + LDEM_16)")),
            "site": site, "lat_deg": lat, "lon_deg": lon, "sources": h.sources, "stack_signature": e.stack_signature(), "windows": windows,
            "complete_azimuths": h.complete.iter().filter(|c| **c).count(), "n_az": h.complete.len(),
        }));
    }
    let doc = serde_json::json!({"start_utc": start, "end_utc": end, "generator": "cargo run -p xtask -- web-fixtures", "scenarios": out});
    serde_json::to_string_pretty(&doc).map_err(|e| e.to_string())
}

#[derive(Debug)]
struct Finding {
    path: PathBuf,
    line: usize,
    marker: &'static str,
}

impl fmt::Display for Finding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}:{}: stub marker `{}`",
            self.path.display(),
            self.line,
            self.marker
        )
    }
}

fn scan(root: &Path) -> Vec<Finding> {
    let mut out = Vec::new();
    for r in ROOTS {
        walk(&root.join(r), &mut out);
    }
    out
}

fn walk(dir: &Path, out: &mut Vec<Finding>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let name = entry.file_name();
        if path.is_dir() {
            if !SKIP_DIRS.iter().any(|s| name == *s) {
                walk(&path, out);
            }
        } else if path
            .extension()
            .and_then(|e| e.to_str())
            .is_some_and(|e| EXTS.contains(&e))
        {
            let Ok(text) = fs::read_to_string(&path) else {
                continue;
            };
            for (i, line) in text.lines().enumerate() {
                for marker in MARKERS {
                    if line.contains(marker) {
                        out.push(Finding {
                            path: path.clone(),
                            line: i + 1,
                            marker,
                        });
                    }
                }
            }
        }
    }
}

/// RW-71c: the polar map's display tiles, rendered from the real 240 m south polar tier into the device package
/// (run after `pipeline/build_package.py`).
fn display_tiles(root: &Path) -> ExitCode {
    let reg: serde_json::Value = match serde_json::from_str(include_str!(
        "../../crates/stewie-contracts/fixtures/bodies.json"
    )) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("bodies.json: {e}");
            return ExitCode::FAILURE;
        }
    };
    let Some(sphere) = reg["moon"]["ellipsoid_radius_m"]
        .as_f64()
        .and_then(|r| lunar_frames::Sphere::new(r).ok())
    else {
        eprintln!("bodies.json: no moon radius");
        return ExitCode::FAILURE;
    };
    let terrain = root.join(".cache/terrain");
    let out = root.join(".cache/package/south_polar_sites/display");
    match stewie_package::display::write_polar_tiles(
        (
            &terrain.join("ldem_75s_240m.img"),
            &terrain.join("ldem_75s_240m.lbl"),
        ),
        sphere,
        "IAU_2015:30135",
        &out,
    ) {
        Ok(n) => println!("{n} tiles in {}", out.display()),
        Err(e) => {
            eprintln!("display tiles: {e}");
            return ExitCode::FAILURE;
        }
    }
    // the web map's grid fixture: the index without hashes, and where each catalog site falls
    let fixture = fs::read_to_string(out.join("tiles.json"))
        .map_err(|e| e.to_string())
        .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).map_err(|e| e.to_string()))
        .and_then(|index| {
            let sites: serde_json::Value = serde_json::from_str(include_str!(
                "../../crates/stewie-contracts/fixtures/sites.json"
            ))
            .map_err(|e| e.to_string())?;
            stewie_package::display::grid_fixture(
                &index,
                &lunar_frames::PolarStereographic::south(sphere),
                &sites,
            )
        })
        .and_then(|v| serde_json::to_string_pretty(&v).map_err(|e| e.to_string()));
    let path = root.join("web/src/fixtures/display_grid.json");
    match fixture.and_then(|t| fs::write(&path, t + "\n").map_err(|e| e.to_string())) {
        Ok(()) => {
            println!("{}", path.display());
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("display grid fixture: {e}");
            ExitCode::FAILURE
        }
    }
}

fn main() -> ExitCode {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    match std::env::args().nth(1).as_deref() {
        Some("no-stubs") => {}
        Some("wasm-golden") => return wasm_golden(&root),
        Some("web-fixtures") => return web_fixtures(&root),
        Some("display-tiles") => return display_tiles(&root),
        _ => {
            eprintln!(
                "usage: cargo run -p xtask -- <no-stubs | wasm-golden | web-fixtures | display-tiles>"
            );
            return ExitCode::FAILURE;
        }
    }
    let findings = scan(&root);
    for f in &findings {
        eprintln!("{f}");
    }
    if findings.is_empty() {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;

    // Synthetic test trees (labelled): small source files written to a temp dir to exercise the scanner.
    fn tree(name: &str, files: &[(&str, &str)]) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("xtask-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        for (rel, body) in files {
            let p = dir.join(rel);
            fs::create_dir_all(p.parent().unwrap()).unwrap();
            fs::write(p, body).unwrap();
        }
        dir
    }

    #[test]
    fn clean_tree_has_no_findings() {
        let d = tree(
            "clean",
            &[("crates/a/src/lib.rs", "pub fn f() -> u8 { 1 }\n")],
        );
        assert!(scan(&d).is_empty());
    }

    #[test]
    fn todo_macro_is_found_with_location() {
        let body = format!("fn f() {{ {}\"later\") }}\n", concat!("to", "do!("));
        let d = tree("todo", &[("crates/a/src/lib.rs", &body)]);
        let found = scan(&d);
        assert_eq!(found.len(), 1);
        assert!(found[0].to_string().contains("lib.rs:1"));
    }

    #[test]
    fn every_marker_kind_is_found() {
        let body = [
            concat!("unimpl", "emented!()"),
            concat!("// TO", "DO x"),
            concat!("// FIX", "ME y"),
        ]
        .join("\n");
        let d = tree(
            "markers",
            &[
                ("crates/a/src/lib.rs", &body),
                ("web/src/app.tsx", concat!("// TO", "DO z")),
            ],
        );
        assert_eq!(scan(&d).len(), 4);
    }

    #[test]
    fn build_and_vendor_dirs_are_skipped() {
        let m = concat!("to", "do!()");
        let d = tree(
            "skip",
            &[
                ("target/debug/x.rs", m),
                ("web/node_modules/p/i.ts", m),
                ("crates/a/src/lib.rs", "pub struct S;\n"),
            ],
        );
        assert!(scan(&d).is_empty());
    }

    #[test]
    fn python_and_docs_are_out_of_scope() {
        let m = concat!("# TO", "DO");
        let d = tree("scope", &[("stewie/x.py", m), ("docs/a.md", m)]);
        assert!(scan(&d).is_empty());
    }
}
