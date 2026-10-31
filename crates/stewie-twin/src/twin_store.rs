//! The versioned, event-sourced observed-terrain twin (Python `stewie.twin.versioned.TwinStore`).
//!
//! An immutable base height grid plus an append-only edit log; the current map is the base with every
//! live patch replayed. Each event needs provenance, bumps the version, and is hash-chained:
//! sha256(previous hash + the event without its hash + the patch's little-endian f64 bytes). Undo never
//! deletes history; it appends an `undo` event. Durable stores journal and fsync before acknowledging.
//! This is the perception view: the conserved physics authority is never edited through it.

use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::{TwinError, journal, pyjson};

#[derive(Debug, Clone)]
pub struct TwinStore {
    base: Vec<f64>,
    rows: usize,
    cols: usize,
    cell_m: f64,
    events: Vec<Value>,
    version: u64,
    journal: Option<PathBuf>,
}

fn hex(d: &[u8]) -> String {
    d.iter().fold(String::new(), |mut s, b| {
        use std::fmt::Write as _;
        let _ = write!(s, "{b:02x}");
        s
    })
}

fn patch_bytes(patch: &[Vec<f64>]) -> Vec<u8> {
    patch
        .iter()
        .flatten()
        .flat_map(|v| v.to_le_bytes())
        .collect()
}

/// A recorded patch's rows as numbers (accepts JSON integers as Python's `np.array(..., float64)` does).
fn patch_rows(ev: &Value) -> Result<Vec<Vec<f64>>, TwinError> {
    let bad = || TwinError::Invalid("patch event lacks a 2-D numeric patch".into());
    ev.get("patch")
        .and_then(Value::as_array)
        .ok_or_else(bad)?
        .iter()
        .map(|r| {
            r.as_array()
                .ok_or_else(bad)?
                .iter()
                .map(|x| x.as_f64().ok_or_else(bad))
                .collect()
        })
        .collect()
}

impl TwinStore {
    /// A volatile store over `base` (row-major, `rows` x `cols`).
    ///
    /// # Errors
    /// A base of the wrong length or with a non-finite height.
    pub fn new(base: Vec<f64>, rows: usize, cols: usize, cell_m: f64) -> Result<Self, TwinError> {
        if base.len() != rows * cols || !base.iter().all(|h| h.is_finite()) {
            return Err(TwinError::Invalid(format!(
                "base must be {rows}x{cols} finite heights"
            )));
        }
        Ok(Self {
            base,
            rows,
            cols,
            cell_m,
            events: Vec::new(),
            version: 0,
            journal: None,
        })
    }

    /// Cold restore: replay the journal through the edit path (each hash re-derived and checked before it
    /// is applied), repair a torn tail, then keep journalling.
    ///
    /// # Errors
    /// As [`journal::replay`] and [`TwinStore::apply_event`].
    pub fn from_journal(
        base: Vec<f64>,
        rows: usize,
        cols: usize,
        cell_m: f64,
        path: &Path,
    ) -> Result<Self, TwinError> {
        let mut tw = Self::new(base, rows, cols, cell_m)?;
        journal::replay(path, "twin journal", |ev| tw.apply_event(ev).map(|_| ()))?;
        tw.journal = Some(path.to_path_buf());
        Ok(tw)
    }

    #[must_use]
    pub fn cell_m(&self) -> f64 {
        self.cell_m
    }

    /// The immutable base heights (row-major).
    #[must_use]
    pub fn base(&self) -> &[f64] {
        &self.base
    }

    /// `(rows, cols)`.
    #[must_use]
    pub fn shape(&self) -> (usize, usize) {
        (self.rows, self.cols)
    }

    #[must_use]
    pub fn version(&self) -> u64 {
        self.version
    }

    #[must_use]
    pub fn events(&self) -> &[Value] {
        &self.events
    }

    /// `(version, latest event hash)`, consistent by construction (callers share the store behind one lock).
    #[must_use]
    pub fn identity(&self) -> (u64, String) {
        (self.version, self.last_hash())
    }

    fn last_hash(&self) -> String {
        self.events
            .last()
            .and_then(|e| e.get("hash"))
            .and_then(Value::as_str)
            .unwrap_or("genesis")
            .to_owned()
    }

    fn append(
        &mut self,
        mut body: Value,
        patch: &[u8],
        expected: Option<&str>,
    ) -> Result<u64, TwinError> {
        body["seq"] = json!(self.events.len());
        let mut h = Sha256::new();
        h.update(self.last_hash().as_bytes());
        h.update(pyjson::dumps(&body)?.as_bytes());
        h.update(patch);
        let hash = hex(&h.finalize());
        if expected.is_some_and(|e| e != hash) {
            return Err(TwinError::Tampered(format!(
                "twin event seq {}",
                self.events.len()
            )));
        }
        body["hash"] = json!(hash);
        if let Some(p) = &self.journal {
            journal::append(p, &body)?; // durable before acknowledged
        }
        self.events.push(body);
        self.version += 1;
        Ok(self.version)
    }

    /// Replace the observed heights of a rectangle at `origin_rc`. Returns the new version.
    ///
    /// # Errors
    /// Empty provenance; a ragged, empty or non-finite patch; a patch outside the twin.
    pub fn apply_patch(
        &mut self,
        heights: &[Vec<f64>],
        origin_rc: (usize, usize),
        provenance: &str,
    ) -> Result<u64, TwinError> {
        self.patch_checked(heights, origin_rc, provenance, None)
    }

    fn patch_checked(
        &mut self,
        heights: &[Vec<f64>],
        (r0, c0): (usize, usize),
        provenance: &str,
        expected: Option<&str>,
    ) -> Result<u64, TwinError> {
        if provenance.trim().is_empty() {
            return Err(TwinError::Invalid(
                "every twin edit requires non-empty provenance".into(),
            ));
        }
        let (h, w) = (heights.len(), heights.first().map_or(0, Vec::len));
        let valid = h > 0
            && w > 0
            && heights
                .iter()
                .all(|r| r.len() == w && r.iter().all(|x| x.is_finite()));
        if !valid {
            return Err(TwinError::Invalid(
                "patch must be a finite 2-D height array".into(),
            ));
        }
        if r0 + h > self.rows || c0 + w > self.cols {
            return Err(TwinError::Invalid(format!(
                "patch {h}x{w} at ({r0},{c0}) exceeds the twin extent {}x{}",
                self.rows, self.cols
            )));
        }
        let body = json!({
            "kind": "patch",
            "origin_rc": [r0, c0],
            "shape": [h, w],
            "provenance": provenance,
            "patch": heights,
        });
        self.append(body, &patch_bytes(heights), expected)
    }

    /// The patch events not yet undone.
    fn undone_targets(&self) -> std::collections::BTreeSet<u64> {
        self.events
            .iter()
            .filter(|e| e["kind"] == "undo")
            .filter_map(|e| e["target"].as_u64())
            .collect()
    }

    /// Append an undo of the most recent live patch (history is never deleted). Returns the new version.
    ///
    /// # Errors
    /// Nothing left to undo.
    pub fn undo(&mut self) -> Result<u64, TwinError> {
        self.undo_checked(None)
    }

    fn undo_checked(&mut self, expected: Option<&str>) -> Result<u64, TwinError> {
        let undone = self.undone_targets();
        let target = self
            .events
            .iter()
            .rev()
            .filter(|e| e["kind"] == "patch")
            .filter_map(|e| e["seq"].as_u64())
            .find(|s| !undone.contains(s))
            .ok_or_else(|| TwinError::Invalid("nothing to undo".into()))?;
        let body = json!({"kind": "undo", "target": target, "provenance": format!("undo of seq {target}")});
        self.append(body, b"", expected)
    }

    /// Replay one recorded event verbatim, verifying its chain hash before it changes anything.
    ///
    /// # Errors
    /// An unknown kind, a malformed event, or a hash that does not re-derive.
    pub fn apply_event(&mut self, ev: &Value) -> Result<u64, TwinError> {
        let expected = ev.get("hash").and_then(Value::as_str);
        if expected.is_none() {
            return Err(TwinError::Invalid("event lacks its hash".into()));
        }
        match ev.get("kind").and_then(Value::as_str) {
            Some("patch") => {
                let o = ev.get("origin_rc").and_then(Value::as_array);
                let at = |k: usize| {
                    o.and_then(|a| a.get(k))
                        .and_then(Value::as_u64)
                        .and_then(|v| usize::try_from(v).ok())
                };
                let (Some(r0), Some(c0)) = (at(0), at(1)) else {
                    return Err(TwinError::Invalid("patch event lacks origin_rc".into()));
                };
                let prov = ev.get("provenance").and_then(Value::as_str).unwrap_or("");
                self.patch_checked(&patch_rows(ev)?, (r0, c0), prov, expected)
            }
            Some("undo") => self.undo_checked(expected),
            other => Err(TwinError::Invalid(format!(
                "unknown twin event kind {other:?}"
            ))),
        }
    }

    fn live_patches(&self) -> impl Iterator<Item = &Value> {
        let undone = self.undone_targets();
        self.events.iter().filter(move |e| {
            e["kind"] == "patch" && e["seq"].as_u64().is_some_and(|s| !undone.contains(&s))
        })
    }

    /// The current observed map: the base with every live patch laid over it in order.
    #[must_use]
    pub fn current(&self) -> Vec<f64> {
        let mut out = self.base.clone();
        self.lay(|i, v| out[i] = v);
        out
    }

    /// True where a live patch has been measured (the coverage gate for consuming observed terrain).
    #[must_use]
    pub fn observed_mask(&self) -> Vec<bool> {
        let mut m = vec![false; self.base.len()];
        self.lay(|i, _| m[i] = true);
        m
    }

    #[allow(clippy::cast_possible_truncation)] // origins were bounds-checked when appended
    fn lay(&self, mut put: impl FnMut(usize, f64)) {
        for e in self.live_patches() {
            let (r0, c0) = (
                e["origin_rc"][0].as_u64().unwrap_or(0) as usize,
                e["origin_rc"][1].as_u64().unwrap_or(0) as usize,
            );
            for (dr, row) in patch_rows(e).unwrap_or_default().iter().enumerate() {
                for (dc, &v) in row.iter().enumerate() {
                    put((r0 + dr) * self.cols + c0 + dc, v);
                }
            }
        }
    }

    /// Re-derive every event's chain hash.
    #[must_use]
    pub fn verify_chain(&self) -> bool {
        let mut prev = "genesis".to_owned();
        for e in &self.events {
            let mut body = e.clone();
            let Some(m) = body.as_object_mut() else {
                return false;
            };
            let Some(hash) = m.remove("hash").and_then(|h| h.as_str().map(str::to_owned)) else {
                return false;
            };
            let bytes = if e["kind"] == "patch" {
                patch_rows(e).map(|p| patch_bytes(&p))
            } else {
                Ok(Vec::new())
            };
            let (Ok(bytes), Ok(text)) = (bytes, pyjson::dumps(&body)) else {
                return false;
            };
            let mut h = Sha256::new();
            h.update(prev.as_bytes());
            h.update(text.as_bytes());
            h.update(&bytes);
            if hex(&h.finalize()) != hash {
                return false;
            }
            prev = hash;
        }
        true
    }

    /// Event summaries without patch payloads.
    #[must_use]
    pub fn history(&self) -> Vec<Value> {
        self.events
            .iter()
            .map(|e| {
                let mut s = e.clone();
                if let Some(m) = s.as_object_mut() {
                    m.remove("patch");
                }
                s
            })
            .collect()
    }
}
