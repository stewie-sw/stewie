//! JSON-lines journal replay with tail repair, and durable append (Python `stewie.twin.journal_io`).
//!
//! A crash mid-fsync tears only the final line. Replay applies every complete record, tolerates exactly
//! one torn tail, and refuses corruption anywhere else (that is real history loss). Before the writer is
//! re-armed, the tail is repaired: a torn final line is truncated away (it was never acknowledged), and a
//! complete final record missing its newline gets one, so the next append starts its own line instead of
//! grafting onto a partial record. The original bytes are first kept in an fsynced recovery file.

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::Path;

use serde_json::Value;

use crate::{TwinError, pyjson};

/// Replay `path` through `apply`, then repair its tail. Returns the records applied (0 for no file).
/// Requires exclusive writer access.
///
/// # Errors
/// I/O failure; [`TwinError::InteriorCorruption`] for an unparsable line before the tail (the file is not
/// modified); any error `apply` returns.
pub fn replay(
    path: &Path,
    what: &str,
    mut apply: impl FnMut(&Value) -> Result<(), TwinError>,
) -> Result<usize, TwinError> {
    if !path.exists() {
        return Ok(0);
    }
    let original = fs::read(path)?;
    let lines: Vec<&[u8]> = original.split_inclusive(|&b| b == b'\n').collect();
    let blank = |l: &[u8]| l.iter().all(u8::is_ascii_whitespace);
    let (mut applied, mut good_end) = (0, 0);
    for (i, raw) in lines.iter().enumerate() {
        if blank(raw) {
            good_end += raw.len();
            continue;
        }
        match serde_json::from_slice::<Value>(raw) {
            Ok(rec) => {
                apply(&rec)?;
                applied += 1;
                good_end += raw.len();
            }
            Err(_) if lines[i + 1..].iter().all(|l| blank(l)) => break,
            Err(_) => {
                return Err(TwinError::InteriorCorruption {
                    what: what.to_owned(),
                    line: i,
                });
            }
        }
    }
    let torn = good_end < original.len();
    if torn || (!original.is_empty() && !original.ends_with(b"\n")) {
        keep_recovery_copy(path, &original)?;
        let mut f = OpenOptions::new().write(true).open(path)?;
        if torn {
            f.set_len(good_end as u64)?;
        } else {
            use std::io::Seek;
            f.seek(std::io::SeekFrom::End(0))?;
            f.write_all(b"\n")?;
        }
        f.sync_all()?;
    }
    Ok(applied)
}

/// Write the original bytes to `<name>.recovery-<pid>-<nanos>` beside the journal, fsync it and the
/// directory, before any repair touches the journal.
fn keep_recovery_copy(path: &Path, original: &[u8]) -> Result<(), TwinError> {
    let dir = path
        .parent()
        .filter(|d| !d.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    let name = format!(
        "{}.recovery-{}-{nanos}",
        path.file_name()
            .map_or_else(String::new, |n| n.to_string_lossy().into_owned()),
        std::process::id()
    );
    let mut backup = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(dir.join(name))?;
    backup.write_all(original)?;
    backup.sync_all()?;
    File::open(dir)?.sync_all()?;
    Ok(())
}

/// Durably append one record (`pyjson::dumps` + newline, fsynced) before the caller acknowledges it.
///
/// # Errors
/// I/O failure, or a record [`pyjson::dumps`] refuses.
pub fn append(path: &Path, record: &Value) -> Result<(), TwinError> {
    let line = pyjson::dumps(record)? + "\n";
    let mut f = OpenOptions::new().create(true).append(true).open(path)?;
    f.write_all(line.as_bytes())?;
    f.sync_all()?;
    Ok(())
}
