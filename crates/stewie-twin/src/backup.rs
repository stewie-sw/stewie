//! Twin backups (Python `stewie.twin.backup`, W-2/W-3): a full restorable snapshot of the observed-terrain
//! store (base, cell, event log, content checksum) per version; a version retention ladder; and a mirror of
//! the journal and snapshots to a second location, from which the world cold-restores alone.
//!
//! The checksum is `sha256(base f64 bytes + cell f64 bytes + event-log JSON bytes)`, the JSON being exactly the
//! stored bytes; a snapshot is written with Python's JSON form (`pyjson`), so the Python verifies it too.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::Value;

use crate::numpy::{self, Array};
use crate::twin_store::TwinStore;
use crate::world_log::sha256_hex;
use crate::{TwinError, pyjson};

fn bad(m: impl Into<String>) -> TwinError {
    TwinError::Invalid(m.into())
}

fn checksum(base: &[f64], cell_m: f64, events_json: &[u8]) -> String {
    let base_bytes: Vec<u8> = base.iter().flat_map(|v| v.to_le_bytes()).collect();
    sha256_hex(&[&base_bytes, &cell_m.to_le_bytes(), events_json])
}

/// The arrays of a snapshot of `tw`, in the Python's order.
pub(crate) fn snapshot_arrays(tw: &TwinStore) -> Result<Vec<(&'static str, Array)>, TwinError> {
    let events = pyjson::dumps(&Value::Array(tw.events().to_vec()))?.into_bytes();
    let (rows, cols) = tw.shape();
    let sum = checksum(tw.base(), tw.cell_m(), &events);
    Ok(vec![
        (
            "base",
            Array::F64 {
                shape: vec![rows, cols],
                data: tw.base().to_vec(),
            },
        ),
        (
            "cell_m",
            Array::F64 {
                shape: vec![1],
                data: vec![tw.cell_m()],
            },
        ),
        (
            "events",
            Array::U8 {
                shape: vec![events.len()],
                data: events,
            },
        ),
        (
            "checksum",
            Array::U8 {
                shape: vec![sum.len()],
                data: sum.into_bytes(),
            },
        ),
    ])
}

/// `<dir>/twin_v{version:06}.npz` and its dot-prefixed temporary (outside the retention glob).
pub(crate) fn snapshot_paths(dir: &Path, version: u64) -> (PathBuf, PathBuf) {
    let name = format!("twin_v{version:06}.npz");
    (dir.join(&name), dir.join(format!(".{name}.tmp")))
}

pub(crate) fn write_arrays(
    path: &Path,
    tmp: &Path,
    arrays: &[(&str, Array)],
) -> Result<(), TwinError> {
    let mut buf = std::io::Cursor::new(Vec::new());
    numpy::write_npz(&mut buf, arrays)?;
    crate::write_atomic_via(path, tmp, &buf.into_inner())
}

/// Write a full restorable snapshot of `tw` into `dir`, named by version. Returns its path.
///
/// # Errors
/// An I/O failure.
pub fn snapshot(tw: &TwinStore, dir: &Path) -> Result<PathBuf, TwinError> {
    let (path, tmp) = snapshot_paths(dir, tw.version());
    write_arrays(&path, &tmp, &snapshot_arrays(tw)?)?;
    Ok(path)
}

/// Restore a snapshot (Rust- or Python-written, stored or deflated): the checksum, when present, must match,
/// and every event replays through the hash-verified edit path.
///
/// # Errors
/// A malformed file, a checksum mismatch, or an event that fails verification.
pub fn restore(path: &Path) -> Result<TwinStore, TwinError> {
    let a = numpy::read_npz(fs::File::open(path).map_err(TwinError::Io)?)?;
    let (
        Some(Array::F64 { shape, data: base }),
        Some(Array::F64 { data: cell, .. }),
        Some(Array::U8 { data: events, .. }),
    ) = (a.get("base"), a.get("cell_m"), a.get("events"))
    else {
        return Err(bad(format!("{}: not a twin snapshot", path.display())));
    };
    let (&[rows, cols], Some(&cell_m)) = (shape.as_slice(), cell.first()) else {
        return Err(bad(format!(
            "{}: base must be 2-D with a cell size",
            path.display()
        )));
    };
    // a snapshot written before the checksum existed carries none and is not refused
    if let Some(Array::U8 { data: want, .. }) = a.get("checksum")
        && checksum(base, cell_m, events).as_bytes() != want.as_slice()
    {
        return Err(bad(
            "twin snapshot integrity check failed: checksum mismatch (base/events corrupted)",
        ));
    }
    let log: Vec<Value> = serde_json::from_slice(events).map_err(|e| bad(e.to_string()))?;
    let mut tw = TwinStore::new(base.clone(), rows, cols, cell_m)?;
    for ev in &log {
        tw.apply_event(ev)?;
    }
    Ok(tw)
}

/// The version in a `twin_v{n}.npz` name.
pub(crate) fn snapshot_version(name: &str) -> Option<u64> {
    name.strip_prefix("twin_v")?.split('.').next()?.parse().ok()
}

/// Keep the newest `keep_recent` snapshots plus every `ladder`-th version; delete the rest. Returns the kept
/// names in version order.
///
/// # Errors
/// An I/O failure, or a zero ladder.
pub fn apply_retention(
    dir: &Path,
    keep_recent: usize,
    ladder: u64,
) -> Result<Vec<String>, TwinError> {
    if ladder == 0 {
        return Err(bad("ladder must be positive"));
    }
    let mut named: Vec<(u64, String)> = Vec::new();
    for e in fs::read_dir(dir).map_err(TwinError::Io)? {
        let name = e
            .map_err(TwinError::Io)?
            .file_name()
            .to_string_lossy()
            .into_owned();
        if let Some(v) = snapshot_version(&name) {
            named.push((v, name));
        }
    }
    named.sort();
    let recent_from = named.len().saturating_sub(keep_recent);
    let mut kept = Vec::new();
    for (k, (v, name)) in named.into_iter().enumerate() {
        if k >= recent_from || v % ladder == 0 {
            kept.push(name);
        } else {
            fs::remove_file(dir.join(&name)).map_err(TwinError::Io)?;
        }
    }
    Ok(kept)
}

fn copy_tree(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for e in fs::read_dir(src)? {
        let e = e?;
        let to = dst.join(e.file_name());
        if e.file_type()?.is_dir() {
            copy_tree(&e.path(), &to)?;
        } else {
            fs::copy(e.path(), to)?;
        }
    }
    Ok(())
}

/// Mirror `twin.journal`, `snapshots/` and `twin/` from `data_dir` into `dest` (a directory is replaced, so
/// removed files do not linger), retrying a transient I/O failure twice. Returns the items mirrored.
///
/// # Errors
/// Nothing to replicate, or a failure that persists through three attempts.
pub fn replicate(data_dir: &Path, dest: &Path) -> Result<Vec<String>, TwinError> {
    let items: Vec<&str> = ["twin.journal", "snapshots", "twin"]
        .into_iter()
        .filter(|p| data_dir.join(p).exists())
        .collect();
    if items.is_empty() {
        return Err(bad(format!(
            "nothing to replicate in {}",
            data_dir.display()
        )));
    }
    let attempt = || -> std::io::Result<()> {
        fs::create_dir_all(dest)?;
        for name in &items {
            let (from, to) = (data_dir.join(name), dest.join(name));
            if from.is_dir() {
                if to.exists() {
                    fs::remove_dir_all(&to)?;
                }
                copy_tree(&from, &to)?;
            } else {
                fs::copy(&from, &to)?;
            }
        }
        Ok(())
    };
    let mut last = None;
    for _ in 0..3 {
        match attempt() {
            Ok(()) => return Ok(items.iter().map(|s| (*s).to_owned()).collect()),
            Err(e) => last = Some(e),
        }
    }
    Err(TwinError::Io(last.unwrap_or_else(|| {
        std::io::Error::other("replicate failed")
    })))
}
