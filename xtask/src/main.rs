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

fn main() -> ExitCode {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("..");
    match std::env::args().nth(1).as_deref() {
        Some("no-stubs") => {}
        Some("wasm-golden") => return wasm_golden(&root),
        _ => {
            eprintln!("usage: cargo run -p xtask -- <no-stubs | wasm-golden>");
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
