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

/// A data package's layers aligned to LOLA laser tracks (navigator N32, RW-60c).
pub mod package_alignment {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/package_alignment.schema.json");
}

/// Soil constants beyond the body registry, each with its honesty tag.
pub mod soil_baseline {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/soil_baseline.schema.json");
}

/// A rover agent profile as data (RW-30), every figure tagged with its source.
pub mod rover_profile {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/rover_profile.schema.json");
}

/// A suited-crew EVA profile as data (RW-30h, D-R78), every figure tagged with its page-cited source.
pub mod astronaut_profile {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/astronaut_profile.schema.json");

    /// Rules JSON Schema cannot express here: a FIGURE_READ value carries its reading uncertainty, and the
    /// grade table starts at level ground with strictly increasing grades.
    ///
    /// # Errors
    /// Returns a description of the first violated rule.
    pub fn check(p: &AstronautProfile) -> Result<(), String> {
        let m = &p.metabolic_w;
        let mut all = vec![
            ("alsep_deployment", &m.alsep_deployment),
            ("geology_station", &m.geology_station),
            ("overhead", &m.overhead),
            ("lrv_operations", &m.lrv_operations),
            ("all_activities", &m.all_activities),
            ("level_walk_speed_ms", &p.level_walk_speed_ms),
            ("level_walk_speed_sd_ms", &p.level_walk_speed_sd_ms),
            ("level_walk_metabolic_w", &p.level_walk_metabolic_w),
            ("level_walk_o2_kg_per_hr", &p.level_walk_o2_kg_per_hr),
            (
                "level_walk_cooling_water_kg_per_hr",
                &p.level_walk_cooling_water_kg_per_hr,
            ),
            ("apollo_o2_kg_per_hr", &p.apollo_o2_kg_per_hr),
            (
                "apollo_cooling_water_kg_per_hr",
                &p.apollo_cooling_water_kg_per_hr,
            ),
        ];
        all.extend(p.grade_vo2.iter().map(|g| ("grade_vo2", &g.vo2_ml_min_kg)));
        if let Some((k, _)) = all
            .iter()
            .find(|(_, t)| t.tag == Tag::FigureRead && t.uncertainty.is_none())
        {
            return Err(format!(
                "{k}: a FIGURE_READ value must carry its uncertainty"
            ));
        }
        let grades: Vec<f64> = p.grade_vo2.iter().map(|g| g.grade_pct).collect();
        if grades.first() != Some(&0.0) || grades.windows(2).any(|w| w[1] <= w[0]) {
            return Err(format!(
                "grade_vo2 grades {grades:?} must start at 0 and increase"
            ));
        }
        Ok(())
    }
}

/// The fleet registry: vehicles, tools, power sources and chargers (RW-33a).
pub mod fleet {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/fleet.schema.json");
}

/// An on-demand plugin's manifest (D-R01, RW-50).
pub mod plugin_manifest {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/plugin_manifest.schema.json");
}

/// A task check at a place (navigator N22 via the engine API, RW-56b).
pub mod assessment_request {
    #![allow(clippy::all, clippy::pedantic, missing_debug_implementations)]
    typify::import_types!(schema = "schema/assessment_request.schema.json");
}
