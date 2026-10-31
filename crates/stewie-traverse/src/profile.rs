//! Per-segment route profile (navigator N23, DAG RW-31): along a route's waypoints, each segment's
//! length, rise and signed slope from the DEM, its travel time from the agent's speed model, and at
//! every node the arrival time, where the Sun and the Earth stand (apparent azimuth and elevation from the
//! ephemeris) and whether each is visible over that node's terrain horizon (Lit, Shadow or Unknown). The speed model belongs to the agent profile (the rover's sourced drive speed; the EVA
//! walking model is blocked on sourced data, D-R35). A non-positive or non-finite speed makes the whole
//! profile unassessable, never a guess.

use lunar_dem::TerrainStack;
use lunar_ephem::{AzEl, Body, Ephemeris, az_el};
use lunar_frames::{LatLon, Sphere, body_fixed};
use lunar_horizon::{HorizonConfig, horizon};
use lunar_intervals::{Verdict, verdict_at};

use crate::route::Dem;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Segment {
    pub from: (f64, f64),
    pub to: (f64, f64),
    pub length_m: f64,
    /// Height gained along the segment [m] (negative downhill).
    pub rise_m: f64,
    /// Along-track slope [deg], `atan(rise / horizontal length)`; positive uphill.
    pub slope_deg: f64,
    pub t_start_s: f64,
    pub t_end_s: f64,
}

/// Where the Sun and the Earth stand at a node when the agent arrives, and whether each clears the node's
/// terrain horizon.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct NodeSky {
    pub site: LatLon,
    pub tdb: f64,
    pub sun: AzEl,
    pub earth: AzEl,
    pub sun_verdict: Verdict,
    pub earth_verdict: Verdict,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Profile {
    pub segments: Vec<Segment>,
    pub total_m: f64,
    pub total_s: f64,
    /// One per waypoint, when a sky frame was given.
    pub sky: Vec<NodeSky>,
}

/// Where the route sits on the Moon: grid `(row, col)` to selenographic position, the body sphere, the
/// ephemeris, the departure epoch (TDB seconds), and the terrain each node's horizon is cast over (its eye
/// height is the frame's).
pub struct SkyFrame<'a> {
    pub to_latlon: &'a dyn Fn(f64, f64) -> LatLon,
    pub moon: Sphere,
    pub ephemeris: &'a Ephemeris,
    pub depart_tdb: f64,
    pub eye_height_m: f64,
    pub terrain: &'a TerrainStack,
    pub horizon: HorizonConfig,
}

impl std::fmt::Debug for SkyFrame<'_> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SkyFrame")
            .field("depart_tdb", &self.depart_tdb)
            .finish_non_exhaustive()
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum ProfileError {
    /// The speed model gave no usable speed for a segment: the profile cannot be assessed.
    NoSpeed { segment: usize, slope_deg: f64 },
    /// A waypoint lies off the DEM.
    OffDem((f64, f64)),
    /// A node's time is outside the ephemeris span.
    Ephemeris(String),
    /// A node's horizon could not be cast (no terrain under it, or a bad horizon configuration).
    Horizon(String),
}

/// Bilinear DEM height at a local point (grid nodes sit at `col * cell`, `row * cell` in DEM metres).
#[allow(clippy::cast_precision_loss)]
fn height_at(dem: &Dem<'_>, (x, y): (f64, f64)) -> Option<f64> {
    let (col, row) = (
        (x + dem.origin.0) / dem.cell_m,
        (y + dem.origin.1) / dem.cell_m,
    );
    let ok =
        row >= 0.0 && col >= 0.0 && row <= (dem.height - 1) as f64 && col <= (dem.width - 1) as f64;
    ok.then(|| crate::bilinear(dem.z, dem.width, dem.height, row, col))
}

/// Profile `waypoints` (local metres) on `dem`, timing each segment with `speed_ms(slope_deg)`.
///
/// # Errors
/// [`ProfileError::OffDem`], [`ProfileError::NoSpeed`], or an epoch outside the ephemeris.
#[allow(clippy::cast_precision_loss)]
pub fn profile(
    dem: Dem<'_>,
    waypoints: &[(f64, f64)],
    speed_ms: &dyn Fn(f64) -> f64,
    sky: Option<&SkyFrame<'_>>,
) -> Result<Profile, ProfileError> {
    let heights: Vec<f64> = waypoints
        .iter()
        .map(|&p| height_at(&dem, p).ok_or(ProfileError::OffDem(p)))
        .collect::<Result<_, _>>()?;
    let (mut t, mut total_m, mut segments) = (0.0, 0.0, Vec::new());
    let mut arrive = vec![0.0];
    for (i, w) in waypoints.windows(2).enumerate() {
        let run = (w[1].0 - w[0].0).hypot(w[1].1 - w[0].1);
        let rise = heights[i + 1] - heights[i];
        let length_m = run.hypot(rise);
        let slope_deg = rise.atan2(run).to_degrees();
        let v = speed_ms(slope_deg);
        if !(v.is_finite() && v > 0.0) {
            return Err(ProfileError::NoSpeed {
                segment: i,
                slope_deg,
            });
        }
        let dt = length_m / v;
        segments.push(Segment {
            from: w[0],
            to: w[1],
            length_m,
            rise_m: rise,
            slope_deg,
            t_start_s: t,
            t_end_s: t + dt,
        });
        t += dt;
        total_m += length_m;
        arrive.push(t);
    }
    let mut nodes = Vec::new();
    if let Some(f) = sky {
        let hcfg = HorizonConfig {
            eye_height_m: f.eye_height_m,
            ..f.horizon.clone()
        };
        for (k, &(x, y)) in waypoints.iter().enumerate() {
            let site = (f.to_latlon)(
                (y + dem.origin.1) / dem.cell_m,
                (x + dem.origin.0) / dem.cell_m,
            );
            let pos = body_fixed(f.moon, site, heights[k] + f.eye_height_m);
            let tdb = f.depart_tdb + arrive[k];
            let dir = |b| {
                f.ephemeris
                    .apparent_from(b, tdb, pos)
                    .map(|v| az_el(v, site))
                    .map_err(|e| ProfileError::Ephemeris(e.to_string()))
            };
            let h = horizon(f.terrain, site, &hcfg)
                .map_err(|e| ProfileError::Horizon(e.to_string()))?;
            let seen = |b| {
                verdict_at(f.ephemeris, &h, site, pos, b, tdb)
                    .map_err(|e| ProfileError::Ephemeris(e.to_string()))
            };
            nodes.push(NodeSky {
                site,
                tdb,
                sun: dir(Body::Sun)?,
                earth: dir(Body::Earth)?,
                sun_verdict: seen(Body::Sun)?,
                earth_verdict: seen(Body::Earth)?,
            });
        }
    }
    Ok(Profile {
        segments,
        total_m,
        total_s: t,
        sky: nodes,
    })
}
