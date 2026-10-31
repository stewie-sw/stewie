//! The STEWIE geometry engine behind one API for the browser (WASM, navigator N14) and native callers.
//!
//! [`Engine`] is plain Rust returning `Result<_, String>`, so native and WASM builds run the same code and
//! the R10 determinism test compares the math itself. The `#[wasm_bindgen]` layer (wasm32 only) wraps it
//! with JSON in and out. Terrain arrives as bytes (a browser fetches it); the body radius comes from the
//! registry JSON, never a literal.

use lunar_dem::{DemTile, GlobalGrid, Resolved, TerrainSource, TerrainStack};
use lunar_ephem::{Body, Ephemeris, Utc, az_el};
use lunar_frames::{LatLon, Sphere, body_fixed};
use lunar_horizon::{Horizon, HorizonConfig, horizon};
use lunar_intervals::{VisibilityConfig, Window, visibility_windows};

/// Terrain stack + ephemeris + body sphere.
#[derive(Debug)]
pub struct Engine {
    stack: TerrainStack,
    eph: Ephemeris,
    moon: Sphere,
}

fn body(name: &str) -> Result<Body, String> {
    match name {
        "SUN" => Ok(Body::Sun),
        "EARTH" => Ok(Body::Earth),
        other => Err(format!("unknown body {other:?} (expected SUN or EARTH)")),
    }
}

impl Engine {
    /// # Errors
    /// A registry without a positive `moon.ellipsoid_radius_m`, or an unloadable ephemeris.
    pub fn new(bodies_json: &str) -> Result<Self, String> {
        let reg: serde_json::Value =
            serde_json::from_str(bodies_json).map_err(|e| e.to_string())?;
        let r = reg["moon"]["ellipsoid_radius_m"]
            .as_f64()
            .ok_or("body registry lacks moon.ellipsoid_radius_m")?;
        Ok(Self {
            stack: TerrainStack::new(Vec::new()),
            eph: Ephemeris::bundled().map_err(|e| e.to_string())?,
            moon: Sphere::new(r).map_err(|e| e.to_string())?,
        })
    }

    /// # Errors
    /// Any `DemTile::from_bundle_bytes` refusal.
    pub fn add_tile(
        &mut self,
        priority: u32,
        id: &str,
        metadata_json: &str,
        heightmap: &[u8],
    ) -> Result<(), String> {
        let t = DemTile::from_bundle_bytes(id, metadata_json, heightmap, self.moon)
            .map_err(|e| e.to_string())?;
        self.stack
            .push(priority, Box::new(t) as Box<dyn TerrainSource>);
        Ok(())
    }

    /// # Errors
    /// Any `GlobalGrid::from_label_bytes` refusal.
    pub fn add_global(
        &mut self,
        priority: u32,
        id: &str,
        label: &str,
        img: &[u8],
    ) -> Result<(), String> {
        let g =
            GlobalGrid::from_label_bytes(id, label, img, self.moon).map_err(|e| e.to_string())?;
        self.stack.push(priority, Box::new(g));
        Ok(())
    }

    /// The terrain stack's signature (see `TerrainStack::signature`).
    #[must_use]
    pub fn stack_signature(&self) -> String {
        self.stack.signature()
    }

    /// # Errors
    /// No terrain under the observer, or an invalid configuration.
    pub fn horizon(
        &self,
        lat: f64,
        lon: f64,
        n_az: usize,
        max_range_m: f64,
        step_m: f64,
        eye_m: f64,
    ) -> Result<Horizon, String> {
        let cfg = HorizonConfig {
            n_az,
            max_range_m,
            step_m,
            eye_height_m: eye_m,
        };
        horizon(
            &self.stack,
            LatLon {
                lat_deg: lat,
                lon_deg: lon,
            },
            &cfg,
        )
        .map_err(|e| e.to_string())
    }

    fn ground(&self, ll: LatLon) -> Result<f64, String> {
        match self.stack.resolve(ll) {
            Resolved::Covered { height_m, .. } => Ok(height_m),
            Resolved::NotCovered => Err("no installed terrain at this point: cannot assess".into()),
        }
    }

    /// Topocentric `[azimuth, elevation]` in degrees of `body` from `height_m` above the terrain at the site.
    ///
    /// # Errors
    /// Unknown body, malformed UTC, an epoch outside the ephemeris, or no terrain at the site.
    pub fn az_el(
        &self,
        body_name: &str,
        utc: &str,
        lat: f64,
        lon: f64,
        height_m: f64,
    ) -> Result<[f64; 2], String> {
        let b = body(body_name)?;
        let ll = LatLon {
            lat_deg: lat,
            lon_deg: lon,
        };
        let tdb = self
            .eph
            .tdb(&Utc::parse_iso8601(utc).map_err(|e| e.to_string())?);
        let obs = body_fixed(self.moon, ll, self.ground(ll)? + height_m);
        let v = self
            .eph
            .apparent_from(b, tdb, obs)
            .map_err(|e| e.to_string())?;
        let ae = az_el(v, ll);
        Ok([ae.az_deg, ae.el_deg])
    }

    /// Lit / shadow / unknown windows of `body` over `horizon` between two UTC instants.
    ///
    /// # Errors
    /// As [`Engine::az_el`], plus an invalid sampling configuration.
    #[allow(clippy::too_many_arguments)] // a flat signature mirrors the JS binding
    pub fn windows(
        &self,
        body_name: &str,
        lat: f64,
        lon: f64,
        start_utc: &str,
        end_utc: &str,
        sample_s: f64,
        eye_m: f64,
        horizon: &Horizon,
    ) -> Result<Vec<Window>, String> {
        let b = body(body_name)?;
        let ll = LatLon {
            lat_deg: lat,
            lon_deg: lon,
        };
        let t = |s: &str| {
            Utc::parse_iso8601(s)
                .map(|u| self.eph.tdb(&u))
                .map_err(|e| e.to_string())
        };
        let cfg = VisibilityConfig {
            sample_s,
            tolerance_s: 0.1,
            eye_height_m: eye_m,
            ground_height_m: self.ground(ll)?,
            moon: self.moon,
        };
        visibility_windows(&self.eph, horizon, ll, b, t(start_utc)?, t(end_utc)?, &cfg)
            .map_err(|e| e.to_string())
    }
}

/// The R10 determinism scenario: real Haworth tile over LOLA `LDEM_16`.
pub mod scenario {
    use serde::Serialize;

    use super::Engine;

    const SITE: (f64, f64) = (-86.318_398_660_548_35, -25.414_052_740_154_946);

    /// Raw inputs: the body registry, the Haworth bundle and `LDEM_16`.
    #[derive(Debug)]
    pub struct Inputs {
        bodies: String,
        tile_meta: String,
        tile_heights: Vec<u8>,
        ldem_label: String,
        ldem_img: Vec<u8>,
    }

    impl Inputs {
        /// Read the inputs from the repository (native).
        ///
        /// # Errors
        /// Any missing file (fetch `LDEM_16` with `pipeline/fetch.py`).
        #[cfg(not(target_arch = "wasm32"))]
        pub fn from_repo() -> Result<Self, String> {
            let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
            let text =
                |p: &str| std::fs::read_to_string(root.join(p)).map_err(|e| format!("{p}: {e}"));
            let bytes = |p: &str| std::fs::read(root.join(p)).map_err(|e| format!("{p}: {e}"));
            Ok(Self {
                bodies: text("crates/stewie-contracts/fixtures/bodies.json")?,
                tile_meta: text("samples/lunar_dem/haworth_10km_5m/metadata.json")?,
                tile_heights: bytes("samples/lunar_dem/haworth_10km_5m/heightmap.rf32")?,
                ldem_label: text(".cache/terrain/ldem_16.lbl")?,
                ldem_img: bytes(".cache/terrain/ldem_16.img")?,
            })
        }

        /// The same files compiled into the WASM test binary.
        #[cfg(target_arch = "wasm32")]
        #[must_use]
        pub fn embedded() -> Self {
            Self {
                bodies: include_str!("../../stewie-contracts/fixtures/bodies.json").to_owned(),
                tile_meta: include_str!("../../../samples/lunar_dem/haworth_10km_5m/metadata.json")
                    .to_owned(),
                tile_heights: include_bytes!(
                    "../../../samples/lunar_dem/haworth_10km_5m/heightmap.rf32"
                )
                .to_vec(),
                ldem_label: include_str!("../../../.cache/terrain/ldem_16.lbl").to_owned(),
                ldem_img: include_bytes!("../../../.cache/terrain/ldem_16.img").to_vec(),
            }
        }

        /// # Errors
        /// Any engine or terrain refusal.
        pub fn engine(&self) -> Result<Engine, String> {
            let mut e = Engine::new(&self.bodies)?;
            e.add_tile(1, "haworth_10km_5m", &self.tile_meta, &self.tile_heights)?;
            e.add_global(9, "ldem_16", &self.ldem_label, &self.ldem_img)?;
            Ok(e)
        }
    }

    #[derive(Debug, Serialize)]
    pub struct WindowOut {
        pub start_utc_offset_s: f64,
        pub end_utc_offset_s: f64,
        pub verdict: String,
    }

    #[derive(Debug, Serialize)]
    pub struct Output {
        pub horizon_elev_deg: Vec<Option<f64>>,
        pub horizon_reach_m: Vec<f64>,
        pub sun_az_el: Vec<[f64; 2]>,
        pub earth_az_el: Vec<[f64; 2]>,
        pub sun_windows: Vec<WindowOut>,
    }

    /// # Errors
    /// Any engine refusal.
    pub fn run(inputs: &Inputs) -> Result<Output, String> {
        let e = inputs.engine()?;
        let (lat, lon) = SITE;
        let h = e.horizon(lat, lon, 720, 200_000.0, 50.0, 1.5)?;
        let hours: Vec<String> = (0..24)
            .map(|i| format!("2027-01-01T{i:02}:00:00Z"))
            .collect();
        let track = |b: &str| {
            hours
                .iter()
                .map(|t| e.az_el(b, t, lat, lon, 1.5))
                .collect::<Result<Vec<_>, _>>()
        };
        let w = e.windows(
            "SUN",
            lat,
            lon,
            "2027-01-01T00:00:00Z",
            "2027-01-31T00:00:00Z",
            600.0,
            1.5,
            &h,
        )?;
        let t0 = w.first().map_or(0.0, |x| x.start_tdb);
        Ok(Output {
            sun_az_el: track("SUN")?,
            earth_az_el: track("EARTH")?,
            sun_windows: w
                .iter()
                .map(|x| WindowOut {
                    start_utc_offset_s: x.start_tdb - t0,
                    end_utc_offset_s: x.end_tdb - t0,
                    verdict: format!("{:?}", x.verdict),
                })
                .collect(),
            horizon_elev_deg: h.elev_deg,
            horizon_reach_m: h.reach_m,
        })
    }

    /// Largest absolute numeric difference between two JSON documents of the same shape; infinity when the
    /// shapes or any non-numeric values differ.
    #[must_use]
    pub fn max_abs_diff(a: &serde_json::Value, b: &serde_json::Value) -> f64 {
        use serde_json::Value as V;
        match (a, b) {
            (V::Number(x), V::Number(y)) => match (x.as_f64(), y.as_f64()) {
                (Some(x), Some(y)) => (x - y).abs(),
                _ => f64::INFINITY,
            },
            (V::Array(x), V::Array(y)) if x.len() == y.len() => x
                .iter()
                .zip(y)
                .map(|(p, q)| max_abs_diff(p, q))
                .fold(0.0, f64::max),
            (V::Object(x), V::Object(y)) if x.len() == y.len() => x
                .iter()
                .map(|(k, v)| y.get(k).map_or(f64::INFINITY, |w| max_abs_diff(v, w)))
                .fold(0.0, f64::max),
            _ if a == b => 0.0,
            _ => f64::INFINITY,
        }
    }
}

/// JSON-in/JSON-out bindings for the browser worker.
#[cfg(target_arch = "wasm32")]
mod bindings {
    use wasm_bindgen::prelude::*;

    #[wasm_bindgen(js_name = Engine)]
    #[derive(Debug)]
    pub struct JsEngine(super::Engine);

    #[wasm_bindgen(js_class = Engine)]
    impl JsEngine {
        #[wasm_bindgen(constructor)]
        pub fn new(bodies_json: &str) -> Result<JsEngine, JsError> {
            super::Engine::new(bodies_json)
                .map(JsEngine)
                .map_err(|e| JsError::new(&e))
        }

        #[wasm_bindgen(js_name = addTile)]
        pub fn add_tile(
            &mut self,
            priority: u32,
            id: &str,
            metadata_json: &str,
            heightmap: &[u8],
        ) -> Result<(), JsError> {
            self.0
                .add_tile(priority, id, metadata_json, heightmap)
                .map_err(|e| JsError::new(&e))
        }

        #[wasm_bindgen(js_name = addGlobal)]
        pub fn add_global(
            &mut self,
            priority: u32,
            id: &str,
            label: &str,
            img: &[u8],
        ) -> Result<(), JsError> {
            self.0
                .add_global(priority, id, label, img)
                .map_err(|e| JsError::new(&e))
        }

        /// Horizon as JSON `{az_deg, elev_deg, reach_m, complete, sources}`.
        pub fn horizon(
            &self,
            lat: f64,
            lon: f64,
            n_az: usize,
            max_range_m: f64,
            step_m: f64,
            eye_m: f64,
        ) -> Result<String, JsError> {
            let h = self
                .0
                .horizon(lat, lon, n_az, max_range_m, step_m, eye_m)
                .map_err(|e| JsError::new(&e))?;
            Ok(serde_json::json!({"az_deg": h.az_deg, "elev_deg": h.elev_deg, "reach_m": h.reach_m, "complete": h.complete, "sources": h.sources}).to_string())
        }

        #[wasm_bindgen(js_name = azEl)]
        pub fn az_el(
            &self,
            body: &str,
            utc: &str,
            lat: f64,
            lon: f64,
            height_m: f64,
        ) -> Result<Vec<f64>, JsError> {
            self.0
                .az_el(body, utc, lat, lon, height_m)
                .map(|v| v.to_vec())
                .map_err(|e| JsError::new(&e))
        }
    }
}
