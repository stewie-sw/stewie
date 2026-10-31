//! Rise/set crossings and lit/shadow/unknown windows (navigator N8, requirements R6/R7).
//!
//! The measurable quantity is the upper-limb margin: the elevation of the top of the Sun's or Earth's disk
//! minus the known terrain horizon at its azimuth (horizon linear between azimuth bins). Its zero crossings
//! are first and last contact. The verdict is three-state: `Shadow` when the disk is below even the known
//! horizon, `Lit` only where the horizon sector is complete, and `Unknown` otherwise, because terrain beyond
//! the installed reach could still hide the body. A truncated horizon never yields `Lit`.

use std::fmt;

use lunar_ephem::{Body, EphemError, Ephemeris, az_el};
use lunar_frames::{LatLon, Sphere, body_fixed};
use lunar_horizon::Horizon;

#[derive(Debug, Clone, PartialEq)]
pub struct VisibilityConfig {
    /// Sampling step [s]; windows shorter than this can be missed.
    pub sample_s: f64,
    /// Bisection tolerance on crossing and boundary times [s].
    pub tolerance_s: f64,
    pub eye_height_m: f64,
    /// Terrain height under the observer [m above the sphere].
    pub ground_height_m: f64,
    /// The body sphere from the registry (never a literal here).
    pub moon: Sphere,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Lit,
    Shadow,
    Unknown,
}

/// A limb crossing of the known horizon.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Crossing {
    pub tdb: f64,
    /// True when the limb rises above the known horizon.
    pub rising: bool,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Window {
    pub start_tdb: f64,
    pub end_tdb: f64,
    pub verdict: Verdict,
}

#[derive(Debug)]
pub enum IntervalError {
    Ephemeris(EphemError),
    InvalidConfig(String),
    EmptyHorizon,
}

impl fmt::Display for IntervalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            IntervalError::Ephemeris(e) => write!(f, "{e}"),
            IntervalError::InvalidConfig(m) => write!(f, "invalid config: {m}"),
            IntervalError::EmptyHorizon => write!(f, "horizon has no azimuths"),
        }
    }
}

impl std::error::Error for IntervalError {}

impl From<EphemError> for IntervalError {
    fn from(e: EphemError) -> Self {
        IntervalError::Ephemeris(e)
    }
}

struct Observer<'a> {
    eph: &'a Ephemeris,
    horizon: &'a Horizon,
    site: LatLon,
    position_m: [f64; 3],
}

/// Upper-limb margin [deg] and whether the horizon sector at the body's azimuth is complete.
struct Sample {
    margin_deg: f64,
    complete: bool,
}

impl Observer<'_> {
    #[allow(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss
    )]
    fn sample(&self, body: Body, tdb: f64) -> Result<Sample, IntervalError> {
        let v = self.eph.apparent_from(body, tdb, self.position_m)?;
        let ae = az_el(v, self.site);
        let dist = v[0].hypot(v[1]).hypot(v[2]);
        let radius = self.eph.angular_radius_deg(body, dist)?;
        let n = self.horizon.az_deg.len();
        let k = ae.az_deg / (360.0 / n as f64);
        let k0 = (k.floor() as usize) % n;
        let k1 = (k0 + 1) % n;
        let f = k - k.floor();
        let (Some(h0), Some(h1)) = (self.horizon.elev_deg[k0], self.horizon.elev_deg[k1]) else {
            // no covered terrain in this sector: nothing is known, so the verdict is Unknown
            return Ok(Sample {
                margin_deg: ae.el_deg + radius + 90.0,
                complete: false,
            });
        };
        Ok(Sample {
            margin_deg: ae.el_deg + radius - ((1.0 - f) * h0 + f * h1),
            complete: self.horizon.complete[k0] && self.horizon.complete[k1],
        })
    }

    fn verdict(&self, body: Body, tdb: f64) -> Result<Verdict, IntervalError> {
        let s = self.sample(body, tdb)?;
        Ok(if s.margin_deg < 0.0 {
            Verdict::Shadow
        } else if s.complete {
            Verdict::Lit
        } else {
            Verdict::Unknown
        })
    }
}

fn observer<'a>(
    eph: &'a Ephemeris,
    horizon: &'a Horizon,
    site: LatLon,
    cfg: &VisibilityConfig,
) -> Result<Observer<'a>, IntervalError> {
    let valid = cfg.sample_s.is_finite()
        && cfg.sample_s > 0.0
        && cfg.tolerance_s.is_finite()
        && cfg.tolerance_s > 0.0;
    if !valid {
        return Err(IntervalError::InvalidConfig(format!("{cfg:?}")));
    }
    if horizon.az_deg.is_empty() {
        return Err(IntervalError::EmptyHorizon);
    }
    Ok(Observer {
        eph,
        horizon,
        site,
        position_m: body_fixed(cfg.moon, site, cfg.ground_height_m + cfg.eye_height_m),
    })
}

/// Sample times from `t0` to `t1` inclusive, `step` apart (the last step may be shorter).
fn sample_times(t0: f64, t1: f64, step: f64) -> Vec<f64> {
    let mut ts = Vec::new();
    let mut t = t0;
    while t < t1 {
        ts.push(t);
        t += step;
    }
    ts.push(t1);
    ts
}

/// Bisect `[lo, hi]` to `tol` for the boundary where `same_as_lo` turns false.
fn bisect(
    mut lo: f64,
    mut hi: f64,
    tol: f64,
    mut same_as_lo: impl FnMut(f64) -> Result<bool, IntervalError>,
) -> Result<f64, IntervalError> {
    while hi - lo > tol {
        let mid = 0.5 * (lo + hi);
        if same_as_lo(mid)? {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    Ok(0.5 * (lo + hi))
}

/// Upper-limb crossings of the known horizon by `body` between `t0` and `t1` (TDB seconds).
///
/// # Errors
/// An epoch outside the ephemeris span, an invalid config, or an empty horizon.
pub fn crossings(
    eph: &Ephemeris,
    horizon: &Horizon,
    site: LatLon,
    body: Body,
    t0: f64,
    t1: f64,
    cfg: &VisibilityConfig,
) -> Result<Vec<Crossing>, IntervalError> {
    let obs = observer(eph, horizon, site, cfg)?;
    let ts = sample_times(t0, t1, cfg.sample_s);
    let ms: Vec<f64> = ts
        .iter()
        .map(|&t| obs.sample(body, t).map(|s| s.margin_deg))
        .collect::<Result<_, _>>()?;
    let mut out = Vec::new();
    for i in 0..ts.len() - 1 {
        let below = ms[i] < 0.0;
        if below != (ms[i + 1] < 0.0) {
            let t = bisect(ts[i], ts[i + 1], cfg.tolerance_s, |t| {
                Ok((obs.sample(body, t)?.margin_deg < 0.0) == below)
            })?;
            out.push(Crossing {
                tdb: t,
                rising: below,
            });
        }
    }
    Ok(out)
}

/// Contiguous lit/shadow/unknown windows covering `[t0, t1]`, boundaries bisected to `tolerance_s`.
///
/// # Errors
/// As [`crossings`].
pub fn visibility_windows(
    eph: &Ephemeris,
    horizon: &Horizon,
    site: LatLon,
    body: Body,
    t0: f64,
    t1: f64,
    cfg: &VisibilityConfig,
) -> Result<Vec<Window>, IntervalError> {
    let obs = observer(eph, horizon, site, cfg)?;
    let ts = sample_times(t0, t1, cfg.sample_s);
    let vs: Vec<Verdict> = ts
        .iter()
        .map(|&t| obs.verdict(body, t))
        .collect::<Result<_, _>>()?;
    let mut out = Vec::new();
    let mut start = t0;
    for i in 0..ts.len() - 1 {
        if vs[i] != vs[i + 1] {
            let edge = bisect(ts[i], ts[i + 1], cfg.tolerance_s, |t| {
                Ok(obs.verdict(body, t)? == vs[i])
            })?;
            out.push(Window {
                start_tdb: start,
                end_tdb: edge,
                verdict: vs[i],
            });
            start = edge;
        }
    }
    out.push(Window {
        start_tdb: start,
        end_tdb: t1,
        verdict: vs[vs.len() - 1],
    });
    Ok(out)
}
