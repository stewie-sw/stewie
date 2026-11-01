//! The conserved as-built record (RW-34b; Python `lode.planner_acceptance.mission_terrain_delta` / `record_mission`,
//! `lode.regolith_volume.estimate_moved_regolith`, `RegolithVolumeEstimate.from_delta`, `leap.volume_evidence`).
//!
//! A mission's terrain change is the conserved column's own executed delta (as-built minus the pre-build surface,
//! from the same run as acceptance), and that delta is what is folded into the site's Terrain Memory, so the
//! recorded as-built change is the executed physics change by construction (assessment #4). The moved-regolith
//! estimate turns a before/after surface pair into cut and fill mass with a correlated-worst-case uncertainty band
//! and cross-checks it against the conserved mass and the drum-fill sensor's published error band.

use serde_json::{Value, json};
use stewie_plan::acceptance::{AcceptanceInputs, AcceptanceParams, validate_plan_grids};
use stewie_plan::mission::Mission;
use stewie_traverse::route::Dem;
use stewie_twin::numpy::sum as np_sum;
use stewie_twin::terrain_memory::{Placement, TerrainMemory};

/// The spine contract version the evidence is stamped with (Python `stewie.contracts.SPINE_VERSION`).
pub const SPINE_VERSION: &str = "1.0";

/// A mission's executed terrain change over its own grid (row-major).
#[derive(Debug, Clone, PartialEq)]
pub struct TerrainDelta {
    pub delta: Vec<f64>,
    pub base: Vec<f64>,
    pub as_built: Vec<f64>,
    pub x0: f64,
    pub y0: f64,
    pub cell_m: f64,
    pub rows: usize,
    pub cols: usize,
    /// The executed cut mass [kg].
    pub mass_moved_kg: f64,
}

/// The mission's conserved terrain change: the acceptance run's as-built surface minus its pre-build surface, on
/// the real terrain when a DEM is given, else on the flat mantle (the Python's default).
///
/// # Errors
/// A column the physics refuses.
pub fn mission_terrain_delta(
    m: &Mission,
    dem: Option<Dem<'_>>,
    inp: &AcceptanceInputs<'_>,
    p: &AcceptanceParams,
) -> Result<TerrainDelta, String> {
    let (report, g) = validate_plan_grids(m, dem, inp, p)?;
    Ok(TerrainDelta {
        delta: g.as_built.iter().zip(&g.base).map(|(a, b)| a - b).collect(),
        base: g.base,
        as_built: g.as_built,
        x0: g.grid.x0,
        y0: g.grid.y0,
        cell_m: g.grid.cell_m,
        rows: g.grid.rows,
        cols: g.grid.cols,
        mass_moved_kg: report["executed_cut_kg"].as_f64().unwrap_or(0.0),
    })
}

/// Fold a mission's executed change into the site's Terrain Memory at its order-frame offset.
///
/// # Errors
/// A Terrain Memory whose cell differs from the mission's, or the memory's own refusal.
pub fn record_mission(
    memory: &mut TerrainMemory,
    m: &Mission,
    d: &TerrainDelta,
) -> Result<Placement, String> {
    memory
        .apply_subgrid(
            &d.delta,
            d.rows,
            d.cols,
            (d.x0, d.y0),
            d.cell_m,
            &m.name,
            d.mass_moved_kg,
        )
        .map_err(|e| e.to_string())
}

/// The drum-fill sensor's published error (ICE-RASSOR FDC, NTRS 20210022781): configuration.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DrumBand {
    /// Mean error over the mass range, without and with the two outlier dig cycles.
    pub mpe_all: f64,
    pub mpe_with_outliers: f64,
    /// Mean error above half full.
    pub mpe_half_full: f64,
    pub half_full_kg: f64,
}

impl DrumBand {
    /// The published figures, verbatim (NTRS 20210022781, the linear FDC result; Python `rassor_mass_model`).
    pub const NTRS_20210022781: Self = Self {
        mpe_all: 0.07403,
        mpe_with_outliers: 0.11842,
        mpe_half_full: 0.02558,
        half_full_kg: 20.0,
    };

    /// The relative error of a drum-mass reading: the half-full figure above half full, else a linear blend
    /// from the over-range figure (so the upper bound stays monotone).
    #[must_use]
    pub fn uncertainty_frac(&self, mass_kg: f64, include_outliers: bool) -> f64 {
        let lo = if include_outliers {
            self.mpe_with_outliers
        } else {
            self.mpe_all
        };
        if mass_kg >= self.half_full_kg {
            return self.mpe_half_full;
        }
        let f = mass_kg.max(0.0) / self.half_full_kg;
        lo + f * (self.mpe_half_full - lo)
    }
}

/// The estimator's inputs besides the two surfaces.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct EstimateInputs {
    /// In-situ density of the cut material [kg/m^3] (the column density on the conserved authority).
    pub density_kg_m3: f64,
    /// Placed fill density; the cut density when not given.
    pub spoil_density_kg_m3: Option<f64>,
    /// Per-cell surface height error [m] (0 for conserved surfaces).
    pub height_rmse_m: f64,
    /// Relative density envelope.
    pub density_frac: f64,
    pub conserved_mass_kg: Option<f64>,
    pub drum_inferred_kg: Option<f64>,
}

/// Moved regolith between two surfaces on one grid, with its uncertainty band and cross-checks (Python
/// `estimate_moved_regolith`).
///
/// # Errors
/// Mismatched grids, a non-positive density, or a negative error term.
#[allow(clippy::cast_precision_loss)] // a cell count
pub fn estimate_moved_regolith(
    before: &[f64],
    after: &[f64],
    cell_m: f64,
    e: &EstimateInputs,
    drum: &DrumBand,
) -> Result<Value, String> {
    if e.density_kg_m3 <= 0.0 || e.density_kg_m3.is_nan() {
        return Err(format!(
            "density_kg_m3 must be > 0 (got {})",
            e.density_kg_m3
        ));
    }
    let spoil = e.spoil_density_kg_m3.unwrap_or(e.density_kg_m3);
    if spoil <= 0.0 || spoil.is_nan() {
        return Err(format!("spoil_density_kg_m3 must be > 0 (got {spoil})"));
    }
    if e.height_rmse_m < 0.0 || e.density_frac < 0.0 {
        return Err("height_rmse_m and density_frac must be >= 0".to_owned());
    }
    if before.len() != after.len() {
        return Err(format!(
            "before/after heightfields must share a grid: {} vs {} cells",
            before.len(),
            after.len()
        ));
    }
    let area = cell_m * cell_m;
    let d: Vec<f64> = after.iter().zip(before).map(|(a, b)| a - b).collect();
    let neg: Vec<f64> = d.iter().copied().filter(|&x| x < 0.0).collect();
    let pos: Vec<f64> = d.iter().copied().filter(|&x| x > 0.0).collect();
    let cut_v = -np_sum(&neg) * area;
    let fill_v = np_sum(&pos) * area;
    let changed = d.iter().filter(|x| x.abs() > 1e-9).count();
    let observed = cut_v * e.density_kg_m3;
    // correlated worst case: the height error over every worked cell, plus the density envelope
    let unc =
        e.height_rmse_m * (changed as f64 * area) * e.density_kg_m3 + e.density_frac * observed;
    let (lower, upper) = (observed - unc, observed + unc);
    let ftol = 1e-9 * observed.abs().max(1.0);
    let mut out = json!({
        "cut_volume_m3": cut_v, "fill_volume_m3": fill_v, "net_volume_m3": np_sum(&d) * area,
        "changed_cells": changed, "cell_area_m2": area,
        "density_kg_m3": e.density_kg_m3, "spoil_density_kg_m3": spoil,
        "height_rmse_m": e.height_rmse_m, "density_frac": e.density_frac,
        "observed_mass_kg": observed, "fill_mass_kg": fill_v * spoil,
        "uncertainty_kg": unc, "uncertainty_frac": if observed > 0.0 { unc / observed } else { 0.0 },
        "lower_kg": lower, "upper_kg": upper,
        "conserved_mass_kg": null, "conserved_err_kg": null, "agreement_conserved": null,
        "drum_inferred_kg": null, "drum_uncertainty_frac": null, "drum_lower_kg": null, "drum_upper_kg": null,
        "agreement_drum": null,
    });
    if let Some(c) = e.conserved_mass_kg {
        out["conserved_mass_kg"] = json!(c);
        out["conserved_err_kg"] = json!(observed - c);
        out["agreement_conserved"] = json!(lower - ftol <= c && c <= upper + ftol);
    }
    if let Some(dm) = e.drum_inferred_kg {
        let du = drum.uncertainty_frac(dm, false);
        let (dlo, dhi) = (dm * (1.0 - du), dm * (1.0 + du));
        out["drum_inferred_kg"] = json!(dm);
        out["drum_uncertainty_frac"] = json!(du);
        out["drum_lower_kg"] = json!(dlo);
        out["drum_upper_kg"] = json!(dhi);
        out["agreement_drum"] = json!(lower.max(dlo) <= upper.min(dhi) + ftol);
    }
    Ok(out)
}

/// The typed moved-regolith evidence for a work order (Python `RegolithVolumeEstimate.from_delta`): the estimate,
/// the changed-cell count, a confidence class from the uncertainty fraction (high <= 5 %, medium <= 15 %), and
/// `accepted` only when every available cross-check agrees.
///
/// # Errors
/// As [`estimate_moved_regolith`].
#[allow(clippy::too_many_arguments)] // the Python contract's fields
pub fn volume_evidence(
    before: &[f64],
    after: &[f64],
    cell_m: f64,
    e: &EstimateInputs,
    drum: &DrumBand,
    work_order_id: &str,
    (before_source, after_source): (&str, &str),
    transaction_id: &str,
) -> Result<Value, String> {
    let est = estimate_moved_regolith(before, after, cell_m, e, drum)?;
    let change = after
        .iter()
        .zip(before)
        .filter(|(a, b)| (*a - *b) != 0.0)
        .count();
    let uf = est["uncertainty_frac"].as_f64().unwrap_or(0.0);
    let conf = if uf <= 0.05 {
        "high"
    } else if uf <= 0.15 {
        "medium"
    } else {
        "low"
    };
    let checks: Vec<bool> = ["agreement_conserved", "agreement_drum"]
        .iter()
        .filter_map(|k| est[*k].as_bool())
        .collect();
    let accept = if !checks.is_empty() && checks.iter().all(|c| *c) {
        "accepted"
    } else {
        "review"
    };
    Ok(json!({
        "work_order_id": work_order_id, "before_source": before_source, "after_source": after_source,
        "change_cells": change, "observed_mass_kg": est["observed_mass_kg"], "fill_mass_kg": est["fill_mass_kg"],
        "uncertainty_kg": est["uncertainty_kg"], "uncertainty_frac": uf, "lower_kg": est["lower_kg"],
        "upper_kg": est["upper_kg"], "conserved_err_kg": est["conserved_err_kg"],
        "agreement_conserved": est["agreement_conserved"], "drum_inferred_kg": est["drum_inferred_kg"],
        "agreement_drum": est["agreement_drum"], "confidence_class": conf, "acceptance": accept,
        "transaction_id": transaction_id, "schema_version": SPINE_VERSION,
    }))
}
