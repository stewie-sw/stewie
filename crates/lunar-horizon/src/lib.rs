//! Terrain horizon and disk visibility (navigator N7/N8a, requirement R4).
//!
//! Rays are great circles on the body sphere, `n_az` of them clockwise from north, sampled every `step_m`
//! of arc out to `max_range_m` through a [`TerrainStack`]. The elevation of each sample is exact spherical
//! geometry (curvature included) from an eye `eye_height_m` above the terrain. A ray stops where the
//! installed terrain ends: its `reach_m` falls short and `complete` is false, so the caller can report an
//! unknown sector instead of assuming open sky.

use std::collections::BTreeSet;
use std::fmt;

use lunar_dem::{Resolved, TerrainStack};
use lunar_frames::LatLon;

#[derive(Debug, Clone, PartialEq)]
pub struct HorizonConfig {
    pub n_az: usize,
    pub max_range_m: f64,
    pub step_m: f64,
    pub eye_height_m: f64,
    /// Terrain nearer than this [m] does not count toward the horizon: the observer's own DEM cell(s),
    /// which a gridded surface cannot resolve as an obstruction. 0 counts every sample.
    pub start_m: f64,
}

/// Per-azimuth horizon. `elev_deg[k]` is `None` when not even the first step is covered.
#[derive(Debug, Clone, PartialEq)]
pub struct Horizon {
    pub az_deg: Vec<f64>,
    pub elev_deg: Vec<Option<f64>>,
    pub reach_m: Vec<f64>,
    pub complete: Vec<bool>,
    /// Ids of every terrain source a ray sampled.
    pub sources: Vec<String>,
}

#[derive(Debug, Clone, PartialEq)]
pub enum HorizonError {
    /// No installed terrain under the observer: cannot assess.
    NotCovered,
    InvalidConfig(String),
}

impl fmt::Display for HorizonError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            HorizonError::NotCovered => write!(f, "no installed terrain covers the observer"),
            HorizonError::InvalidConfig(m) => write!(f, "invalid horizon config: {m}"),
        }
    }
}

impl std::error::Error for HorizonError {}

/// Compute the horizon at `at`.
///
/// # Errors
/// [`HorizonError::NotCovered`] when no source covers the observer; [`HorizonError::InvalidConfig`] for a
/// zero azimuth count, a non-positive step, a range shorter than one step, or a `start_m` outside `[0, max_range_m)`.
#[allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)]
pub fn horizon(
    stack: &TerrainStack,
    at: LatLon,
    cfg: &HorizonConfig,
) -> Result<Horizon, HorizonError> {
    let valid = cfg.step_m.is_finite()
        && cfg.step_m > 0.0
        && cfg.max_range_m.is_finite()
        && cfg.max_range_m >= cfg.step_m
        && cfg.start_m.is_finite()
        && cfg.start_m >= 0.0
        && cfg.start_m < cfg.max_range_m;
    if cfg.n_az == 0 || !valid {
        return Err(HorizonError::InvalidConfig(format!("{cfg:?}")));
    }
    let radius = stack.sphere().ok_or(HorizonError::NotCovered)?.radius_m();
    let Resolved::Covered {
        height_m: ground, ..
    } = stack.resolve(at)
    else {
        return Err(HorizonError::NotCovered);
    };
    let ro = radius + ground + cfg.eye_height_m;
    let n_steps = (cfg.max_range_m / cfg.step_m).floor() as usize;
    let (phi1, lam1) = (at.lat_deg.to_radians(), at.lon_deg.to_radians());
    let (sp1, cp1) = phi1.sin_cos();
    let mut out = Horizon {
        az_deg: Vec::with_capacity(cfg.n_az),
        elev_deg: Vec::with_capacity(cfg.n_az),
        reach_m: Vec::with_capacity(cfg.n_az),
        complete: Vec::with_capacity(cfg.n_az),
        sources: Vec::new(),
    };
    let mut seen = BTreeSet::new();
    for k in 0..cfg.n_az {
        let az_deg = 360.0 * k as f64 / cfg.n_az as f64;
        let (sa, ca) = az_deg.to_radians().sin_cos();
        let mut best: Option<f64> = None;
        let mut reach = 0.0;
        let mut covered_all = true;
        for i in 1..=n_steps {
            let s = i as f64 * cfg.step_m;
            let delta = s / radius;
            let (sd, cd) = delta.sin_cos();
            let phi2 = (sp1 * cd + cp1 * sd * ca).asin();
            let lam2 = lam1 + (sa * sd * cp1).atan2(cd - sp1 * phi2.sin());
            let ll = LatLon {
                lat_deg: phi2.to_degrees(),
                lon_deg: lam2.to_degrees(),
            };
            let Resolved::Covered { source, height_m } = stack.resolve(ll) else {
                covered_all = false;
                break;
            };
            if !seen.contains(&source.id) {
                seen.insert(source.id.clone());
            }
            reach = s;
            if s < cfg.start_m {
                continue;
            }
            let rt = radius + height_m;
            let elev = (rt * cd - ro).atan2(rt * sd);
            best = Some(best.map_or(elev, |b: f64| b.max(elev)));
        }
        out.az_deg.push(az_deg);
        out.elev_deg.push(best.map(f64::to_degrees));
        out.reach_m.push(reach);
        out.complete.push(covered_all);
    }
    out.sources = seen.into_iter().collect();
    Ok(out)
}

/// Fraction of a disk of angular radius `radius_deg` centred at elevation `centre_el_deg` that lies above
/// a horizon at `horizon_el_deg` (the horizon treated as straight across the disk).
#[must_use]
pub fn disk_fraction_visible(centre_el_deg: f64, radius_deg: f64, horizon_el_deg: f64) -> f64 {
    let d = (centre_el_deg - horizon_el_deg) / radius_deg;
    if d >= 1.0 {
        1.0
    } else if d <= -1.0 {
        0.0
    } else {
        1.0 - (d.acos() - d * (1.0 - d * d).sqrt()) / std::f64::consts::PI
    }
}
