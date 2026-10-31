//! The twin's durable records (RW-21). Journals written by the Python twin must replay and verify here
//! byte for byte, so every hash is taken over [`pyjson::dumps`], a port of Python's
//! `json.dumps(obj, sort_keys=True)`.

pub mod journal;
pub mod numpy;
pub mod pyjson;
pub mod terrain_memory;
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
