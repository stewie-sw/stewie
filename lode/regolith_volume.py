"""ML-06: the Regolith Volume Estimator -- moved volume/mass WITH an uncertainty band from before/after
DEM/stereo heightfields, cross-checked against the conserved-authority mass and the drum-fill sensing
estimate.

The three legs it ties together (all pre-existing, tested models -- nothing re-derived here):

  * VOLUME: ``stewie.eval.perception_measure.excavation_volume`` (PM-16) turns the before/after
    heightfields into cut / fill / net volumes on the shared grid.
  * MASS: cut volume x the site's IN-SITU bulk density = the excavated (moved) mass. On the conserved
    authority the height a cut releases is ``removed_areal / column density`` (column_state), so the
    matching density is the COLUMN bulk density (K.RHO_SURFACE on the default mantle) -- the caller
    supplies it, sourced, never fabricated here. Fill volume x spoil density recovers the placed mass
    (deposit_field's volume-preserving rise, ``dh = deposited_areal / spoil_density``).
  * UNCERTAINTY: the observed band is driven by the PER-CELL HEIGHT ERROR of the surfaces (for stereo
    reconstructions, the measured dense height RMSE from ``perception_measure``; 0 for conserved
    surfaces) plus an optional density envelope. The height term is propagated as FULLY CORRELATED
    across the worked cells (rmse x worked area x density) -- deliberately conservative, because stereo
    height error is NOT independent per cell (the g2cal sigma calibration folds sun-geometry-dependent
    per-pose bias into its sigma), so a sqrt(N) independent-error reduction would overstate precision.

Cross-checks (each optional, each reported, neither fabricated):
  * conserved authority: does ``mass_moved_kg`` (validate_plan's executed cut) sit inside the band?
  * drum-fill sensing: does the ICE-RASSOR FDC drum estimate's own published-error band
    (``drum_mass_uncertainty_frac``, NTRS 20210022781) OVERLAP the observed band?

GATED (named, not built here): the DENSE observed-before/after leg -- feeding this estimator two stereo
RECONSTRUCTIONS of a worksite (before/after renders -> SGBM heightfields) needs the GPU render pipeline
(P6 map channel). The estimator itself is pure numpy and is exercised now on conserved surfaces with the
REAL measured stereo height RMSE (lode/test_regolith_volume.py).
"""
from __future__ import annotations

from stewie.eval.perception_measure import excavation_volume
from stewie.physics.rassor_mass_model import drum_mass_uncertainty_frac


def estimate_moved_regolith(before_h, after_h, cell_m, *, density_kg_m3,
                            spoil_density_kg_m3=None, height_rmse_m=0.0, density_frac=0.0,
                            conserved_mass_kg=None, drum_inferred_kg=None) -> dict:
    """Estimate the regolith moved between a BEFORE and AFTER heightfield, with an uncertainty band and
    the two cross-checks the mass estimate must survive.

    ``density_kg_m3`` is the in-situ bulk density of the cut material (sourced by the caller; on the
    conserved authority's default mantle this is the column density, K.RHO_SURFACE);
    ``spoil_density_kg_m3`` the loose density fills were placed at (defaults to ``density_kg_m3``).
    ``height_rmse_m`` is the per-cell height error of the SURFACES (measured stereo RMSE for observed
    heightfields, 0 for conserved ones); ``density_frac`` an optional relative density envelope. Both
    widen the band -- correlated-worst-case, see the module docstring.

    ``conserved_mass_kg`` (validate_plan / mission_terrain_delta's ``mass_moved_kg``) and
    ``drum_inferred_kg`` (a DrumSensor mass estimate) switch on their cross-checks: ``agreement_*`` is
    True/False when supplied, None when not. Agreement uses a tiny float-roundoff guard only -- the
    real tolerance is the declared uncertainty, never a hidden fudge."""
    if not (density_kg_m3 > 0.0):
        raise ValueError(f"density_kg_m3 must be > 0 (got {density_kg_m3})")
    spoil = density_kg_m3 if spoil_density_kg_m3 is None else spoil_density_kg_m3
    if not (spoil > 0.0):
        raise ValueError(f"spoil_density_kg_m3 must be > 0 (got {spoil})")
    if height_rmse_m < 0.0 or density_frac < 0.0:
        raise ValueError("height_rmse_m and density_frac must be >= 0")
    vols = excavation_volume(before_h, after_h, cell_m)     # PM-16 (raises on a grid mismatch)
    observed = vols["cut_volume_m3"] * density_kg_m3        # the moved (excavated) mass estimate
    fill_mass = vols["fill_volume_m3"] * spoil
    # correlated-worst-case band: rmse over EVERY worked cell, at the cut density, + the density envelope
    worked_area_m2 = vols["changed_cells"] * vols["cell_area_m2"]
    unc = height_rmse_m * worked_area_m2 * density_kg_m3 + density_frac * observed
    lower, upper = observed - unc, observed + unc
    ftol = 1e-9 * max(1.0, abs(observed))                   # float roundoff only, NOT a tolerance knob
    out = {
        **vols,
        "density_kg_m3": float(density_kg_m3), "spoil_density_kg_m3": float(spoil),
        "height_rmse_m": float(height_rmse_m), "density_frac": float(density_frac),
        "observed_mass_kg": float(observed), "fill_mass_kg": float(fill_mass),
        "uncertainty_kg": float(unc),
        "uncertainty_frac": float(unc / observed) if observed > 0.0 else 0.0,
        "lower_kg": float(lower), "upper_kg": float(upper),
        "conserved_mass_kg": None, "conserved_err_kg": None, "agreement_conserved": None,
        "drum_inferred_kg": None, "drum_uncertainty_frac": None,
        "drum_lower_kg": None, "drum_upper_kg": None, "agreement_drum": None,
    }
    if conserved_mass_kg is not None:                       # leg 1: the conserved-authority truth
        out["conserved_mass_kg"] = float(conserved_mass_kg)
        out["conserved_err_kg"] = float(observed - conserved_mass_kg)
        out["agreement_conserved"] = bool(lower - ftol <= conserved_mass_kg <= upper + ftol)
    if drum_inferred_kg is not None:                        # leg 2: drum-fill sensing (published FDC band)
        dunc = drum_mass_uncertainty_frac(drum_inferred_kg)
        dlo, dhi = drum_inferred_kg * (1.0 - dunc), drum_inferred_kg * (1.0 + dunc)
        out["drum_inferred_kg"] = float(drum_inferred_kg)
        out["drum_uncertainty_frac"] = float(dunc)
        out["drum_lower_kg"], out["drum_upper_kg"] = float(dlo), float(dhi)
        # agreement = the two bands OVERLAP (each estimate carries its own honestly-sourced error)
        out["agreement_drum"] = bool(max(lower, dlo) <= min(upper, dhi) + ftol)
    return out
