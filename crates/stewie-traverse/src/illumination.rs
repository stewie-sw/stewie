//! The illumination route-cost layer (RW-15a; Python `dart.illumination_cost`, `dart.shadow_predict.cast_shadow_mask`,
//! `dart.visibility.is_visible`/`viewshed`), fed by the Rust ephemeris instead of hand-supplied Sun angles.
//!
//! Each term is returned separately so an operator can see why a cell is expensive: shadow hazard (an unlit cell
//! cannot get a fiducial lock), saturation (lit under a grazing Sun, so perception washes out), map uncertainty
//! (when a coverage field is given; otherwise zero), and visibility (no line of sight to any localization anchor).
//! The weights and the grazing threshold are configuration ([CALIB] in the Python). Cells step toward the Sun with
//! Python's round-half-even, so the masks are the Python's cell for cell.

use lunar_ephem::{AzEl, Body, EphemError, Ephemeris, Utc, az_el};
use lunar_frames::LatLon;

use crate::costmap::Illumination;

/// The term weights and the grazing-Sun threshold.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct IlluminationWeights {
    pub shadow: f64,
    pub saturation: f64,
    pub map_uncertainty: f64,
    pub visibility: f64,
    /// Below this Sun elevation a lit cell risks washout [deg].
    pub grazing_el_deg: f64,
}

/// A heightmap: row-major `z`, `width` columns, `height` rows, square cells; `origin` is the world position of
/// cell (0, 0).
#[derive(Debug, Clone, Copy)]
pub struct Heightmap<'a> {
    pub z: &'a [f64],
    pub width: usize,
    pub height: usize,
    pub cell_m: f64,
    pub origin: (f64, f64),
}

/// The up-Sun march direction `(d_row, d_col)`: azimuth clockwise from north, row = north, col = east.
#[must_use]
pub fn sun_march_dir_rowcol(sun_az_deg: f64) -> (f64, f64) {
    let a = sun_az_deg.to_radians();
    (a.cos(), a.sin())
}

#[allow(clippy::cast_possible_truncation)] // a grid step, finite and small
fn round_index(v: f64) -> i64 {
    v.round_ties_even() as i64
}

/// Cells in cast shadow: marching toward the Sun, some terrain rises above the Sun-elevation ray from the cell
/// within `max_range_m`. Everything is shadowed when the Sun is down.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss,
    clippy::cast_possible_wrap
)]
pub fn cast_shadow_mask(h: &Heightmap<'_>, sun: AzEl, max_range_m: f64) -> Vec<bool> {
    let n_cells = h.width * h.height;
    if sun.el_deg <= 0.0 {
        return vec![true; n_cells];
    }
    let (dr, dc) = sun_march_dir_rowcol(sun.az_deg);
    let tan_el = sun.el_deg.to_radians().tan();
    let steps = ((max_range_m / h.cell_m) as i64).max(1);
    let (rows, cols) = (h.height as i64, h.width as i64);
    (0..n_cells)
        .map(|i| {
            let (r, c) = ((i / h.width) as i64, (i % h.width) as i64);
            let z0 = h.z[i];
            for k in 1..=steps {
                let kf = k as f64;
                let (ri, ci) = (
                    round_index(r as f64 + dr * kf),
                    round_index(c as f64 + dc * kf),
                );
                if !(0..rows).contains(&ri) || !(0..cols).contains(&ci) {
                    break;
                }
                if h.z[(ri * cols + ci) as usize] > z0 + kf * h.cell_m * tan_el {
                    return true;
                }
            }
            false
        })
        .collect()
}

#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap
)]
fn height_at(h: &Heightmap<'_>, x: f64, y: f64) -> Option<f64> {
    let (ri, ci) = (
        round_index((y - h.origin.1) / h.cell_m),
        round_index((x - h.origin.0) / h.cell_m),
    );
    ((0..h.height as i64).contains(&ri) && (0..h.width as i64).contains(&ci))
        .then(|| h.z[ri as usize * h.width + ci as usize])
}

/// Line of sight from an observer `observer_height_m` above the ground at `from` to a target `target_height_m`
/// above the ground at `to`: occluded where terrain on the ray rises above the sightline. Off the map is blind.
#[must_use]
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_precision_loss
)]
pub fn is_visible(
    h: &Heightmap<'_>,
    from: (f64, f64),
    to: (f64, f64),
    observer_height_m: f64,
    target_height_m: f64,
) -> bool {
    let (Some(z0), Some(zt)) = (height_at(h, from.0, from.1), height_at(h, to.0, to.1)) else {
        return false;
    };
    let (z0, zt) = (z0 + observer_height_m, zt + target_height_m);
    let dist = (to.0 - from.0).hypot(to.1 - from.1);
    if dist < h.cell_m {
        return true;
    }
    // more steps than cells, so a one-cell occluder cannot be stepped over
    let n = ((dist / h.cell_m).ceil() as usize + 1).max(2);
    for i in 1..n {
        let f = i as f64 / n as f64;
        let Some(zh) = height_at(
            h,
            from.0 + (to.0 - from.0) * f,
            from.1 + (to.1 - from.1) * f,
        ) else {
            return false;
        };
        if zh > z0 + (zt - z0) * f + 1e-6 {
            return false;
        }
    }
    true
}

/// Per cell: can an observer standing there see at least one anchor?
#[must_use]
#[allow(clippy::cast_precision_loss)]
pub fn viewshed(
    h: &Heightmap<'_>,
    anchors: &[(f64, f64)],
    observer_height_m: f64,
    target_height_m: f64,
) -> Vec<bool> {
    (0..h.width * h.height)
        .map(|i| {
            let at = (
                h.origin.0 + (i % h.width) as f64 * h.cell_m,
                h.origin.1 + (i / h.width) as f64 * h.cell_m,
            );
            anchors
                .iter()
                .any(|&a| is_visible(h, at, a, observer_height_m, target_height_m))
        })
        .collect()
}

/// The separable illumination cost and its weighted total.
#[derive(Debug, Clone, PartialEq)]
pub struct IlluminationCost {
    /// The terms, as the costmap takes them.
    pub layer: Illumination,
    pub total: Vec<f64>,
}

/// The illumination cost of every cell under the Sun at `sun`. `los` (cells with sight of an anchor) switches
/// the visibility term on; `map_uncertainty` the map term.
///
/// # Errors
/// A map-uncertainty or line-of-sight layer of the wrong size.
pub fn illumination_cost(
    h: &Heightmap<'_>,
    sun: AzEl,
    max_range_m: f64,
    map_uncertainty: Option<&[f64]>,
    los: Option<&[bool]>,
    w: &IlluminationWeights,
) -> Result<IlluminationCost, String> {
    let n = h.width * h.height;
    let shadowed = cast_shadow_mask(h, sun, max_range_m);
    let shadow: Vec<f64> = shadowed
        .iter()
        .map(|&s| if s { 1.0 } else { 0.0 })
        .collect();
    let graze = ((w.grazing_el_deg - sun.el_deg) / w.grazing_el_deg).max(0.0);
    let saturation: Vec<f64> = shadowed
        .iter()
        .map(|&s| if s { 0.0 } else { graze })
        .collect();
    let mu = match map_uncertainty {
        Some(m) if m.len() == n => m.to_vec(),
        Some(m) => {
            return Err(format!(
                "map uncertainty has {} cells, the map {n}",
                m.len()
            ));
        }
        None => vec![0.0; n],
    };
    let visibility = match los {
        Some(l) if l.len() == n => l.iter().map(|&v| if v { 0.0 } else { 1.0 }).collect(),
        Some(l) => {
            return Err(format!(
                "line-of-sight layer has {} cells, the map {n}",
                l.len()
            ));
        }
        None => vec![0.0; n],
    };
    let total = (0..n)
        .map(|i| {
            w.shadow * shadow[i]
                + w.saturation * saturation[i]
                + w.map_uncertainty * mu[i]
                + w.visibility * visibility[i]
        })
        .collect();
    Ok(IlluminationCost {
        layer: Illumination::Terms {
            shadow_hazard: shadow,
            saturation,
            map_uncertainty: mu,
            visibility,
            weights: [w.shadow, w.saturation, w.map_uncertainty, w.visibility],
        },
        total,
    })
}

/// The apparent Sun's azimuth and elevation at a surface site at `utc`, from the packed DE440 ephemeris.
///
/// # Errors
/// A time outside the ephemeris span.
pub fn sun_at(
    eph: &Ephemeris,
    site: LatLon,
    site_position_m: [f64; 3],
    utc: &Utc,
) -> Result<AzEl, EphemError> {
    let tdb = eph.tdb(utc);
    Ok(az_el(
        eph.apparent_from(Body::Sun, tdb, site_position_m)?,
        site,
    ))
}

/// Where a Sun direction came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SolarSource {
    /// Measured in a camera image.
    DirectImage,
    /// Predicted from the ephemeris, declared as such (never passed off as image-derived).
    EphemerisFallback,
}

impl SolarSource {
    #[must_use]
    pub fn name(self) -> &'static str {
        match self {
            Self::DirectImage => "DIRECT_IMAGE",
            Self::EphemerisFallback => "EPHEMERIS_FALLBACK",
        }
    }
}

/// A Sun-direction observation with its covariance (Python `dart.solar_observation.SolarObservation`).
#[derive(Debug, Clone, PartialEq)]
pub struct SolarObservation {
    pub azimuth_deg: f64,
    pub elevation_deg: f64,
    pub variance_azimuth_deg2: f64,
    pub variance_elevation_deg2: f64,
    pub source: SolarSource,
    pub covariance_calibrated: bool,
    pub sample_id: String,
    pub coordinate_frame: String,
    pub provenance: String,
}

impl SolarObservation {
    /// Check the observation: finite values, the Sun above the horizon and below the zenith, non-negative
    /// variances, a sample id.
    ///
    /// # Errors
    /// The first rule broken, in the Python's words.
    pub fn validated(self) -> Result<Self, String> {
        let values = [
            self.azimuth_deg,
            self.elevation_deg,
            self.variance_azimuth_deg2,
            self.variance_elevation_deg2,
        ];
        if !values.iter().all(|v| v.is_finite()) {
            return Err("solar observation values must be finite".to_owned());
        }
        if !(0.0 < self.elevation_deg && self.elevation_deg < 90.0) {
            return Err("solar elevation must be in (0, 90) degrees".to_owned());
        }
        if self.variance_azimuth_deg2 < 0.0 || self.variance_elevation_deg2 < 0.0 {
            return Err("solar variances must be nonnegative".to_owned());
        }
        if self.sample_id.is_empty() {
            return Err("solar sample_id is required".to_owned());
        }
        Ok(self)
    }
}

/// Declare an ephemeris-only Sun direction with its one-sigma errors, without pretending it is image-derived.
///
/// # Errors
/// A negative sigma, or an observation [`SolarObservation::validated`] refuses.
pub fn ephemeris_fallback(
    sun: AzEl,
    sample_id: &str,
    (sigma_azimuth_deg, sigma_elevation_deg): (f64, f64),
    covariance_calibrated: bool,
) -> Result<SolarObservation, String> {
    let nonneg = |v: f64, name: &str| {
        if v < 0.0 {
            // Rust's `{:?}` of a float is the Python repr for these values (-0.5, -1.0)
            Err(format!("{name} must be >= 0 (got {v:?})"))
        } else {
            Ok(v)
        }
    };
    let (sa, se) = (
        nonneg(sigma_azimuth_deg, "sigma_azimuth_deg")?,
        nonneg(sigma_elevation_deg, "sigma_elevation_deg")?,
    );
    SolarObservation {
        azimuth_deg: sun.az_deg.rem_euclid(360.0),
        elevation_deg: sun.el_deg,
        variance_azimuth_deg2: sa * sa,
        variance_elevation_deg2: se * se,
        source: SolarSource::EphemerisFallback,
        covariance_calibrated,
        sample_id: sample_id.to_owned(),
        coordinate_frame: "GODOT_WORLD".to_owned(),
        provenance: "RUNTIME_PARAMETER".to_owned(),
    }
    .validated()
}

/// The ephemeris fallback for a site and time, from the packed DE440 ephemeris.
///
/// # Errors
/// A time outside the ephemeris span, or as [`ephemeris_fallback`] (e.g. the Sun below the horizon).
pub fn ephemeris_fallback_at(
    eph: &Ephemeris,
    (site, site_position_m): (LatLon, [f64; 3]),
    utc: &Utc,
    sample_id: &str,
    sigmas_deg: (f64, f64),
) -> Result<SolarObservation, String> {
    let sun = sun_at(eph, site, site_position_m, utc).map_err(|e| e.to_string())?;
    ephemeris_fallback(sun, sample_id, sigmas_deg, false)
}
