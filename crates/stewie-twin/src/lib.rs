//! The twin's durable records (RW-21). Journals written by the Python twin must replay and verify here
//! byte for byte, so every hash is taken over [`pyjson::dumps`], a port of Python's
//! `json.dumps(obj, sort_keys=True)`.

pub mod journal;
pub mod numpy;
pub mod pyjson;
pub mod terrain_memory;
pub mod traffic_memory;
pub mod twin_store;
pub mod world_log;

use std::fmt;

#[derive(Debug)]
pub enum TwinError {
    Io(std::io::Error),
    /// A record before the final line does not parse: real history loss, never skipped.
    InteriorCorruption {
        what: String,
        line: usize,
    },
    /// A recomputed hash or link disagrees with the record: the journal was altered.
    Tampered(String),
    Invalid(String),
}

impl fmt::Display for TwinError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TwinError::Io(e) => write!(f, "{e}"),
            TwinError::InteriorCorruption { what, line } => write!(
                f,
                "{what} corrupt at interior line {line} (not the tail); refusing a partial silent restore"
            ),
            TwinError::Tampered(m) => {
                write!(f, "replay hash mismatch, the journal was altered: {m}")
            }
            TwinError::Invalid(m) => write!(f, "{m}"),
        }
    }
}

impl std::error::Error for TwinError {}

impl From<std::io::Error> for TwinError {
    fn from(e: std::io::Error) -> Self {
        TwinError::Io(e)
    }
}

/// Write `bytes` to `<path>.part`, sync, and rename over `path` (creating its directory): the Python twin's
/// atomic save, so a crash or a concurrent writer never leaves a torn file at the canonical path.
///
/// # Errors
/// An I/O failure.
pub fn write_atomic(path: &std::path::Path, bytes: &[u8]) -> Result<(), TwinError> {
    use std::io::Write as _;
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(TwinError::Io)?;
    }
    let tmp = std::path::PathBuf::from(format!("{}.part", path.display()));
    let mut f = std::fs::File::create(&tmp).map_err(TwinError::Io)?;
    f.write_all(bytes).map_err(TwinError::Io)?;
    f.sync_all().map_err(TwinError::Io)?;
    std::fs::rename(&tmp, path).map_err(TwinError::Io)
}

/// The raw persisted bytes at `path` (or `None`), taken before a mutation so a world-log commit that then
/// fails can be compensated by [`restore_file`] (DT-03).
///
/// # Errors
/// An I/O failure.
pub fn snapshot_file(path: &std::path::Path) -> Result<Option<Vec<u8>>, TwinError> {
    if path.exists() {
        std::fs::read(path).map(Some).map_err(TwinError::Io)
    } else {
        Ok(None)
    }
}

/// Restore `path` to a [`snapshot_file`] snapshot atomically; `None` removes it.
///
/// # Errors
/// An I/O failure.
pub fn restore_file(path: &std::path::Path, snapshot: Option<&[u8]>) -> Result<(), TwinError> {
    match snapshot {
        Some(bytes) => write_atomic(path, bytes),
        None if path.exists() => std::fs::remove_file(path).map_err(TwinError::Io),
        None => Ok(()),
    }
}
