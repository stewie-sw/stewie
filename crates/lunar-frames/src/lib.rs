//! Frames shared by rover and EVA navigation: a body sphere, body-fixed (mean-Earth / mean-rotation axes)
//! vectors, the local east-north-up basis, and polar stereographic projection (EPSG 9810, variant A, on
//! the sphere) — the CRS of the committed LOLA tiles (`IAU_2015:30135`).
//!
//! The radius always comes from the body registry; this crate holds no body constants.

use std::f64::consts::FRAC_PI_4;
use std::fmt;

/// A planetary reference sphere.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Sphere {
    radius_m: f64,
}

/// A frame or projection input that has no answer.
#[derive(Debug, Clone, PartialEq)]
pub enum FrameError {
    InvalidRadius(f64),
    /// The point projects to infinity (the pole opposite the projection origin).
    Unprojectable {
        lat_deg: f64,
    },
}

impl fmt::Display for FrameError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            FrameError::InvalidRadius(r) => {
                write!(f, "sphere radius must be finite and positive, got {r}")
            }
            FrameError::Unprojectable { lat_deg } => {
                write!(
                    f,
                    "latitude {lat_deg} deg is the antipodal pole of the projection"
                )
            }
        }
    }
}

impl std::error::Error for FrameError {}

impl Sphere {
    /// # Errors
    /// [`FrameError::InvalidRadius`] unless the radius is finite and positive.
    pub fn new(radius_m: f64) -> Result<Self, FrameError> {
        if radius_m.is_finite() && radius_m > 0.0 {
            Ok(Self { radius_m })
        } else {
            Err(FrameError::InvalidRadius(radius_m))
        }
    }

    #[must_use]
    pub fn radius_m(self) -> f64 {
        self.radius_m
    }
}

/// Planetocentric latitude and east longitude in degrees.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LatLon {
    pub lat_deg: f64,
    pub lon_deg: f64,
}

/// Body-fixed Cartesian position [m] of a point at height `h_m` above the sphere.
#[must_use]
pub fn body_fixed(sphere: Sphere, ll: LatLon, h_m: f64) -> [f64; 3] {
    let (lat, lon) = (ll.lat_deg.to_radians(), ll.lon_deg.to_radians());
    let r = sphere.radius_m + h_m;
    [
        r * lat.cos() * lon.cos(),
        r * lat.cos() * lon.sin(),
        r * lat.sin(),
    ]
}

/// Local east, north and up unit vectors, expressed in body-fixed axes.
#[must_use]
pub fn enu_basis(ll: LatLon) -> [[f64; 3]; 3] {
    let (lat, lon) = (ll.lat_deg.to_radians(), ll.lon_deg.to_radians());
    let (sl, cl) = lat.sin_cos();
    let (so, co) = lon.sin_cos();
    [
        [-so, co, 0.0],
        [-sl * co, -sl * so, cl],
        [cl * co, cl * so, sl],
    ]
}

/// Polar stereographic projection on a sphere, origin at a pole, scale factor `k0` at the origin.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct PolarStereographic {
    sphere: Sphere,
    south: bool,
    lon0_deg: f64,
    k0: f64,
}

impl PolarStereographic {
    /// South-pole origin, central meridian 0, k0 = 1, no false origin: `IAU_2015:30135` for the Moon.
    #[must_use]
    pub fn south(sphere: Sphere) -> Self {
        Self {
            sphere,
            south: true,
            lon0_deg: 0.0,
            k0: 1.0,
        }
    }

    /// North-pole counterpart (`IAU_2015:30131` for the Moon).
    #[must_use]
    pub fn north(sphere: Sphere) -> Self {
        Self {
            sphere,
            south: false,
            lon0_deg: 0.0,
            k0: 1.0,
        }
    }

    /// (easting, northing) in metres.
    ///
    /// # Errors
    /// [`FrameError::Unprojectable`] for the pole opposite the origin.
    pub fn forward(&self, ll: LatLon) -> Result<(f64, f64), FrameError> {
        let lat = ll.lat_deg.to_radians();
        let dlon = (ll.lon_deg - self.lon0_deg).to_radians();
        let t = if self.south {
            (FRAC_PI_4 + lat / 2.0).tan()
        } else {
            (FRAC_PI_4 - lat / 2.0).tan()
        };
        if !t.is_finite() || t.abs() > 1e12 {
            return Err(FrameError::Unprojectable {
                lat_deg: ll.lat_deg,
            });
        }
        let rho = 2.0 * self.sphere.radius_m * self.k0 * t;
        let (s, c) = dlon.sin_cos();
        Ok(if self.south {
            (rho * s, rho * c)
        } else {
            (rho * s, -rho * c)
        })
    }

    /// Latitude and longitude (longitude in (-180, 180]) of a projected point.
    #[must_use]
    pub fn inverse(&self, easting: f64, northing: f64) -> LatLon {
        let rho = easting.hypot(northing);
        let chi = 2.0 * (rho / (2.0 * self.sphere.radius_m * self.k0)).atan();
        let (lat, lon) = if self.south {
            (chi - std::f64::consts::FRAC_PI_2, easting.atan2(northing))
        } else {
            (std::f64::consts::FRAC_PI_2 - chi, easting.atan2(-northing))
        };
        LatLon {
            lat_deg: lat.to_degrees(),
            lon_deg: wrap_lon(lon.to_degrees() + self.lon0_deg),
        }
    }
}

fn wrap_lon(deg: f64) -> f64 {
    let w = (deg + 180.0).rem_euclid(360.0) - 180.0;
    if w <= -180.0 { w + 360.0 } else { w }
}
