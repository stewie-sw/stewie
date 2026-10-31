//! Traffic Memory (Python `stewie.twin.traffic_memory`, RW-21c-2): the per-site record of how driving firms the
//! ground. Each telemetry event (the cells the wheels crossed and their per-wheel normal load) folds into the
//! cumulative load, the peak load and the pass count of every cell, as a hash-chained version. Re-folding an
//! event already seen changes nothing (H-09), so re-committing a run cannot double-harden a road.
//!
//! The hardened density approaches the conserved compaction equilibrium at the peak load exponentially in the
//! cumulative load: `rho = rho_eq - (rho_eq - rho_surface) * exp(-sum / sigma_c)`, capped at the deep density,
//! so it never firms past what the conserved model would produce. The road layer and `sigma_c` are [CALIB]
//! model parameters with no published value; they are required here and persisted with the memory.

use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use stewie_physics::bearing;
use stewie_physics::material::MaterialModel;
use stewie_physics::soil::SoilParams;
use stewie_physics::terra;

use crate::numpy::{self, Array};
use crate::terrain_memory::safe_site;
use crate::world_log::sha256_hex;
use crate::{TwinError, pyjson};

fn bad(m: impl Into<String>) -> TwinError {
    TwinError::Invalid(m.into())
}

/// The model parameters a memory is built with (persisted with it).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct TrafficParams {
    /// Reference areal mass of the compactable road layer [kg/m^2] ([CALIB]).
    pub mass_areal: f64,
    /// Cumulative load over which a cell firms about 63% of the way to equilibrium [N] ([CALIB]).
    pub sigma_c_n: f64,
    /// Wheel contact width [m] (the rover profile's).
    pub contact_width_m: f64,
}

/// What the derived fields read: the soil's Bekker set (its surface density is the pristine state, its deep
/// density the cap), the wheel contact length, the material model and gravity.
#[derive(Debug, Clone, Copy)]
pub struct Hardening<'a> {
    pub soil: &'a SoilParams,
    pub contact_len_m: f64,
    pub material: &'a MaterialModel,
    pub gravity_ms2: f64,
}

/// One provenance record.
#[derive(Debug, Clone, PartialEq)]
pub struct Record {
    pub version: u64,
    pub mission: String,
    pub event_id: String,
    pub added_load_n: f64,
    pub cells: u64,
    pub hash: String,
}

impl Record {
    fn meta(&self) -> Value {
        json!({"version": self.version, "mission": self.mission, "event_id": self.event_id,
               "added_load_n": self.added_load_n, "cells": self.cells})
    }
}

fn record_hash(prev: &str, meta: &Value) -> Result<String, TwinError> {
    Ok(sha256_hex(&[
        prev.as_bytes(),
        pyjson::dumps(meta)?.as_bytes(),
    ]))
}

#[derive(Debug, Clone, PartialEq)]
pub struct Summary {
    pub site: String,
    pub version: u64,
    pub cells_trafficked: usize,
    pub max_passes: u32,
    pub max_load_cycles_n: f64,
    pub peak_relative_density: f64,
    pub cells_firm_dr_gt_0p5: usize,
    pub peak_bearing_uplift_pa: f64,
    pub missions: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TrafficMemory {
    pub site: String,
    pub rows: usize,
    pub cols: usize,
    pub cell_m: f64,
    pub origin: (f64, f64),
    pub params: TrafficParams,
    load_cycles: Vec<f64>,
    peak_load: Vec<f64>,
    passes: Vec<u32>,
    version: u64,
    chain: Vec<Record>,
    applied: Vec<String>,
}

impl TrafficMemory {
    /// An empty memory over a `rows x cols` grid.
    ///
    /// # Errors
    /// A zero-sized grid, a non-positive cell, or non-positive model parameters.
    pub fn new(
        site: &str,
        rows: usize,
        cols: usize,
        cell_m: f64,
        origin: (f64, f64),
        params: TrafficParams,
    ) -> Result<Self, TwinError> {
        if rows == 0 || cols == 0 {
            return Err(bad(format!(
                "TrafficMemory grid must be positive (got rows={rows}, cols={cols})"
            )));
        }
        if !(cell_m.is_finite() && cell_m > 0.0) {
            return Err(bad(format!(
                "TrafficMemory cell_m must be > 0 (got {cell_m})"
            )));
        }
        let p = &params;
        if ![p.mass_areal, p.sigma_c_n, p.contact_width_m]
            .iter()
            .all(|v| v.is_finite() && *v > 0.0)
        {
            return Err(bad(format!(
                "TrafficMemory parameters must be > 0 (got {params:?})"
            )));
        }
        let n = rows * cols;
        Ok(Self {
            site: site.to_owned(),
            rows,
            cols,
            cell_m,
            origin,
            params,
            load_cycles: vec![0.0; n],
            peak_load: vec![0.0; n],
            passes: vec![0; n],
            version: 0,
            chain: Vec::new(),
            applied: Vec::new(),
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
    pub fn load_cycles(&self) -> &[f64] {
        &self.load_cycles
    }

    #[must_use]
    pub fn peak_load(&self) -> &[f64] {
        &self.peak_load
    }

    #[must_use]
    pub fn passes(&self) -> &[u32] {
        &self.passes
    }

    /// Fold one telemetry event: a per-cell wheel-load field [N] (0 where the wheels did not cross). An event
    /// id already folded is a no-op that returns the current version.
    ///
    /// # Errors
    /// A wrong-sized or non-finite field.
    pub fn apply(&mut self, load: &[f64], mission: &str, event_id: &str) -> Result<u64, TwinError> {
        if self.applied.iter().any(|e| e == event_id) {
            return Ok(self.version);
        }
        if load.len() != self.rows * self.cols {
            return Err(bad(format!(
                "load_field has {} cells != grid {}x{}",
                load.len(),
                self.rows,
                self.cols
            )));
        }
        if !load.iter().all(|v| v.is_finite()) {
            return Err(bad("load_field must be finite (got NaN/Inf)"));
        }
        let d: Vec<f64> = load.iter().map(|v| v.max(0.0)).collect();
        let mut cells = 0;
        for (i, &v) in d.iter().enumerate() {
            self.load_cycles[i] += v;
            self.peak_load[i] = self.peak_load[i].max(v);
            if v > 0.0 {
                self.passes[i] += 1;
                cells += 1;
            }
        }
        self.version += 1;
        self.applied.push(event_id.to_owned());
        let mut rec = Record {
            version: self.version,
            mission: mission.to_owned(),
            event_id: event_id.to_owned(),
            added_load_n: numpy::round(numpy::sum(&d), 6),
            cells,
            hash: String::new(),
        };
        let prev = self.chain.last().map_or("", |r| r.hash.as_str());
        rec.hash = record_hash(prev, &rec.meta())?;
        self.chain.push(rec);
        Ok(self.version)
    }

    /// Fold a driven corridor, every `(row, col)` crossed at the same per-wheel load, as one event. Cells off
    /// the grid are dropped (the record's cell count shows how many landed).
    ///
    /// # Errors
    /// As [`Self::apply`].
    pub fn apply_path(
        &mut self,
        cells: &[(i64, i64)],
        load_n: f64,
        mission: &str,
        event_id: &str,
    ) -> Result<u64, TwinError> {
        let mut field = vec![0.0f64; self.rows * self.cols];
        for &(r, c) in cells {
            if let (Ok(r), Ok(c)) = (usize::try_from(r), usize::try_from(c))
                && r < self.rows
                && c < self.cols
            {
                let k = r * self.cols + c;
                field[k] = field[k].max(load_n);
            }
        }
        self.apply(&field, mission, event_id)
    }

    /// Per-cell asymptotic density [kg/m^3]: the conserved compaction equilibrium at the peak load, capped at
    /// the soil's deep density; untrafficked cells stay at the surface density.
    #[must_use]
    pub fn equilibrium_density(&self, h: &Hardening<'_>) -> Vec<f64> {
        self.peak_load
            .iter()
            .map(|&l| {
                terra::compaction_target_density(
                    self.params.mass_areal,
                    l,
                    h.contact_len_m,
                    self.params.contact_width_m,
                    0.0,
                    h.soil,
                )
                .min(h.soil.rho_deep)
            })
            .collect()
    }

    /// Per-cell hardened density [kg/m^3]: an exponential approach to the equilibrium in cumulative load.
    #[must_use]
    pub fn densified_density(&self, h: &Hardening<'_>) -> Vec<f64> {
        let rho0 = h.soil.rho_surface;
        self.equilibrium_density(h)
            .iter()
            .zip(&self.load_cycles)
            .map(|(eq, s)| rho0 + (eq - rho0) * (1.0 - (-s / self.params.sigma_c_n).exp()))
            .collect()
    }

    /// Per-cell relative density in [0, 1] of the hardened road.
    #[must_use]
    pub fn relative_density(&self, h: &Hardening<'_>) -> Vec<f64> {
        self.densified_density(h)
            .iter()
            .map(|&r| h.material.relative_density(r))
            .collect()
    }

    fn allowable(h: &Hardening<'_>, rho: f64, width_m: f64, factor_of_safety: f64) -> f64 {
        let (phi, c) = h.material.cell_strength(rho);
        bearing::allowable_pa(c, phi, rho * h.gravity_ms2, width_m, 0.0, factor_of_safety)
    }

    /// Per-cell allowable-bearing uplift [Pa] the traffic produced over a `width_m` footing:
    /// `q_allow(rho) - q_allow(surface density)`, never negative.
    #[must_use]
    pub fn bearing_uplift_pa(
        &self,
        h: &Hardening<'_>,
        width_m: f64,
        factor_of_safety: f64,
    ) -> Vec<f64> {
        let base = Self::allowable(h, h.soil.rho_surface, width_m, factor_of_safety);
        self.densified_density(h)
            .iter()
            .map(|&r| (Self::allowable(h, r, width_m, factor_of_safety) - base).max(0.0))
            .collect()
    }

    /// How much of the site is trafficked and how hard it got. Bearing capacity rises with density, so the
    /// peak uplift is read at the densest cell.
    #[must_use]
    pub fn summary(&self, h: &Hardening<'_>, width_m: f64, factor_of_safety: f64) -> Summary {
        let rho = self.densified_density(h);
        let dr: Vec<f64> = rho
            .iter()
            .map(|&r| h.material.relative_density(r))
            .collect();
        let peak_rho = rho.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let base = Self::allowable(h, h.soil.rho_surface, width_m, factor_of_safety);
        Summary {
            site: self.site.clone(),
            version: self.version,
            cells_trafficked: self.passes.iter().filter(|&&p| p > 0).count(),
            max_passes: self.passes.iter().copied().max().unwrap_or(0),
            max_load_cycles_n: numpy::round(
                self.load_cycles
                    .iter()
                    .copied()
                    .fold(f64::NEG_INFINITY, f64::max),
                3,
            ),
            peak_relative_density: numpy::round(
                dr.iter().copied().fold(f64::NEG_INFINITY, f64::max),
                4,
            ),
            cells_firm_dr_gt_0p5: dr.iter().filter(|&&d| d > 0.5).count(),
            peak_bearing_uplift_pa: numpy::round(
                (Self::allowable(h, peak_rho, width_m, factor_of_safety) - base).max(0.0),
                3,
            ),
            missions: self.chain.iter().map(|r| r.mission.clone()).collect(),
        }
    }

    /// True iff every record's hash equals `H(prev_hash, its meta)`.
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

    /// Persist as the Python does: `load_cycles`, `peak_load`, `passes` and `meta` in an `.npz`, atomically.
    ///
    /// # Errors
    /// An I/O failure.
    pub fn save(&self, path: &Path) -> Result<(), TwinError> {
        let chain: Vec<Value> = self
            .chain
            .iter()
            .map(|r| {
                let mut m = r.meta();
                m["hash"] = Value::from(r.hash.clone());
                m
            })
            .collect();
        let p = &self.params;
        let meta = json!({"site": self.site, "rows": self.rows, "cols": self.cols, "cell_m": self.cell_m,
            "origin": [self.origin.0, self.origin.1], "mass_areal": p.mass_areal, "sigma_c_n": p.sigma_c_n,
            "contact_width_m": p.contact_width_m, "version": self.version, "chain": chain,
            "applied": self.applied});
        let shape = vec![self.rows, self.cols];
        numpy::save_npz(
            path,
            &[
                (
                    "load_cycles",
                    Array::F64 {
                        shape: shape.clone(),
                        data: self.load_cycles.clone(),
                    },
                ),
                (
                    "peak_load",
                    Array::F64 {
                        shape: shape.clone(),
                        data: self.peak_load.clone(),
                    },
                ),
                (
                    "passes",
                    Array::U32 {
                        shape,
                        data: self.passes.clone(),
                    },
                ),
                ("meta", Array::Str(meta.to_string())),
            ],
        )
    }

    /// Restore a memory written by [`Self::save`] or by the Python.
    ///
    /// # Errors
    /// An unreadable or malformed file.
    pub fn load(path: &Path) -> Result<Self, TwinError> {
        let arrays = numpy::read_npz(std::fs::File::open(path).map_err(TwinError::Io)?)?;
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
        let text = |v: &Value, k: &str| {
            v[k].as_str()
                .map(str::to_owned)
                .ok_or_else(|| bad(format!("meta {k}")))
        };
        let mut tm = Self::new(
            &text(&m, "site")?,
            int("rows")?,
            int("cols")?,
            num("cell_m")?,
            (
                m["origin"][0].as_f64().ok_or_else(|| bad("meta origin"))?,
                m["origin"][1].as_f64().ok_or_else(|| bad("meta origin"))?,
            ),
            TrafficParams {
                mass_areal: num("mass_areal")?,
                sigma_c_n: num("sigma_c_n")?,
                contact_width_m: num("contact_width_m")?,
            },
        )?;
        let cells = tm.rows * tm.cols;
        match (
            arrays.get("load_cycles"),
            arrays.get("peak_load"),
            arrays.get("passes"),
        ) {
            (
                Some(Array::F64 { data: l, .. }),
                Some(Array::F64 { data: p, .. }),
                Some(Array::U32 { data: c, .. }),
            ) if l.len() == cells && p.len() == cells && c.len() == cells => {
                tm.load_cycles.clone_from(l);
                tm.peak_load.clone_from(p);
                tm.passes.clone_from(c);
            }
            _ => {
                return Err(bad(format!(
                    "{}: grids missing or not {cells} cells",
                    path.display()
                )));
            }
        }
        tm.version = m["version"].as_u64().ok_or_else(|| bad("meta version"))?;
        for r in m["chain"].as_array().ok_or_else(|| bad("meta chain"))? {
            tm.chain.push(Record {
                version: r["version"].as_u64().ok_or_else(|| bad("chain version"))?,
                mission: text(r, "mission")?,
                event_id: text(r, "event_id")?,
                added_load_n: r["added_load_n"]
                    .as_f64()
                    .ok_or_else(|| bad("chain load"))?,
                cells: r["cells"].as_u64().ok_or_else(|| bad("chain cells"))?,
                hash: text(r, "hash")?,
            });
        }
        tm.applied = m["applied"]
            .as_array()
            .ok_or_else(|| bad("meta applied"))?
            .iter()
            .map(|v| {
                v.as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| bad("applied id"))
            })
            .collect::<Result<_, _>>()?;
        Ok(tm)
    }
}

/// `<data_dir>/traffic_memory/<site>.npz`.
#[must_use]
pub fn traffic_path(data_dir: &Path, site: &str) -> PathBuf {
    data_dir
        .join("traffic_memory")
        .join(format!("{}.npz", safe_site(site)))
}

/// A site's persisted memory, or `None` when nothing has been recorded yet.
///
/// # Errors
/// An unreadable or malformed file.
pub fn load_site(data_dir: &Path, site: &str) -> Result<Option<TrafficMemory>, TwinError> {
    let p = traffic_path(data_dir, site);
    if p.exists() {
        TrafficMemory::load(&p).map(Some)
    } else {
        Ok(None)
    }
}

/// Persist a site's memory under the data directory.
///
/// # Errors
/// An I/O failure.
pub fn save_site(data_dir: &Path, memory: &TrafficMemory) -> Result<PathBuf, TwinError> {
    let p = traffic_path(data_dir, &memory.site);
    memory.save(&p)?;
    Ok(p)
}

/// The raw persisted bytes of a site's memory, for the DT-03 compensating rollback.
///
/// # Errors
/// An I/O failure.
pub fn snapshot_site(data_dir: &Path, site: &str) -> Result<Option<Vec<u8>>, TwinError> {
    crate::snapshot_file(&traffic_path(data_dir, site))
}

/// Restore a site's memory to a snapshot (`None` removes it).
///
/// # Errors
/// An I/O failure.
pub fn restore_site(data_dir: &Path, site: &str, snapshot: Option<&[u8]>) -> Result<(), TwinError> {
    crate::restore_file(&traffic_path(data_dir, site), snapshot)
}
