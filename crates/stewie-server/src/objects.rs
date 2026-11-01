//! The object store (RW-55b8; Python `server.objects`): named artifacts as one JSON file per slugged name under
//! `data_dir/{kind}/` (the shared `live` namespace) or `data_dir/{kind}/sandbox/<owner>/`, with ownership stamps,
//! the overwrite and delete policies, and recoverable soft-delete into the namespace's `.trash`. Each
//! authorize-and-mutate runs under the artifact's `.locks/<slug>.lock` `flock`, the lock the Python takes, so the two
//! servers serialize on a shared data directory.

use std::fs::File;
use std::path::{Path, PathBuf};

use serde_json::{Map, Value, json};

/// A name's file slug (Python `_slug`): runs outside `[a-z0-9]` become `-`, trimmed, at most 64 characters.
#[must_use]
pub fn slug(name: &str) -> String {
    let mut out = String::new();
    for c in name.to_lowercase().chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            out.push(c);
        } else if !out.ends_with('-') {
            out.push('-');
        }
    }
    let s: String = out.trim_matches('-').chars().take(64).collect();
    if s.is_empty() {
        "unnamed".to_owned()
    } else {
        s
    }
}

/// A namespace of the store.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Namespace<'a> {
    /// The shared, command-eligible store (the flat `{kind}/` directory).
    Live,
    /// One owner's scratch space.
    Sandbox(Option<&'a str>),
}

/// The directory of a kind's namespace, created as the Python's `_ns_dir` does.
///
/// # Errors
/// The directory cannot be created.
pub fn ns_dir(data_dir: &Path, kind: &str, ns: Namespace<'_>) -> Result<PathBuf, String> {
    let base = data_dir.join(kind);
    let d = match ns {
        Namespace::Live => base,
        Namespace::Sandbox(owner) => base.join("sandbox").join(slug(owner.unwrap_or("unknown"))),
    };
    std::fs::create_dir_all(&d).map_err(|e| format!("{}: {e}", d.display()))?;
    Ok(d)
}

/// The artifact's lock, held until dropped (`flock`, as the Python's `_artifact_lock`).
#[derive(Debug)]
pub struct ArtifactLock {
    /// Held only for its descriptor: closing it on drop releases the lock.
    _file: File,
}

impl ArtifactLock {
    /// Take the exclusive lock on `(kind, name)` in its namespace.
    ///
    /// # Errors
    /// The lock file cannot be opened or locked.
    pub fn take(
        data_dir: &Path,
        kind: &str,
        name: &str,
        ns: Namespace<'_>,
    ) -> Result<Self, String> {
        use std::os::unix::fs::OpenOptionsExt as _;
        let dir = ns_dir(data_dir, kind, ns)?.join(".locks");
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        let f = std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .mode(0o600)
            .open(dir.join(format!("{}.lock", slug(name))))
            .map_err(|e| e.to_string())?;
        f.lock().map_err(|e| e.to_string())?;
        Ok(Self { _file: f })
    }
}

/// The stored artifact's path.
///
/// # Errors
/// The namespace directory cannot be created.
pub fn artifact_path(
    data_dir: &Path,
    kind: &str,
    name: &str,
    ns: Namespace<'_>,
) -> Result<PathBuf, String> {
    Ok(ns_dir(data_dir, kind, ns)?.join(format!("{}.json", slug(name))))
}

/// The `created_by`/`created_at` to write (Python `_owner_meta`): a re-save keeps the original creator, a new or
/// unowned file is stamped now.
#[must_use]
pub fn owner_meta(path: &Path, owner: &str, now: f64) -> (Value, Value) {
    if let Some(prev) = std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        && prev.get("created_by").is_some_and(truthy)
    {
        return (
            prev["created_by"].clone(),
            prev.get("created_at").cloned().unwrap_or(json!(now)),
        );
    }
    (json!(owner), json!(now))
}

/// Python truthiness of a JSON value.
pub(crate) fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|x| x != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(m) => !m.is_empty(),
    }
}

/// The stored artifact's `created_by` (Python `owner_of`): `None` when absent, `"unknown"` when unreadable or
/// unowned.
#[must_use]
pub fn owner_of(path: &Path) -> Option<String> {
    if !path.exists() {
        return None;
    }
    let owner = std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .map(|d| {
            d.get("created_by")
                .map_or_else(|| "unknown".to_owned(), crate::validate::py_str)
        });
    Some(owner.unwrap_or_else(|| "unknown".to_owned()))
}

/// The delete policy (AG-06, BP-05): a live artifact needs a director; a sandbox one its owner or a director; a
/// missing one is a harmless no-op.
#[must_use]
pub fn deletion_allowed(
    owner: Option<&str>,
    identity: &str,
    is_director: bool,
    ns: Namespace<'_>,
) -> bool {
    match (owner, ns) {
        (None, _) => true,
        (Some(_), Namespace::Live) => is_director,
        (Some(o), Namespace::Sandbox(_)) => is_director || o == identity,
    }
}

/// The overwrite policy (SR-01): an existing artifact is writable by its owner or a director; a new name is free.
#[must_use]
pub fn write_allowed(owner: Option<&str>, identity: &str, is_director: bool) -> bool {
    owner.is_none_or(|o| is_director || o == identity)
}

/// Move the artifact into its namespace's `.trash` as `<slug>.<ms>.json` (Python `_soft_delete_unlocked`); `false`
/// when there is none. The caller holds the artifact's lock.
///
/// # Errors
/// The move fails.
pub fn soft_delete_unlocked(
    data_dir: &Path,
    kind: &str,
    name: &str,
    ns: Namespace<'_>,
    now: f64,
) -> Result<bool, String> {
    let src = artifact_path(data_dir, kind, name, ns)?;
    if !src.exists() {
        return Ok(false);
    }
    let trash = ns_dir(data_dir, kind, ns)?.join(".trash");
    std::fs::create_dir_all(&trash).map_err(|e| e.to_string())?;
    #[allow(clippy::cast_possible_truncation)] // the Python's `int(time.time() * 1000)`
    let ms = (now * 1000.0) as i64;
    std::fs::rename(&src, trash.join(format!("{}.{ms}.json", slug(name))))
        .map_err(|e| e.to_string())?;
    Ok(true)
}

/// The Python's sorted list repr of the fields outside `allowed`, if any (`sorted(set(doc) - KEYS)`).
#[must_use]
pub fn unknown_fields(doc: &Map<String, Value>, allowed: &[&str]) -> Option<String> {
    let mut unknown: Vec<&String> = doc
        .keys()
        .filter(|k| !allowed.contains(&k.as_str()))
        .collect();
    unknown.sort();
    (!unknown.is_empty()).then(|| {
        format!(
            "[{}]",
            unknown
                .iter()
                .map(|k| crate::operators::py_repr(k))
                .collect::<Vec<_>>()
                .join(", ")
        )
    })
}

/// Write `{**head, created_by, created_at, **doc}` as the Python's `json.dumps(..., indent=1, sort_keys=True)`,
/// atomically.
///
/// # Errors
/// A non-finite number, or the write fails.
pub fn write_doc(
    path: &Path,
    head: &[(&str, Value)],
    meta: (Value, Value),
    doc: &Map<String, Value>,
) -> Result<(), String> {
    let mut m: Map<String, Value> = head
        .iter()
        .map(|(k, v)| ((*k).to_owned(), v.clone()))
        .collect();
    m.insert("created_by".to_owned(), meta.0);
    m.insert("created_at".to_owned(), meta.1);
    m.extend(doc.iter().map(|(k, v)| (k.clone(), v.clone())));
    let text =
        stewie_twin::pyjson::dumps_indent(&Value::Object(m), 1).map_err(|e| e.to_string())?;
    crate::atomic_write(path, text.as_bytes())
}

/// A stored document, if the file exists.
///
/// # Errors
/// An unreadable or malformed file (the Python raises).
pub fn load(path: &Path) -> Result<Option<Value>, String> {
    if !path.exists() {
        return Ok(None);
    }
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    serde_json::from_str(&text)
        .map(Some)
        .map_err(|e| e.to_string())
}

/// The `*.json` file names of a directory, sorted as the Python's `sorted(os.listdir(...))`.
///
/// # Errors
/// The directory cannot be read.
pub fn json_files(dir: &Path) -> Result<Vec<String>, String> {
    let mut out: Vec<String> = std::fs::read_dir(dir)
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .filter_map(|e| e.file_name().to_str().map(str::to_owned))
        .filter(|n| {
            #[allow(clippy::case_sensitive_file_extension_comparisons)]
            // the Python's `endswith(".json")`
            n.ends_with(".json")
        })
        .collect();
    out.sort();
    Ok(out)
}

/// The namespace's `.trash` directory, created.
///
/// # Errors
/// It cannot be created.
pub fn trash_dir(data_dir: &Path, kind: &str, ns: Namespace<'_>) -> Result<PathBuf, String> {
    let d = ns_dir(data_dir, kind, ns)?.join(".trash");
    std::fs::create_dir_all(&d).map_err(|e| e.to_string())?;
    Ok(d)
}

/// Restore the newest trashed copy (the last `<slug>.*.json` in name order) into the namespace (Python
/// `_restore_unlocked`); `false` when there is none. The caller holds the lock and has checked the destination.
///
/// # Errors
/// The move fails.
pub fn restore_unlocked(
    data_dir: &Path,
    kind: &str,
    name: &str,
    ns: Namespace<'_>,
) -> Result<bool, String> {
    let prefix = format!("{}.", slug(name));
    let tdir = trash_dir(data_dir, kind, ns)?;
    let hits: Vec<String> = json_files(&tdir)?
        .into_iter()
        .filter(|f| f.starts_with(&prefix))
        .collect();
    let Some(newest) = hits.last() else {
        return Ok(false);
    };
    std::fs::rename(tdir.join(newest), artifact_path(data_dir, kind, name, ns)?)
        .map_err(|e| e.to_string())?;
    Ok(true)
}

/// Copy a sandbox draft over the live artifact of its slug (Python `_publish_unlocked`); `false` when the draft is
/// absent. The caller holds the live lock and has authorized the destination.
///
/// # Errors
/// The read or the write fails.
pub fn publish_unlocked(
    data_dir: &Path,
    kind: &str,
    name: &str,
    source_owner: &str,
) -> Result<bool, String> {
    let src = artifact_path(data_dir, kind, name, Namespace::Sandbox(Some(source_owner)))?;
    if !src.exists() {
        return Ok(false);
    }
    let bytes = std::fs::read(&src).map_err(|e| e.to_string())?;
    crate::atomic_write(
        &artifact_path(data_dir, kind, name, Namespace::Live)?,
        &bytes,
    )?;
    Ok(true)
}

/// Python `len()` of a stored field, `0` when absent; a value without a length is an error (the Python raises).
fn py_len(v: Option<&Value>, what: &str) -> Result<usize, String> {
    match v {
        None => Ok(0),
        Some(Value::Array(a)) => Ok(a.len()),
        Some(Value::Object(m)) => Ok(m.len()),
        Some(Value::String(s)) => Ok(s.chars().count()),
        Some(_) => Err(format!("{what} has no length")),
    }
}

/// The readable `*.json` documents of a namespace directory, in name order, unreadable ones skipped (Python's
/// `except (json.JSONDecodeError, OSError): continue`).
fn documents(dir: &Path) -> Result<Vec<(String, Value)>, String> {
    Ok(json_files(dir)?
        .into_iter()
        .filter_map(|f| {
            let d =
                serde_json::from_str::<Value>(&std::fs::read_to_string(dir.join(&f)).ok()?).ok()?;
            Some((f, d))
        })
        .collect())
}

/// A namespace's mission rows (Python `list_missions`).
///
/// # Errors
/// The directory cannot be read, or a stored `orders` has no length.
pub fn list_missions(data_dir: &Path, ns: Namespace<'_>) -> Result<Vec<Value>, String> {
    documents(&ns_dir(data_dir, "missions", ns)?)?
        .into_iter()
        .map(|(f, d)| {
            let get = |k: &str, default: Value| d.get(k).cloned().unwrap_or(default);
            Ok(json!({"name": get("name", json!(f.trim_end_matches(".json"))), "title": get("title", json!("")),
                      "body": get("body", json!("?")), "n_orders": py_len(d.get("orders"), &f)?,
                      "owner": get("created_by", json!("unknown")), "created_at": get("created_at", Value::Null)}))
        })
        .collect()
}

/// The live structure-template rows (Python `list_structures`): a document without a `name` is skipped.
///
/// # Errors
/// The directory cannot be read, or a stored `kind_list` has no length.
pub fn list_structures(data_dir: &Path) -> Result<Vec<Value>, String> {
    let mut rows = Vec::new();
    for (f, d) in documents(&ns_dir(data_dir, "structures", Namespace::Live)?)? {
        let Some(name) = d.get("name") else { continue };
        rows.push(
            json!({"name": name, "title": d.get("title").cloned().unwrap_or(json!("")),
                         "n_entries": py_len(d.get("kind_list"), &f)?,
                         "owner": d.get("created_by").cloned().unwrap_or(json!("unknown")),
                         "created_at": d.get("created_at").cloned().unwrap_or(Value::Null)}),
        );
    }
    Ok(rows)
}

/// What a restore did.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Restored {
    /// The newest trashed copy is back in place.
    Yes,
    /// There was no trashed copy.
    Nothing,
    /// The destination is occupied; the Python's `FileExistsError` text.
    Occupied(String),
}

/// Restore under the artifact's lock, never over an existing artifact (Python `restore_authorized` once the caller
/// is authorized).
///
/// # Errors
/// The lock, the listing or the move fails.
pub fn restore(
    data_dir: &Path,
    kind: &str,
    name: &str,
    ns: Namespace<'_>,
) -> Result<Restored, String> {
    let _lock = ArtifactLock::take(data_dir, kind, name, ns)?;
    if artifact_path(data_dir, kind, name, ns)?.exists() {
        return Ok(Restored::Occupied(format!(
            "refusing to restore {kind}/{} over an existing artifact",
            slug(name)
        )));
    }
    Ok(if restore_unlocked(data_dir, kind, name, ns)? {
        Restored::Yes
    } else {
        Restored::Nothing
    })
}

#[cfg(test)]
mod tests {
    use super::slug;

    #[test]
    fn slugs_match_the_python() {
        // SYNTHETIC names against Python `_slug` (`re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64]`)
        for (name, want) in [
            ("Pad Ring A", "pad-ring-a"),
            ("--Berm__2--", "berm-2"),
            ("Ω", "unnamed"),
            ("a—b", "a-b"),
            ("", "unnamed"),
        ] {
            assert_eq!(slug(name), want, "{name:?}");
        }
        assert_eq!(slug(&"x".repeat(70)).len(), 64);
        assert_eq!(
            slug(&format!("{}-tail", "y".repeat(63))),
            format!("{}-", "y".repeat(63))
        );
    }
}
