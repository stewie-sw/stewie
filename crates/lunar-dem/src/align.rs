//! Alignment of a terrain source to LOLA laser tracks (RW-60c, navigator N32, D-R105): the horizontal shift and
//! vertical offset that best put the source on the LOLA shots, and the residual RMS after them. A source sits in
//! the LOLA frame when its best shift is within a pixel and its residual is within the threshold for its resolution;
//! otherwise it may not enter a stack.
//!
//! Heights on both sides are radius minus the reference sphere. A shift is applied to each shot in its own local
//! east/north tangent frame and the source is sampled at the shifted point, so one search serves polar tiers and
//! global grids alike. The search is coarse to fine (whole pixels over the window, then eighth-pixels around the
//! best); at each shift the vertical offset is the mean residual (the least-squares offset) and the cost is the
//! residual variance over the shots the source covers. LOLA RDR extracts carry a few gross false returns (at Peary,
//! 23 of 228,464 shots, the worst 6.8 km off) that would dominate a plain RMS, so residuals more than
//! `OUTLIER_SIGMAS` robust sigmas (1.4826 x the median absolute deviation) from the median are set aside before the
//! offset, the cost and the reported RMS, and counted.

/// Residuals further than this many robust sigmas from the median are false returns, not terrain.
pub const OUTLIER_SIGMAS: f64 = 5.0;

use lunar_frames::LatLon;

use crate::TerrainSource;

/// One LOLA shot: planetocentric position and height above the reference sphere [m].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Shot {
    pub lat_deg: f64,
    pub lon_deg: f64,
    pub height_m: f64,
}

/// The best placement of a source on the shots.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Alignment {
    /// Move a shot this far east and north to find its terrain in the source [m].
    pub shift_east_m: f64,
    pub shift_north_m: f64,
    /// LOLA height minus source height, on average [m].
    pub vertical_offset_m: f64,
    /// RMS of the residuals after the shift and offset [m].
    pub residual_rms_m: f64,
    /// Shots the source covers at the best shift and that are not set aside.
    pub shots_used: usize,
    /// Shots set aside as false returns.
    pub shots_rejected: usize,
}

impl Alignment {
    /// The horizontal shift's length [m].
    #[must_use]
    pub fn shift_m(&self) -> f64 {
        self.shift_east_m.hypot(self.shift_north_m)
    }
}

/// The residual RMS a source of `resolution_m` may show against LOLA and still enter a stack: 2 m (LOLA ranging and
/// geolocation) plus 5 % of the cell (gridding error grows with the cell over relief). The threshold catches a
/// source whose terrain does not match LOLA's at its claimed resolution; a misregistered source is caught by the
/// one-pixel shift rule. On the pinned boxes the LOLA tiers fit at 0.87 m (40 m, threshold 4 m), 2.82 m and 2.60 m
/// (240 m, 14 m) and 74.6 m (the 1.9 km global grid over the Apennine relief at Hadley, 96.7 m).
#[must_use]
pub fn max_residual_rms_m(resolution_m: f64) -> f64 {
    2.0 + 0.05 * resolution_m
}

/// Whether an alignment admits its source: shifted by at most one pixel, and within the residual threshold.
#[must_use]
pub fn admits(a: &Alignment, resolution_m: f64) -> bool {
    a.shift_m() <= resolution_m && a.residual_rms_m <= max_residual_rms_m(resolution_m)
}

/// A shot moved `east`, `north` metres in its local tangent frame on a sphere of `radius_m`.
fn moved(s: &Shot, (east, north): (f64, f64), radius_m: f64) -> LatLon {
    let lat = s.lat_deg + (north / radius_m).to_degrees();
    let lon = s.lon_deg + (east / (radius_m * s.lat_deg.to_radians().cos())).to_degrees();
    LatLon {
        lat_deg: lat,
        lon_deg: lon,
    }
}

fn median(v: &mut [f64]) -> f64 {
    v.sort_by(f64::total_cmp);
    let m = v.len() / 2;
    if v.len() % 2 == 1 {
        v[m]
    } else {
        f64::midpoint(v[m - 1], v[m])
    }
}

/// (offset, variance, kept, rejected) of the residuals at one shift after setting aside false returns; None when
/// fewer than `min_shots` are covered.
#[allow(clippy::cast_precision_loss)]
fn fit(
    source: &dyn TerrainSource,
    shots: &[Shot],
    d: (f64, f64),
    min_shots: usize,
) -> Option<(f64, f64, usize, usize)> {
    let radius = source.sphere().radius_m();
    let r: Vec<f64> = shots
        .iter()
        .filter_map(|s| {
            source
                .sample_latlon(moved(s, d, radius))
                .map(|z| s.height_m - z)
        })
        .collect();
    if r.len() < min_shots.max(1) {
        return None;
    }
    let med = median(&mut r.clone());
    let sigma = 1.4826 * median(&mut r.iter().map(|x| (x - med).abs()).collect::<Vec<_>>());
    let kept: Vec<f64> = r
        .iter()
        .copied()
        .filter(|x| (x - med).abs() <= OUTLIER_SIGMAS * sigma)
        .collect();
    if kept.is_empty() {
        return None;
    }
    let n = kept.len() as f64;
    let mean = kept.iter().sum::<f64>() / n;
    let var = kept.iter().map(|x| (x - mean) * (x - mean)).sum::<f64>() / n;
    Some((mean, var, kept.len(), r.len() - kept.len()))
}

/// Align `source` to `shots`, searching shifts up to `search_px` of its pixels; `min_shots` covered shots are
/// required at every shift.
///
/// # Errors
/// Fewer than `min_shots` shots on the source.
#[allow(clippy::cast_precision_loss, clippy::cast_possible_wrap)]
pub fn align(
    source: &dyn TerrainSource,
    shots: &[Shot],
    search_px: usize,
    min_shots: usize,
) -> Result<Alignment, String> {
    let cell = source.resolution_m();
    // the search uses a subsample of the shots; the reported fit uses all of them
    let stride = (shots.len() / 20_000).max(1);
    let few: Vec<Shot> = shots.iter().step_by(stride).copied().collect();
    let few_min = (min_shots / stride).max(1);
    let mut best: Option<((f64, f64), f64)> = None;
    let consider = |best: &mut Option<((f64, f64), f64)>, d: (f64, f64)| {
        if let Some((_, var, _, _)) = fit(source, &few, d, few_min)
            && best.is_none_or(|(_, v)| var < v)
        {
            *best = Some((d, var));
        }
    };
    let s = search_px as i64;
    for i in -s..=s {
        for j in -s..=s {
            consider(&mut best, (i as f64 * cell, j as f64 * cell));
        }
    }
    let coarse = best.map(|(d, _)| d);
    let (ce, cn) = coarse
        .ok_or_else(|| format!("fewer than {min_shots} LOLA shots fall on {}", source.id()))?;
    for i in -8_i64..=8 {
        for j in -8_i64..=8 {
            consider(
                &mut best,
                (ce + i as f64 * cell / 8.0, cn + j as f64 * cell / 8.0),
            );
        }
    }
    let ((de, dn), _) = best.ok_or("no fit")?;
    let (mean, var, used, rejected) = fit(source, shots, (de, dn), min_shots)
        .ok_or_else(|| format!("fewer than {min_shots} LOLA shots fall on {}", source.id()))?;
    Ok(Alignment {
        shift_east_m: de,
        shift_north_m: dn,
        vertical_offset_m: mean,
        residual_rms_m: var.sqrt(),
        shots_used: used,
        shots_rejected: rejected,
    })
}

/// Shots from an ODE simple-topography CSV (`Pt_Longitude, Pt_Latitude, Topography`; longitude east 0-360).
///
/// # Errors
/// A header or row that is not that shape.
pub fn parse_shots(csv: &str) -> Result<Vec<Shot>, String> {
    let mut lines = csv.lines();
    let header = lines.next().ok_or("empty shot file")?;
    let cols: Vec<&str> = header.split(',').map(str::trim).collect();
    if cols != ["Pt_Longitude", "Pt_Latitude", "Topography"] {
        return Err(format!("unexpected shot header {header:?}"));
    }
    lines
        .filter(|l| !l.trim().is_empty())
        .enumerate()
        .map(|(k, l)| {
            let v: Vec<f64> = l
                .split(',')
                .map(|x| {
                    x.trim()
                        .parse::<f64>()
                        .map_err(|e| format!("row {}: {e}", k + 1))
                })
                .collect::<Result<_, _>>()?;
            match v.as_slice() {
                [lon, lat, h] => Ok(Shot {
                    lat_deg: *lat,
                    lon_deg: if *lon > 180.0 { lon - 360.0 } else { *lon },
                    height_m: *h,
                }),
                _ => Err(format!("row {}: {} fields", k + 1, v.len())),
            }
        })
        .collect()
}
