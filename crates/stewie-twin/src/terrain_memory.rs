//! Terrain Memory (Python `stewie.twin.terrain_memory`, RW-21c): the authoritative per-site record of how missions
//! changed the terrain. It holds the accumulated per-cell height change against the base DEM, each mission's
//! own change (sparse, so any past surface can be rebuilt), and a hash-chained provenance log, and it persists
//! as the same `.npz` the Python writes. It takes deltas in from the conserved physics; it never recomputes them.
//!
//! Each record's hash is `sha256(prev_hash + json.dumps(meta, sort_keys=True))` over
//! `{version, mission, mass_moved_kg, net_volume_m3}`, both numbers rounded to 6 decimals as Python rounds and
//! the volume summed as numpy sums, so a Python chain verifies here and a Rust chain verifies there.

use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

use crate::numpy::{self, Array};
use crate::world_log::sha256_hex;
use crate::{TwinError, pyjson};

fn bad(m: impl Into<String>) -> TwinError {
    TwinError::Invalid(m.into())
}

/// One provenance record.
#[derive(Debug, Clone, PartialEq)]
pub struct Record {
    pub version: u64,
    pub mission: String,
    pub mass_moved_kg: f64,
    pub net_volume_m3: f64,
    pub hash: String,
}

impl Record {
    fn meta(&self) -> Value {
        json!({"version": self.version, "mission": self.mission, "mass_moved_kg": self.mass_moved_kg,
               "net_volume_m3": self.net_volume_m3})
    }
}

fn record_hash(prev: &str, meta: &Value) -> Result<String, TwinError> {
    Ok(sha256_hex(&[
        prev.as_bytes(),
        pyjson::dumps(meta)?.as_bytes(),
    ]))
}

/// Where a sub-grid mission landed in the site grid.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Placement {
    pub version: u64,
    /// Cells of the mission inside the site with a change above 1e-9 m.
    pub placed_cells: usize,
    /// True when part of the mission fell outside the site grid (surfaced, never silently dropped).
    pub clipped: bool,
}

/// How much a site has changed across all applied missions.
#[derive(Debug, Clone, PartialEq)]
pub struct Summary {
    pub site: String,
    pub version: u64,
    pub cells_changed: usize,
    pub net_volume_m3: f64,
    pub max_cut_m: f64,
    pub max_fill_m: f64,
    pub missions: Vec<String>,
}

/// One mission's change, sparse: flat indices and values of its non-zero cells.
#[derive(Debug, Clone, PartialEq)]
struct Sparse {
    idx: Vec<usize>,
    val: Vec<f64>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TerrainMemory {
    pub site: String,
    pub rows: usize,
    pub cols: usize,
    pub cell_m: f64,
    /// Order-frame `(x0, y0)` [m] the grid covers; x grows with column, y with row.
    pub origin: (f64, f64),
    delta: Vec<f64>,
    version: u64,
    chain: Vec<Record>,
    history: Vec<Sparse>,
}

/// Python `int(round(v))`: half to even.
#[allow(clippy::cast_possible_truncation)]
fn round_index(v: f64) -> i64 {
    v.round_ties_even() as i64
}

/// The overlap of a block `n` long placed at `offset` with `[0, len)`: `(start, end)` in grid coordinates.
#[allow(
    clippy::cast_possible_wrap,
    clippy::cast_sign_loss,
    clippy::cast_possible_truncation
)]
fn overlap(offset: i64, n: usize, len: usize) -> (usize, usize) {
    let lo = offset.max(0);
    let hi = (offset + n as i64).min(len as i64);
    if hi > lo {
        (lo as usize, hi as usize)
    } else {
        (0, 0)
    }
}

impl TerrainMemory {
    /// An empty memory over a `rows x cols` grid of `cell_m` cells.
    ///
    /// # Errors
    /// A zero-sized grid or a non-positive cell.
    pub fn new(
        site: &str,
        rows: usize,
        cols: usize,
        cell_m: f64,
        origin: (f64, f64),
    ) -> Result<Self, TwinError> {
        if rows == 0 || cols == 0 {
            return Err(bad(format!(
                "TerrainMemory grid must be positive (got rows={rows}, cols={cols})"
            )));
        }
        if !(cell_m.is_finite() && cell_m > 0.0) {
            return Err(bad(format!(
                "TerrainMemory cell_m must be > 0 (got {cell_m})"
            )));
        }
        Ok(Self {
            site: site.to_owned(),
            rows,
            cols,
            cell_m,
            origin,
            delta: vec![0.0; rows * cols],
            version: 0,
            chain: Vec::new(),
            history: Vec::new(),
        })
    }

    #[must_use]
    pub fn version(&self) -> u64 {
        self.version
    }

    #[must_use]
    pub fn chain(&self) -> &[Record] {
        &self.chain
    }

    #[must_use]
    pub fn cell_area(&self) -> f64 {
        self.cell_m * self.cell_m
    }

    fn check_grid(&self, what: &str, len: usize) -> Result<(), TwinError> {
        if len == self.rows * self.cols {
            Ok(())
        } else {
            Err(bad(format!(
                "{what} has {len} cells != grid {}x{}",
                self.rows, self.cols
            )))
        }
    }

    /// Fold one mission's per-cell height change [m] (site grid, row-major) in as a new hash-chained version.
    ///
    /// # Errors
    /// A wrong-sized or non-finite delta.
    pub fn apply(
        &mut self,
        delta: &[f64],
        mission: &str,
        mass_moved_kg: f64,
    ) -> Result<u64, TwinError> {
        self.check_grid("delta", delta.len())?;
        if !delta.iter().all(|v| v.is_finite()) {
            return Err(bad("delta must be finite (got NaN/Inf)"));
        }
        for (acc, d) in self.delta.iter_mut().zip(delta) {
            *acc += d;
        }
        let idx: Vec<usize> = (0..delta.len()).filter(|&i| delta[i] != 0.0).collect();
        let val = idx.iter().map(|&i| delta[i]).collect();
        self.history.push(Sparse { idx, val });
        self.version += 1;
        let mut rec = Record {
            version: self.version,
            mission: mission.to_owned(),
            mass_moved_kg: numpy::round(mass_moved_kg, 6),
            net_volume_m3: numpy::round(numpy::sum(delta) * self.cell_area(), 6),
            hash: String::new(),
        };
        let prev = self.chain.last().map_or("", |r| r.hash.as_str());
        rec.hash = record_hash(prev, &rec.meta())?;
        self.chain.push(rec);
        Ok(self.version)
    }

    /// Fold a mission's local change (its own `sub_rows x sub_cols` box with order-frame corner `sub_origin`,
    /// same cell) into the site grid at `round((sub_origin - origin) / cell)`, clipping to the site.
    ///
    /// # Errors
    /// A different cell size, a ragged delta, or as [`Self::apply`].
    #[allow(
        clippy::cast_sign_loss,
        clippy::cast_possible_wrap,
        clippy::cast_possible_truncation,
        clippy::too_many_arguments // the Python signature: the mission's box, its corner and cell, and the record
    )]
    pub fn apply_subgrid(
        &mut self,
        delta: &[f64],
        sub_rows: usize,
        sub_cols: usize,
        sub_origin: (f64, f64),
        cell_m: f64,
        mission: &str,
        mass_moved_kg: f64,
    ) -> Result<Placement, TwinError> {
        if (cell_m - self.cell_m).abs() > 1e-9 {
            return Err(bad(format!(
                "sub-grid cell_m {cell_m} != site cell_m {}",
                self.cell_m
            )));
        }
        if delta.len() != sub_rows * sub_cols {
            return Err(bad("delta must be a 2-D (rows, cols) grid"));
        }
        let col_off = round_index((sub_origin.0 - self.origin.0) / self.cell_m);
        let row_off = round_index((sub_origin.1 - self.origin.1) / self.cell_m);
        let (r0, r1) = overlap(row_off, sub_rows, self.rows);
        let (c0, c1) = overlap(col_off, sub_cols, self.cols);
        let mut full = vec![0.0; self.rows * self.cols];
        let mut placed = 0;
        for r in r0..r1 {
            for c in c0..c1 {
                let v =
                    delta[(r as i64 - row_off) as usize * sub_cols + (c as i64 - col_off) as usize];
                full[r * self.cols + c] = v;
                placed += usize::from(v.abs() > 1e-9);
            }
        }
        let clipped = row_off < 0
            || col_off < 0
            || row_off + sub_rows as i64 > self.rows as i64
            || col_off + sub_cols as i64 > self.cols as i64;
        let version = self.apply(&full, mission, mass_moved_kg)?;
        Ok(Placement {
            version,
            placed_cells: placed,
            clipped,
        })
    }

    /// Retained per-mission deltas (equal to the version unless loaded from a pre-retention file).
    #[must_use]
    pub fn history_len(&self) -> usize {
        self.history.len()
    }

    fn dense(&self, s: &Sparse) -> Vec<f64> {
        let mut out = vec![0.0; self.rows * self.cols];
        for (&i, &v) in s.idx.iter().zip(&s.val) {
            out[i] = v;
        }
        out
    }

    fn retained(&self, version: u64, from: u64) -> Result<usize, TwinError> {
        let v = usize::try_from(version).map_err(|e| bad(e.to_string()))?;
        if version < from || v > self.history.len() {
            return Err(bad(format!(
                "version {version} outside retained history {from}..{}",
                self.history.len()
            )));
        }
        Ok(v)
    }

    /// The change applied at `version` (1-based, as the chain).
    ///
    /// # Errors
    /// A version outside the retained history.
    pub fn delta_at(&self, version: u64) -> Result<Vec<f64>, TwinError> {
        let v = self.retained(version, 1)?;
        Ok(self.dense(&self.history[v - 1]))
    }

    /// The accumulated change as of `version`; version 0 is the pristine base.
    ///
    /// # Errors
    /// A version outside the retained history.
    pub fn cumulative_delta_at(&self, version: u64) -> Result<Vec<f64>, TwinError> {
        let v = self.retained(version, 0)?;
        let mut out = vec![0.0; self.rows * self.cols];
        for s in &self.history[..v] {
            for (&i, &d) in s.idx.iter().zip(&s.val) {
                out[i] += d;
            }
        }
        Ok(out)
    }

    /// The surface as of `version`: `base + cumulative_delta_at(version)`.
    ///
    /// # Errors
    /// A wrong-sized base or a version outside the retained history.
    pub fn height_at(&self, base: &[f64], version: u64) -> Result<Vec<f64>, TwinError> {
        self.check_grid("base", base.len())?;
        let d = self.cumulative_delta_at(version)?;
        Ok(base.iter().zip(&d).map(|(b, d)| b + d).collect())
    }

    /// Roll back to `version`, discarding later missions and their records.
    ///
    /// # Errors
    /// A version outside the retained history.
    pub fn revert_to(&mut self, version: u64) -> Result<(), TwinError> {
        let v = self.retained(version, 0)?;
        self.delta = self.cumulative_delta_at(version)?;
        self.history.truncate(v);
        self.chain.truncate(v);
        self.version = version;
        Ok(())
    }

    /// The accumulated change [m] against the base DEM.
    #[must_use]
    pub fn cumulative_delta(&self) -> &[f64] {
        &self.delta
    }

    /// The current surface on the site grid: `base + cumulative_delta`.
    ///
    /// # Errors
    /// A wrong-sized base.
    pub fn current_height(&self, base: &[f64]) -> Result<Vec<f64>, TwinError> {
        self.check_grid("base", base.len())?;
        Ok(base.iter().zip(&self.delta).map(|(b, d)| b + d).collect())
    }

    /// A copy of a larger DEM (`dem_rows x dem_cols`, same cell) with this memory added at
    /// `round((origin + dem_origin) / cell)`, clipped to the DEM: the surface a new mission plans against.
    ///
    /// # Errors
    /// A different cell size or a ragged DEM.
    #[allow(
        clippy::cast_sign_loss,
        clippy::cast_possible_wrap,
        clippy::cast_possible_truncation
    )]
    pub fn imprint_on_dem(
        &self,
        dem: &[f64],
        dem_cols: usize,
        dem_cell: f64,
        dem_origin: (f64, f64),
    ) -> Result<Vec<f64>, TwinError> {
        if (dem_cell - self.cell_m).abs() > 1e-9 {
            return Err(bad(format!(
                "dem_cell {dem_cell} != memory cell_m {} (resample not supported)",
                self.cell_m
            )));
        }
        if dem_cols == 0 || !dem.len().is_multiple_of(dem_cols) {
            return Err(bad("base_z must be a 2-D DEM"));
        }
        let mut z = dem.to_vec();
        let col_off = round_index((self.origin.0 + dem_origin.0) / self.cell_m);
        let row_off = round_index((self.origin.1 + dem_origin.1) / self.cell_m);
        let (r0, r1) = overlap(row_off, self.rows, dem.len() / dem_cols);
        let (c0, c1) = overlap(col_off, self.cols, dem_cols);
        for r in r0..r1 {
            for c in c0..c1 {
                let m = (r as i64 - row_off) as usize * self.cols + (c as i64 - col_off) as usize;
                z[r * dem_cols + c] += self.delta[m];
            }
        }
        Ok(z)
    }

    /// As [`Self::imprint_on_dem`] onto a coarser DEM: each memory cell centre is binned into the DEM cell it
    /// falls in, and a DEM cell rises by the binned change over its capacity `(dem_cell / cell)^2`, which
    /// conserves volume exactly (unrecorded fine cells count as no change).
    ///
    /// # Errors
    /// A ragged DEM.
    #[allow(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss
    )]
    pub fn imprint_on_dem_resampled(
        &self,
        dem: &[f64],
        dem_cols: usize,
        dem_cell: f64,
        dem_origin: (f64, f64),
    ) -> Result<Vec<f64>, TwinError> {
        if (dem_cell - self.cell_m).abs() <= 1e-9 {
            return self.imprint_on_dem(dem, dem_cols, dem_cell, dem_origin);
        }
        if dem_cols == 0 || !dem.len().is_multiple_of(dem_cols) {
            return Err(bad("base_z must be a 2-D DEM"));
        }
        let dem_rows = dem.len() / dem_cols;
        let mut sums = vec![0.0; dem.len()];
        let mut counts = vec![0usize; dem.len()];
        for i in 0..self.rows {
            for j in 0..self.cols {
                let x = self.origin.0 + (j as f64 + 0.5) * self.cell_m;
                let y = self.origin.1 + (i as f64 + 0.5) * self.cell_m;
                let col = ((x + dem_origin.0) / dem_cell).floor();
                let row = ((y + dem_origin.1) / dem_cell).floor();
                if row >= 0.0
                    && col >= 0.0
                    && (row as usize) < dem_rows
                    && (col as usize) < dem_cols
                {
                    let k = row as usize * dem_cols + col as usize;
                    sums[k] += self.delta[i * self.cols + j];
                    counts[k] += 1;
                }
            }
        }
        let capacity = (dem_cell / self.cell_m).powi(2);
        let mut z = dem.to_vec();
        for k in (0..z.len()).filter(|&k| counts[k] > 0) {
            z[k] += sums[k] / capacity;
        }
        Ok(z)
    }

    #[must_use]
    pub fn summary(&self) -> Summary {
        let d = &self.delta;
        let min = d.iter().copied().fold(f64::INFINITY, f64::min);
        let max = d.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        Summary {
            site: self.site.clone(),
            version: self.version,
            cells_changed: d.iter().filter(|v| v.abs() > 1e-9).count(),
            net_volume_m3: numpy::round(numpy::sum(d) * self.cell_area(), 6),
            max_cut_m: numpy::round(-min, 6),
            max_fill_m: numpy::round(max, 6),
            missions: self.chain.iter().map(|r| r.mission.clone()).collect(),
        }
    }

    /// True iff every record's hash equals `H(prev_hash, its meta)`: reordering or editing is detected.
    #[must_use]
    pub fn verify_chain(&self) -> bool {
        let mut prev = String::new();
        for r in &self.chain {
            match record_hash(&prev, &r.meta()) {
                Ok(h) if h == r.hash => prev.clone_from(&r.hash),
                _ => return false,
            }
        }
        true
    }

    fn meta_json(&self) -> Value {
        let chain: Vec<Value> = self
            .chain
            .iter()
            .map(|r| {
                let mut m = r.meta();
                m["hash"] = Value::from(r.hash.clone());
                m
            })
            .collect();
        json!({"site": self.site, "rows": self.rows, "cols": self.cols, "cell_m": self.cell_m,
               "origin": [self.origin.0, self.origin.1], "version": self.version, "chain": chain})
    }

    /// Persist as the Python does: an `.npz` of `delta`, `meta` (JSON text) and the flattened history
    /// (`hist_idx`, `hist_val`, `hist_off`), written to `<path>.part`, synced, then renamed into place.
    ///
    /// # Errors
    /// An I/O failure.
    pub fn save(&self, path: &Path) -> Result<(), TwinError> {
        let mut idx = Vec::new();
        let mut val = Vec::new();
        let mut off = vec![0i64];
        for s in &self.history {
            idx.extend(s.idx.iter().map(|&i| i64::try_from(i).unwrap_or(i64::MAX)));
            val.extend_from_slice(&s.val);
            off.push(i64::try_from(idx.len()).unwrap_or(i64::MAX));
        }
        let arrays = [
            (
                "delta",
                Array::F64 {
                    shape: vec![self.rows, self.cols],
                    data: self.delta.clone(),
                },
            ),
            ("meta", Array::Str(self.meta_json().to_string())),
            (
                "hist_idx",
                Array::I64 {
                    shape: vec![idx.len()],
                    data: idx,
                },
            ),
            (
                "hist_val",
                Array::F64 {
                    shape: vec![val.len()],
                    data: val,
                },
            ),
            (
                "hist_off",
                Array::I64 {
                    shape: vec![off.len()],
                    data: off,
                },
            ),
        ];
        numpy::save_npz(path, &arrays)
    }

    /// Restore a memory written by [`Self::save`] or by the Python. A file from before history retention has
    /// no `hist_*` arrays and loads with an empty history, so point-in-time queries refuse rather than invent.
    ///
    /// # Errors
    /// An unreadable or malformed file.
    pub fn load(path: &Path) -> Result<Self, TwinError> {
        let arrays = numpy::read_npz(fs::File::open(path).map_err(TwinError::Io)?)?;
        let Some(Array::Str(meta)) = arrays.get("meta") else {
            return Err(bad(format!("{}: no meta", path.display())));
        };
        let m: Value = serde_json::from_str(meta).map_err(|e| bad(e.to_string()))?;
        let num = |k: &str| m[k].as_f64().ok_or_else(|| bad(format!("meta {k}")));
        let int = |k: &str| {
            m[k].as_u64()
                .and_then(|v| usize::try_from(v).ok())
                .ok_or_else(|| bad(format!("meta {k}")))
        };
        let origin = (
            m["origin"][0].as_f64().ok_or_else(|| bad("meta origin"))?,
            m["origin"][1].as_f64().ok_or_else(|| bad("meta origin"))?,
        );
        let mut tm = Self::new(
            m["site"].as_str().ok_or_else(|| bad("meta site"))?,
            int("rows")?,
            int("cols")?,
            num("cell_m")?,
            origin,
        )?;
        let Some(Array::F64 { data, .. }) = arrays.get("delta") else {
            return Err(bad(format!("{}: no float64 delta", path.display())));
        };
        tm.check_grid("delta", data.len())?;
        tm.delta.clone_from(data);
        tm.version = m["version"].as_u64().ok_or_else(|| bad("meta version"))?;
        for r in m["chain"].as_array().ok_or_else(|| bad("meta chain"))? {
            tm.chain.push(Record {
                version: r["version"].as_u64().ok_or_else(|| bad("chain version"))?,
                mission: r["mission"]
                    .as_str()
                    .ok_or_else(|| bad("chain mission"))?
                    .to_owned(),
                mass_moved_kg: r["mass_moved_kg"]
                    .as_f64()
                    .ok_or_else(|| bad("chain mass"))?,
                net_volume_m3: r["net_volume_m3"]
                    .as_f64()
                    .ok_or_else(|| bad("chain volume"))?,
                hash: r["hash"]
                    .as_str()
                    .ok_or_else(|| bad("chain hash"))?
                    .to_owned(),
            });
        }
        if let (
            Some(Array::I64 { data: idx, .. }),
            Some(Array::F64 { data: val, .. }),
            Some(Array::I64 { data: off, .. }),
        ) = (
            arrays.get("hist_idx"),
            arrays.get("hist_val"),
            arrays.get("hist_off"),
        ) {
            let ix = |v: i64| usize::try_from(v).map_err(|_| bad("negative history index"));
            for w in off.windows(2) {
                let (a, b) = (ix(w[0])?, ix(w[1])?);
                if a > b || b > idx.len() || b > val.len() {
                    return Err(bad("history offsets out of range"));
                }
                let cells: Vec<usize> =
                    idx[a..b].iter().map(|&i| ix(i)).collect::<Result<_, _>>()?;
                if cells.iter().any(|&i| i >= tm.delta.len()) {
                    return Err(bad("history index outside the grid"));
                }
                tm.history.push(Sparse {
                    idx: cells,
                    val: val[a..b].to_vec(),
                });
            }
        }
        Ok(tm)
    }
}

/// A path-safe filename component for a site (alphanumerics, `-` and `_`; `site` if nothing remains).
#[must_use]
pub fn safe_site(site: &str) -> String {
    let s: String = site
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '-' || *c == '_')
        .collect();
    if s.is_empty() { "site".into() } else { s }
}

/// `<data_dir>/terrain_memory/<site>.npz`.
#[must_use]
pub fn terrain_path(data_dir: &Path, site: &str) -> PathBuf {
    data_dir
        .join("terrain_memory")
        .join(format!("{}.npz", safe_site(site)))
}

/// A site's persisted memory, or `None` when nothing has been recorded yet.
///
/// # Errors
/// An unreadable or malformed file.
pub fn load_site(data_dir: &Path, site: &str) -> Result<Option<TerrainMemory>, TwinError> {
    let p = terrain_path(data_dir, site);
    if p.exists() {
        TerrainMemory::load(&p).map(Some)
    } else {
        Ok(None)
    }
}

/// Persist a site's memory under the data directory.
///
/// # Errors
/// An I/O failure.
pub fn save_site(data_dir: &Path, memory: &TerrainMemory) -> Result<PathBuf, TwinError> {
    let p = terrain_path(data_dir, &memory.site);
    if let Some(dir) = p.parent() {
        fs::create_dir_all(dir).map_err(TwinError::Io)?;
    }
    memory.save(&p)?;
    Ok(p)
}

/// The raw persisted bytes of a site's memory (or `None`), taken before a mutation so a world-log commit
/// that then fails can be compensated by [`restore_site`].
///
/// # Errors
/// An I/O failure.
pub fn snapshot_site(data_dir: &Path, site: &str) -> Result<Option<Vec<u8>>, TwinError> {
    crate::snapshot_file(&terrain_path(data_dir, site))
}

/// Restore a site's memory to a [`snapshot_site`] snapshot (`None` removes it), atomically.
///
/// # Errors
/// An I/O failure.
pub fn restore_site(data_dir: &Path, site: &str, snapshot: Option<&[u8]>) -> Result<(), TwinError> {
    crate::restore_file(&terrain_path(data_dir, site), snapshot)
}
