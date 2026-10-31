//! STEWIE data contracts. The JSON Schemas in `schema/` are the single source of truth; the Rust types
//! below are generated from them at compile time, so a schema change that breaks a consumer fails the
//! build.

/// Terrain bundle metadata (`samples/**/metadata.json`).
pub mod dem_bundle {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/dem_bundle.schema.json");

    /// Cross-field rules JSON Schema cannot express: bounds are ordered, the grid spans the bounds exactly
    /// (to float precision; every committed bundle is exact), and the height range is ordered.
    ///
    /// # Errors
    /// Returns a description of the first violated rule.
    pub fn check(b: &DemBundle) -> Result<(), String> {
        let w = &b.world_bounds_m;
        if !(w.x0 < w.x1 && w.y0 < w.y1) {
            return Err(format!(
                "world_bounds_m not ordered: x {}..{}, y {}..{}",
                w.x0, w.x1, w.y0, w.y1
            ));
        }
        let cell = b.grid.cell_m;
        let span_x =
            f64::from(u32::try_from(b.grid.width.get()).map_err(|e| e.to_string())?) * cell;
        let span_y =
            f64::from(u32::try_from(b.grid.height.get()).map_err(|e| e.to_string())?) * cell;
        let tol = cell * 1e-6;
        if (span_x - (w.x1 - w.x0)).abs() > tol || (span_y - (w.y1 - w.y0)).abs() > tol {
            return Err(format!(
                "grid {}x{} @ {cell} m spans {span_x} x {span_y} m but bounds span {} x {} m",
                b.grid.width,
                b.grid.height,
                w.x1 - w.x0,
                w.y1 - w.y0
            ));
        }
        if b.height_range_m[0] > b.height_range_m[1] {
            return Err(format!(
                "height_range_m not ordered: {:?}",
                b.height_range_m
            ));
        }
        Ok(())
    }
}

/// Planetary body registry: one source for gravity, radius and sourced soil constants.
pub mod body {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/body.schema.json");
}

/// Sourced lunar site catalog.
pub mod site {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/site.schema.json");
}

/// Installable data package manifest (navigator N11).
pub mod package_manifest {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/package_manifest.schema.json");
}

/// Soil constants beyond the body registry, each with its honesty tag.
pub mod soil_baseline {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/soil_baseline.schema.json");
}
