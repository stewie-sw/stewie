//! The current terrain view (Python `stewie.twin.terrain_view`, gap A2): the one planning surface, composed as
//! observed where measured, as-built where Terrain Memory changed it, pristine elsewhere, with each cell's
//! source kept so a planner can tell a measured cell from a remembered one. A layer of the wrong size is
//! ignored and contributes nothing: planning never fails on the world-model overlay.

/// Absolute elevation change that counts as built [m] (SR-17): absolute, because a relative tolerance on lunar
/// elevations scales with altitude; two orders below the 0.02 m acceptance flatness tolerance.
pub const AS_BUILT_EPS_M: f64 = 1e-4;

/// Per-cell provenance.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum Source {
    Pristine = 0,
    AsBuilt = 1,
    Observed = 2,
}

#[derive(Debug, Clone, PartialEq)]
pub struct TerrainView {
    pub heights: Vec<f64>,
    pub cell_m: f64,
    pub source: Vec<Source>,
    /// The Terrain Memory version folded in (0 when none or ignored).
    pub as_built_version: u64,
    /// The observed-twin version overlaid (0 when none or ignored).
    pub twin_version: u64,
    /// Fraction of cells taken from the observed twin.
    pub observed_fraction: f64,
}

/// Compose `base` (the pristine DEM) with an as-built surface `(heights, version)` and an observed surface
/// `(heights, measured mask, version)`, each optional and each ignored if it is not `base`'s size.
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn compose(
    base: &[f64],
    cell_m: f64,
    as_built: Option<(&[f64], u64)>,
    observed: Option<(&[f64], &[bool], u64)>,
) -> TerrainView {
    let n = base.len();
    let mut heights = base.to_vec();
    let mut source = vec![Source::Pristine; n];
    let mut as_built_version = 0;
    if let Some((ab, version)) = as_built
        && ab.len() == n
    {
        for i in (0..n).filter(|&i| (ab[i] - base[i]).abs() > AS_BUILT_EPS_M) {
            heights[i] = ab[i];
            source[i] = Source::AsBuilt;
        }
        as_built_version = version;
    }
    let mut twin_version = 0;
    if let Some((oh, mask, version)) = observed
        && oh.len() == n
        && mask.len() == n
        && mask.iter().any(|&m| m)
    {
        for i in (0..n).filter(|&i| mask[i]) {
            heights[i] = oh[i];
            source[i] = Source::Observed;
        }
        twin_version = version;
    }
    let observed = source.iter().filter(|&&s| s == Source::Observed).count();
    TerrainView {
        heights,
        cell_m,
        source,
        as_built_version,
        twin_version,
        observed_fraction: if n == 0 {
            0.0
        } else {
            observed as f64 / n as f64
        },
    }
}
