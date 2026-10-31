//! Golden fixtures written by the Python oracle (`code/oracle/build_fixtures.py`).
//!
//! Each fixture is `<name>.payload.json` plus `<name>.meta.json`. Loading recomputes the SHA-256 of the
//! payload bytes and of every real source file the oracle read, so a hand-edited payload or a changed
//! input (a re-imported DEM, for example) is an error rather than a silent test against stale truth.

use std::collections::BTreeMap;
use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;
use sha2::{Digest, Sha256};

/// A verified fixture.
#[derive(Debug)]
pub struct Fixture {
    pub name: String,
    pub generator: String,
    pub payload: serde_json::Value,
}

/// Why a fixture could not be trusted.
#[derive(Debug)]
pub enum Error {
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    Json {
        path: PathBuf,
        source: serde_json::Error,
    },
    PayloadHash {
        fixture: String,
        expected: String,
        actual: String,
    },
    StaleSource {
        fixture: String,
        source: String,
        expected: String,
        actual: String,
    },
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Io { path, source } => write!(f, "{}: {source}", path.display()),
            Error::Json { path, source } => write!(f, "{}: {source}", path.display()),
            Error::PayloadHash {
                fixture,
                expected,
                actual,
            } => {
                write!(
                    f,
                    "fixture {fixture}: payload sha256 {actual} != recorded {expected}"
                )
            }
            Error::StaleSource {
                fixture,
                source,
                expected,
                actual,
            } => write!(
                f,
                "fixture {fixture} is stale: {source} sha256 {actual} != recorded {expected}; rerun `just oracle`"
            ),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Deserialize)]
struct Meta {
    fixture: String,
    generator: String,
    payload_sha256: String,
    sources: BTreeMap<String, String>,
}

/// The repository root (`stewie/code`), against which fixture sources are resolved.
#[must_use]
pub fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

/// Load and verify a fixture from this crate's `fixtures/` directory.
///
/// # Errors
/// Any I/O or JSON failure, a payload hash mismatch, or a source file whose hash has changed.
pub fn load(name: &str) -> Result<Fixture, Error> {
    load_from(
        &Path::new(env!("CARGO_MANIFEST_DIR")).join("fixtures"),
        name,
    )
}

/// Load and verify a fixture from `dir`, resolving its sources against [`repo_root`].
///
/// # Errors
/// As [`load`].
pub fn load_from(dir: &Path, name: &str) -> Result<Fixture, Error> {
    let meta_path = dir.join(format!("{name}.meta.json"));
    let meta: Meta = serde_json::from_slice(&read(&meta_path)?).map_err(|source| Error::Json {
        path: meta_path.clone(),
        source,
    })?;
    let payload_path = dir.join(format!("{name}.payload.json"));
    let bytes = read(&payload_path)?;
    let actual = sha256_hex(&bytes);
    if actual != meta.payload_sha256 {
        return Err(Error::PayloadHash {
            fixture: meta.fixture,
            expected: meta.payload_sha256,
            actual,
        });
    }
    let root = repo_root();
    for (rel, expected) in &meta.sources {
        let actual = sha256_hex(&read(&root.join(rel))?);
        if &actual != expected {
            return Err(Error::StaleSource {
                fixture: meta.fixture,
                source: rel.clone(),
                expected: expected.clone(),
                actual,
            });
        }
    }
    let payload = serde_json::from_slice(&bytes).map_err(|source| Error::Json {
        path: payload_path,
        source,
    })?;
    Ok(Fixture {
        name: meta.fixture,
        generator: meta.generator,
        payload,
    })
}

fn read(path: &Path) -> Result<Vec<u8>, Error> {
    fs::read(path).map_err(|source| Error::Io {
        path: path.to_path_buf(),
        source,
    })
}

fn sha256_hex(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::with_capacity(64), |mut s, b| {
            use fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        })
}
