//! DE440 Sun and Earth positions for the Moon without SPICE at runtime (navigator N6, requirement R3).
//!
//! `pipeline/ephem_pack.py` fits light-time-corrected Sun and Earth vectors seen from the Moon's centre in
//! `MOON_ME_DE440_ME421` (the LOLA terrain frame), plus the Moon's barycentric velocity in the same axes,
//! to fixed-length Chebyshev segments in TDB, and records the LSK leap-second table and TDB-TT constants.
//! This crate converts UTC to TDB the way SPICE does, subtracts the observer's position, applies stellar
//! aberration to that topocentric direction (SPICE `stelab`), and refuses any epoch outside the span.

use std::fmt;
use std::path::Path;

use lunar_frames::{LatLon, enu_basis};
use serde::Deserialize;
use sha2::{Digest, Sha256};

const BUNDLED_HEADER: &str = include_str!("../data/moon_de440_2026_2035.json");
const BUNDLED_BIN: &[u8] = include_bytes!("../data/moon_de440_2026_2035.bin");

/// A target the package carries.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Body {
    Sun,
    Earth,
}

impl Body {
    fn naif_name(self) -> &'static str {
        match self {
            Body::Sun => "SUN",
            Body::Earth => "EARTH",
        }
    }
}

const MOON_VELOCITY: &str = "MOON_SSB_VELOCITY";
const SPEED_OF_LIGHT_M_S: f64 = 299_792_458.0;

#[derive(Debug)]
pub enum EphemError {
    Io {
        path: String,
        source: std::io::Error,
    },
    Header(String),
    Integrity {
        expected: String,
        actual: String,
    },
    OutOfSpan {
        tdb: f64,
        start: f64,
        end: f64,
    },
    MissingTarget(&'static str),
    Time(String),
}

impl fmt::Display for EphemError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            EphemError::Io { path, source } => write!(f, "{path}: {source}"),
            EphemError::Header(m) => write!(f, "ephemeris header: {m}"),
            EphemError::Integrity { expected, actual } => {
                write!(f, "coefficient sha256 {actual} != header {expected}")
            }
            EphemError::OutOfSpan { tdb, start, end } => {
                write!(f, "TDB {tdb} s is outside the packed span [{start}, {end})")
            }
            EphemError::MissingTarget(t) => write!(f, "package has no {t} segments"),
            EphemError::Time(m) => write!(f, "time: {m}"),
        }
    }
}

impl std::error::Error for EphemError {}

#[derive(Debug, Deserialize)]
struct Lsk {
    delta_at: Vec<[f64; 2]>,
    delta_t_a: f64,
    k: f64,
    eb: f64,
    m0: f64,
    m1: f64,
}

#[derive(Debug, Deserialize)]
struct Header {
    format: String,
    frame: String,
    targets: Vec<String>,
    start_tdb: f64,
    segment_s: f64,
    n_segments: usize,
    degree: usize,
    lsk: Lsk,
    radii_m: std::collections::BTreeMap<String, [f64; 3]>,
    bin_sha256: String,
}

/// A UTC instant (no leap-second instants: seconds are 0 to <60).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Utc {
    /// Seconds past 2000-01-01T12:00:00 UTC counted without leap seconds (the SPICE convention).
    seconds_past_j2000: f64,
}

impl Utc {
    /// Parse `YYYY-MM-DDTHH:MM:SS[.fff]Z`.
    ///
    /// # Errors
    /// Any other shape, or an out-of-range field.
    pub fn parse_iso8601(text: &str) -> Result<Self, EphemError> {
        let bad = || EphemError::Time(format!("not an ISO 8601 UTC instant: {text:?}"));
        let body = text.strip_suffix('Z').ok_or_else(bad)?;
        let (date, time) = body.split_once('T').ok_or_else(bad)?;
        let date_parts: Vec<&str> = date.split('-').collect();
        let time_parts: Vec<&str> = time.split(':').collect();
        if date_parts.len() != 3
            || time_parts.len() != 3
            || date_parts[0].len() != 4
            || date_parts[1].len() != 2
            || date_parts[2].len() != 2
        {
            return Err(bad());
        }
        let num = |field: &str| field.parse::<i64>().map_err(|_| bad());
        let (year, month, day) = (
            num(date_parts[0])?,
            num(date_parts[1])?,
            num(date_parts[2])?,
        );
        let (hour, minute) = (num(time_parts[0])?, num(time_parts[1])?);
        let second: f64 = time_parts[2].parse().map_err(|_| bad())?;
        if !(1..=12).contains(&month) || day < 1 || day > days_in_month(year, month) {
            return Err(bad());
        }
        if !(0..24).contains(&hour) || !(0..60).contains(&minute) || !(0.0..60.0).contains(&second)
        {
            return Err(bad());
        }
        let days = days_from_civil(year, month, day) - days_from_civil(2000, 1, 1);
        #[allow(clippy::cast_precision_loss)] // day counts and clock fields are tiny
        let seconds_past_j2000 =
            days as f64 * 86_400.0 + (hour * 3600 + minute * 60) as f64 + second - 43_200.0;
        Ok(Self { seconds_past_j2000 })
    }
}

fn is_leap(y: i64) -> bool {
    (y % 4 == 0 && y % 100 != 0) || y % 400 == 0
}

fn days_in_month(y: i64, m: i64) -> i64 {
    match m {
        2 if is_leap(y) => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// Days since 1970-01-01 of a proleptic Gregorian date (Howard Hinnant's algorithm).
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

/// Topocentric azimuth (deg from north through east, [0, 360)) and elevation (deg).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AzEl {
    pub az_deg: f64,
    pub el_deg: f64,
}

/// Azimuth and elevation of a body-fixed direction seen from `site`.
#[must_use]
pub fn az_el(v: [f64; 3], site: LatLon) -> AzEl {
    let [e, n, u] = enu_basis(site);
    let dot = |a: [f64; 3]| a[0] * v[0] + a[1] * v[1] + a[2] * v[2];
    let (ve, vn, vu) = (dot(e), dot(n), dot(u));
    AzEl {
        az_deg: ve.atan2(vn).to_degrees().rem_euclid(360.0),
        el_deg: vu.atan2(ve.hypot(vn)).to_degrees(),
    }
}

/// The packed ephemeris.
#[derive(Debug)]
pub struct Ephemeris {
    header: Header,
    coeffs: Vec<f64>,
}

impl Ephemeris {
    /// The 2026-2035 DE440 package compiled into this crate.
    ///
    /// # Errors
    /// A malformed header or a coefficient block that fails its sha256.
    pub fn bundled() -> Result<Self, EphemError> {
        Self::from_parts(BUNDLED_HEADER, BUNDLED_BIN)
    }

    /// Load `<name>.json` and `<name>.bin` from `dir`.
    ///
    /// # Errors
    /// I/O failure, a malformed header, or a coefficient block that fails its sha256.
    pub fn load(dir: &Path, name: &str) -> Result<Self, EphemError> {
        let read = |ext: &str| {
            let p = dir.join(format!("{name}.{ext}"));
            std::fs::read(&p).map_err(|source| EphemError::Io {
                path: p.display().to_string(),
                source,
            })
        };
        let header =
            String::from_utf8(read("json")?).map_err(|e| EphemError::Header(e.to_string()))?;
        Self::from_parts(&header, &read("bin")?)
    }

    fn from_parts(header: &str, bin: &[u8]) -> Result<Self, EphemError> {
        let header: Header =
            serde_json::from_str(header).map_err(|e| EphemError::Header(e.to_string()))?;
        if header.format != "stewie-ephem-chebyshev-v1" || header.frame != "MOON_ME_DE440_ME421" {
            return Err(EphemError::Header(format!(
                "unsupported {} in {}",
                header.format, header.frame
            )));
        }
        let actual = Sha256::digest(bin).iter().fold(String::new(), |mut s, b| {
            use fmt::Write as _;
            let _ = write!(s, "{b:02x}");
            s
        });
        if actual != header.bin_sha256 {
            return Err(EphemError::Integrity {
                expected: header.bin_sha256,
                actual,
            });
        }
        let want = header.n_segments * header.targets.len() * 3 * (header.degree + 1) * 8;
        if bin.len() != want {
            return Err(EphemError::Header(format!(
                "{} coefficient bytes, layout needs {want}",
                bin.len()
            )));
        }
        let coeffs = bin
            .chunks_exact(8)
            .map(|c| f64::from_le_bytes([c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7]]))
            .collect();
        Ok(Self { header, coeffs })
    }

    /// The packed span `[start, end)` in TDB seconds past J2000; any epoch outside it is refused.
    #[must_use]
    #[allow(clippy::cast_precision_loss)] // the segment count is far below 2^52
    pub fn span_tdb(&self) -> (f64, f64) {
        let h = &self.header;
        (h.start_tdb, h.start_tdb + h.segment_s * h.n_segments as f64)
    }

    /// TDB seconds past J2000 for a UTC instant, using the packaged LSK (SPICE `str2et` semantics).
    #[must_use]
    pub fn tdb(&self, utc: &Utc) -> f64 {
        let l = &self.header.lsk;
        let s = utc.seconds_past_j2000;
        let delta_at = l
            .delta_at
            .iter()
            .take_while(|e| e[0] <= s)
            .last()
            .map_or(0.0, |e| e[1]);
        let tt = s + delta_at + l.delta_t_a;
        let mut et = tt;
        for _ in 0..3 {
            let m = l.m0 + l.m1 * et;
            et = tt + l.k * (m + l.eb * m.sin()).sin();
        }
        et
    }

    /// Angular radius [deg] of `body` at `distance_m`, using its smallest PCK radius so an upper-limb
    /// visibility test is never optimistic (R7).
    ///
    /// # Errors
    /// [`EphemError::MissingTarget`] when the package has no radii for `body`.
    pub fn angular_radius_deg(&self, body: Body, distance_m: f64) -> Result<f64, EphemError> {
        let r = self
            .header
            .radii_m
            .get(body.naif_name())
            .ok_or(EphemError::MissingTarget(body.naif_name()))?;
        let min_r = r[0].min(r[1]).min(r[2]);
        Ok((min_r / distance_m).asin().to_degrees())
    }

    /// Body position [m] relative to the Moon's centre in `MOON_ME_DE440_ME421`, light-time corrected (LT).
    ///
    /// # Errors
    /// [`EphemError::OutOfSpan`] outside the packed span; [`EphemError::MissingTarget`].
    pub fn position(&self, body: Body, tdb: f64) -> Result<[f64; 3], EphemError> {
        self.series(body.naif_name(), tdb)
    }

    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        clippy::cast_precision_loss
    )]
    fn series(&self, name: &'static str, tdb: f64) -> Result<[f64; 3], EphemError> {
        let h = &self.header;
        let (start, end) = self.span_tdb();
        if !(tdb >= start && tdb < end) {
            return Err(EphemError::OutOfSpan { tdb, start, end });
        }
        let ti = h
            .targets
            .iter()
            .position(|t| t == name)
            .ok_or(EphemError::MissingTarget(name))?;
        let seg = (((tdb - h.start_tdb) / h.segment_s) as usize).min(h.n_segments - 1);
        let x = 2.0 * (tdb - (h.start_tdb + seg as f64 * h.segment_s)) / h.segment_s - 1.0;
        let n = h.degree + 1;
        let base = (seg * h.targets.len() + ti) * 3 * n;
        let mut out = [0.0; 3];
        for (axis, o) in out.iter_mut().enumerate() {
            *o = clenshaw(&self.coeffs[base + axis * n..base + (axis + 1) * n], x);
        }
        Ok(out)
    }

    /// Apparent (LT+S) vector [m] to `body` from an observer at body-fixed position `observer_m`. The
    /// observer's velocity is the Moon centre's; the site's rotational 4.6 m/s is neglected (<= 1.5e-8 rad).
    ///
    /// # Errors
    /// As [`Ephemeris::position`].
    pub fn apparent_from(
        &self,
        body: Body,
        tdb: f64,
        observer_m: [f64; 3],
    ) -> Result<[f64; 3], EphemError> {
        let p = self.position(body, tdb)?;
        let topo = [
            p[0] - observer_m[0],
            p[1] - observer_m[1],
            p[2] - observer_m[2],
        ];
        Ok(stellar_aberration(topo, self.series(MOON_VELOCITY, tdb)?))
    }
}

/// SPICE `stelab`: rotate `p` toward the observer's velocity `v` [m/s] by asin(|u x v/c|).
#[allow(clippy::many_single_char_names)] // the formula's own symbols (u, v, h, k, phi)
fn stellar_aberration(p: [f64; 3], v: [f64; 3]) -> [f64; 3] {
    let norm = |a: [f64; 3]| a[0].hypot(a[1]).hypot(a[2]);
    let cross = |a: [f64; 3], b: [f64; 3]| {
        [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
    };
    let pn = norm(p);
    let u = [p[0] / pn, p[1] / pn, p[2] / pn];
    let vc = [
        v[0] / SPEED_OF_LIGHT_M_S,
        v[1] / SPEED_OF_LIGHT_M_S,
        v[2] / SPEED_OF_LIGHT_M_S,
    ];
    let h = cross(u, vc); // rotating u about u x v by +phi turns it toward v (SPICE stelab/vrotv)
    let sin_phi = norm(h);
    if sin_phi == 0.0 {
        return p;
    }
    let k = [h[0] / sin_phi, h[1] / sin_phi, h[2] / sin_phi];
    let phi = sin_phi.asin();
    let (s, c) = phi.sin_cos();
    let kxp = cross(k, p);
    let kdp = k[0] * p[0] + k[1] * p[1] + k[2] * p[2];
    [0, 1, 2].map(|i| p[i] * c + kxp[i] * s + k[i] * kdp * (1.0 - c))
}

/// Evaluate a Chebyshev series at x in [-1, 1].
fn clenshaw(c: &[f64], x: f64) -> f64 {
    let (mut b1, mut b2) = (0.0, 0.0);
    for &ck in c.iter().skip(1).rev() {
        let b0 = 2.0 * x * b1 - b2 + ck;
        b2 = b1;
        b1 = b0;
    }
    x * b1 - b2 + c[0]
}
