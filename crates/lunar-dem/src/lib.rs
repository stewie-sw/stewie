//! Real STEWIE DEM bundles (`samples/lunar_dem/<name>/`: `metadata.json` + `heightmap.rf32`).
//!
//! A tile opens only if its metadata satisfies the `stewie-contracts` schema, its recorded sphere is the
//! registry body's sphere (a different datum shifts every horizon), and the heightmap holds exactly
//! `width * height` little-endian f32 values. Sampling never extrapolates: outside the tile there is no
//! answer, and a [`TerrainStack`] says which source answered.

use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use lunar_frames::{LatLon, PolarStereographic, Sphere};
use stewie_contracts::dem_bundle::{self, DemBundle};

/// The only frame curated bundles use (Python `site_dem.bundle_crs` default).
const SUPPORTED_FRAME: &str = "IAU_2015:30135";

#[derive(Debug)]
pub enum DemError {
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    Contract {
        path: PathBuf,
        message: String,
    },
    DatumMismatch {
        bundle: String,
        bundle_radius_m: f64,
        body_radius_m: f64,
    },
    UnsupportedFrame {
        bundle: String,
        frame: String,
    },
    SizeMismatch {
        bundle: String,
        expected_bytes: usize,
        actual_bytes: usize,
    },
}

impl fmt::Display for DemError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            DemError::Io { path, source } => write!(f, "{}: {source}", path.display()),
            DemError::Contract { path, message } => write!(f, "{}: {message}", path.display()),
            DemError::DatumMismatch {
                bundle,
                bundle_radius_m,
                body_radius_m,
            } => {
                write!(
                    f,
                    "{bundle}: sphere {bundle_radius_m} m is not the body sphere {body_radius_m} m"
                )
            }
            DemError::UnsupportedFrame { bundle, frame } => {
                write!(f, "{bundle}: frame {frame:?} is not {SUPPORTED_FRAME}")
            }
            DemError::SizeMismatch {
                bundle,
                expected_bytes,
                actual_bytes,
            } => {
                write!(
                    f,
                    "{bundle}: heightmap has {actual_bytes} bytes, grid needs {expected_bytes}"
                )
            }
        }
    }
}

impl std::error::Error for DemError {}

/// One georeferenced height grid (north-up, row-major, pixel (0,0) centred at (x0 + cell/2, y1 - cell/2)).
#[derive(Debug)]
pub struct DemTile {
    id: String,
    citation: String,
    z: Vec<f32>,
    width: usize,
    height: usize,
    cell_m: f64,
    bounds: [f64; 4],
    sphere: Sphere,
    proj: PolarStereographic,
}

fn io(path: &Path) -> impl FnOnce(std::io::Error) -> DemError + '_ {
    move |source| DemError::Io {
        path: path.to_path_buf(),
        source,
    }
}

fn contract(path: &Path, message: impl fmt::Display) -> DemError {
    DemError::Contract {
        path: path.to_path_buf(),
        message: message.to_string(),
    }
}

impl DemTile {
    /// Open a bundle directory on `sphere`.
    ///
    /// # Errors
    /// I/O failure, contract violation, datum or frame mismatch, or a heightmap of the wrong size.
    pub fn open(dir: &Path, sphere: Sphere) -> Result<Self, DemError> {
        let id = dir
            .file_name()
            .map_or_else(String::new, |n| n.to_string_lossy().into_owned());
        let meta_path = dir.join("metadata.json");
        let text = fs::read_to_string(&meta_path).map_err(io(&meta_path))?;
        let file: serde_json::Value =
            serde_json::from_str(&text).map_err(|e| contract(&meta_path, e))?;
        let hm_name = file["fields"]["heightmap"]["file"]
            .as_str()
            .ok_or_else(|| contract(&meta_path, "fields.heightmap.file is required"))?;
        let hm_path = dir.join(hm_name);
        let bytes = fs::read(&hm_path).map_err(io(&hm_path))?;
        Self::from_bundle_bytes(&id, &text, &bytes, sphere)
    }

    /// A tile from a bundle's `metadata.json` text and heightmap bytes (how a browser loads it).
    ///
    /// # Errors
    /// As [`DemTile::open`], without the I/O.
    pub fn from_bundle_bytes(
        id: &str,
        metadata_json: &str,
        heightmap: &[u8],
        sphere: Sphere,
    ) -> Result<Self, DemError> {
        let meta_path = PathBuf::from(format!("{id}/metadata.json"));
        let id = id.to_owned();
        let text = metadata_json;
        let meta: DemBundle = serde_json::from_str(text).map_err(|e| contract(&meta_path, e))?;
        dem_bundle::check(&meta).map_err(|e| contract(&meta_path, e))?;
        let prov = meta
            .dem_provenance
            .as_ref()
            .ok_or_else(|| contract(&meta_path, "dem_provenance is required to place the tile"))?;
        if !prov.frame.contains(SUPPORTED_FRAME) {
            return Err(DemError::UnsupportedFrame {
                bundle: id,
                frame: prov.frame.clone(),
            });
        }
        let r = prov
            .sphere_radius_m
            .ok_or_else(|| contract(&meta_path, "dem_provenance.sphere_radius_m is required"))?;
        if (r - sphere.radius_m()).abs() > 1e-6 {
            return Err(DemError::DatumMismatch {
                bundle: id,
                bundle_radius_m: r,
                body_radius_m: sphere.radius_m(),
            });
        }
        let hm = &meta.fields.heightmap;
        if hm.dtype.to_string() != "<f4" {
            return Err(contract(
                &meta_path,
                format!("heightmap dtype {} is not <f4", hm.dtype),
            ));
        }
        let width = usize::try_from(meta.grid.width.get()).map_err(|e| contract(&meta_path, e))?;
        let height =
            usize::try_from(meta.grid.height.get()).map_err(|e| contract(&meta_path, e))?;
        if width < 2 || height < 2 {
            return Err(contract(&meta_path, "grid must be at least 2 x 2"));
        }
        let bytes = heightmap;
        let expected = width * height * 4;
        if bytes.len() != expected {
            return Err(DemError::SizeMismatch {
                bundle: id,
                expected_bytes: expected,
                actual_bytes: bytes.len(),
            });
        }
        let z = bytes
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
            .collect();
        let w = &meta.world_bounds_m;
        Ok(Self {
            id,
            citation: prov.citation.clone(),
            z,
            width,
            height,
            cell_m: meta.grid.cell_m,
            bounds: [w.x0, w.y0, w.x1, w.y1],
            sphere,
            proj: PolarStereographic::south(sphere),
        })
    }

    /// A tile from an in-memory grid (row-major, north-up) in the south polar stereographic frame of
    /// `sphere`, e.g. one decoded by the data pipeline. `bounds` is `[x0, y0, x1, y1]` in metres.
    ///
    /// # Errors
    /// [`DemError::Contract`] when the grid, cell size and bounds disagree or the grid is smaller than 2 x 2.
    #[allow(clippy::cast_precision_loss)] // grid dimensions are far below 2^52
    pub fn from_grid(
        id: &str,
        z: Vec<f32>,
        width: usize,
        height: usize,
        cell_m: f64,
        bounds: [f64; 4],
        sphere: Sphere,
    ) -> Result<Self, DemError> {
        let here = PathBuf::from(id);
        if width < 2
            || height < 2
            || z.len() != width * height
            || !(cell_m.is_finite() && cell_m > 0.0)
        {
            return Err(contract(
                &here,
                format!(
                    "grid {width}x{height} with {} values at {cell_m} m",
                    z.len()
                ),
            ));
        }
        let [x0, y0, x1, y1] = bounds;
        let tol = cell_m * 1e-6;
        if (width as f64 * cell_m - (x1 - x0)).abs() > tol
            || (height as f64 * cell_m - (y1 - y0)).abs() > tol
        {
            return Err(contract(&here, "bounds do not span the grid"));
        }
        Ok(Self {
            id: id.to_owned(),
            citation: format!("in-memory grid {id}"),
            z,
            width,
            height,
            cell_m,
            bounds,
            sphere,
            proj: PolarStereographic::south(sphere),
        })
    }

    #[must_use]
    pub fn sphere(&self) -> Sphere {
        self.sphere
    }

    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }
    #[must_use]
    pub fn citation(&self) -> &str {
        &self.citation
    }
    #[must_use]
    pub fn width(&self) -> usize {
        self.width
    }
    #[must_use]
    pub fn height(&self) -> usize {
        self.height
    }
    #[must_use]
    pub fn cell_m(&self) -> f64 {
        self.cell_m
    }

    /// Height [m] of a cell, or `None` outside the grid.
    #[must_use]
    pub fn height_at(&self, row: usize, col: usize) -> Option<f64> {
        (row < self.height && col < self.width).then(|| f64::from(self.z[row * self.width + col]))
    }

    /// Surface slope [deg] with numpy `gradient` semantics: central differences inside, first-order
    /// one-sided differences on the border.
    #[must_use]
    pub fn slope_deg_at(&self, row: usize, col: usize) -> Option<f64> {
        if row >= self.height || col >= self.width {
            return None;
        }
        Some(slope_deg_at(
            |r, c| f64::from(self.z[r * self.width + c]),
            self.width,
            self.height,
            self.cell_m,
            row,
            col,
        ))
    }

    /// Projected (easting, northing) [m] of a cell centre.
    #[must_use]
    #[allow(clippy::cast_precision_loss)] // grid indices are far below 2^52
    pub fn cell_center_projected(&self, row: usize, col: usize) -> (f64, f64) {
        let [x0, _, _, y1] = self.bounds;
        (
            x0 + self.cell_m * (col as f64 + 0.5),
            y1 - self.cell_m * (row as f64 + 0.5),
        )
    }

    #[must_use]
    pub fn cell_center_latlon(&self, row: usize, col: usize) -> LatLon {
        let (e, n) = self.cell_center_projected(row, col);
        self.proj.inverse(e, n)
    }

    /// Bilinear height between cell centres; `None` outside the hull of cell centres.
    #[must_use]
    #[allow(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss
    )]
    pub fn sample_projected(&self, easting: f64, northing: f64) -> Option<f64> {
        let [x0, _, _, y1] = self.bounds;
        let fx = (easting - (x0 + self.cell_m / 2.0)) / self.cell_m;
        let fy = ((y1 - self.cell_m / 2.0) - northing) / self.cell_m;
        let (wmax, hmax) = ((self.width - 1) as f64, (self.height - 1) as f64);
        if !(fx >= 0.0 && fy >= 0.0 && fx <= wmax && fy <= hmax) {
            return None;
        }
        let c0 = (fx.floor() as usize).min(self.width - 2);
        let r0 = (fy.floor() as usize).min(self.height - 2);
        let (tx, ty) = (fx - c0 as f64, fy - r0 as f64);
        let h = |r: usize, c: usize| f64::from(self.z[r * self.width + c]);
        Some(
            (1.0 - ty) * ((1.0 - tx) * h(r0, c0) + tx * h(r0, c0 + 1))
                + ty * ((1.0 - tx) * h(r0 + 1, c0) + tx * h(r0 + 1, c0 + 1)),
        )
    }

    #[must_use]
    pub fn sample_latlon(&self, ll: LatLon) -> Option<f64> {
        let (e, n) = self.proj.forward(ll).ok()?;
        self.sample_projected(e, n)
    }
}

/// Surface slope [deg] at `(row, col)` of a `width` x `height` grid read through `z`: numpy
/// `np.gradient` (central differences inside, one-sided on the border), then `atan(|grad|)`. Grids need
/// at least two cells per axis.
pub fn slope_deg_at(
    z: impl Fn(usize, usize) -> f64,
    width: usize,
    height: usize,
    cell_m: f64,
    row: usize,
    col: usize,
) -> f64 {
    let d = |lo: f64, hi: f64, span: f64| (hi - lo) / span;
    let gx = if col == 0 {
        d(z(row, 0), z(row, 1), cell_m)
    } else if col == width - 1 {
        d(z(row, col - 1), z(row, col), cell_m)
    } else {
        d(z(row, col - 1), z(row, col + 1), 2.0 * cell_m)
    };
    let gy = if row == 0 {
        d(z(0, col), z(1, col), cell_m)
    } else if row == height - 1 {
        d(z(row - 1, col), z(row, col), cell_m)
    } else {
        d(z(row - 1, col), z(row + 1, col), 2.0 * cell_m)
    };
    gx.hypot(gy).atan().to_degrees()
}

/// [`slope_deg_at`] over every cell of a row-major `z` (Python `site_dem.slope_deg_map`).
#[must_use]
pub fn slope_deg_grid(z: &[f64], width: usize, height: usize, cell_m: f64) -> Vec<f64> {
    (0..z.len())
        .map(|i| {
            slope_deg_at(
                |r, c| z[r * width + c],
                width,
                height,
                cell_m,
                i / width,
                i % width,
            )
        })
        .collect()
}

/// Anything that answers "terrain height here?" in the body's frame: a local tile, a global grid.
pub trait TerrainSource: fmt::Debug + Send + Sync {
    fn id(&self) -> &str;
    fn citation(&self) -> &str;
    /// Nominal ground sample distance [m].
    fn resolution_m(&self) -> f64;
    fn sphere(&self) -> Sphere;
    /// Height [m above the sphere], or `None` where the source has no answer (never extrapolated).
    fn sample_latlon(&self, ll: LatLon) -> Option<f64>;
    /// True for a whole-body base tier (its identity and version define the stack), false for a regional tile.
    fn is_global(&self) -> bool {
        false
    }
}

impl TerrainSource for DemTile {
    fn id(&self) -> &str {
        &self.id
    }
    fn citation(&self) -> &str {
        &self.citation
    }
    fn resolution_m(&self) -> f64 {
        self.cell_m
    }
    fn sphere(&self) -> Sphere {
        self.sphere
    }
    fn sample_latlon(&self, ll: LatLon) -> Option<f64> {
        DemTile::sample_latlon(self, ll)
    }
}

/// A PDS simple-cylindrical global DEM (LOLA LDEM): 16-bit LSB heights scaled by the label, read whole.
#[derive(Debug)]
pub struct GlobalGrid {
    id: String,
    citation: String,
    dn: Vec<i16>,
    lines: usize,
    samples: usize,
    scale: f64,
    res_ppd: f64,
    line_offset: f64,
    sample_offset: f64,
    center_lon: f64,
    west_lon: f64,
    sphere: Sphere,
}

/// `KEY = value` pairs of a PDS3 label, comments, quotes and `<units>` stripped.
fn pds_label(text: &str) -> std::collections::BTreeMap<String, String> {
    text.lines()
        .filter_map(|line| {
            let line = line.split("/*").next().unwrap_or("").trim();
            let (k, v) = line.split_once('=')?;
            let v = v.split('<').next().unwrap_or("").trim().trim_matches('"');
            Some((k.trim().to_owned(), v.to_owned()))
        })
        .collect()
}

impl GlobalGrid {
    /// Open an LDEM image and its label on `sphere`.
    ///
    /// # Errors
    /// I/O failure, a label that is not 16-bit LSB simple cylindrical, an OFFSET that is not the body
    /// sphere, or an image whose size disagrees with the label.
    pub fn open(img: &Path, lbl: &Path, sphere: Sphere) -> Result<Self, DemError> {
        let text = fs::read_to_string(lbl).map_err(io(lbl))?;
        let bytes = fs::read(img).map_err(io(img))?;
        let id = img
            .file_stem()
            .map_or_else(String::new, |n| n.to_string_lossy().into_owned());
        Self::from_label_bytes(&id, &text, &bytes, sphere)
    }

    /// A grid from its PDS3 label text and image bytes (how a browser loads it).
    ///
    /// # Errors
    /// As [`GlobalGrid::open`], without the I/O.
    pub fn from_label_bytes(
        id: &str,
        label: &str,
        bytes: &[u8],
        sphere: Sphere,
    ) -> Result<Self, DemError> {
        let r = PdsRaster::parse(id, label, bytes, sphere, "SIMPLE CYLINDRICAL")?;
        Ok(Self {
            res_ppd: r.num("MAP_RESOLUTION")?,
            line_offset: r.num("LINE_PROJECTION_OFFSET")?,
            sample_offset: r.num("SAMPLE_PROJECTION_OFFSET")?,
            center_lon: r.num("CENTER_LONGITUDE")?,
            west_lon: r.num("WESTERNMOST_LONGITUDE")?,
            scale: r.num("SCALING_FACTOR")?,
            citation: r.citation(),
            id: r.id,
            dn: r.dn,
            lines: r.lines,
            samples: r.samples,
            sphere,
        })
    }
}

/// A 16-bit LSB LOLA PDS3 height raster: its label keys and DNs, with the datum and size checked.
struct PdsRaster {
    id: String,
    lbl: PathBuf,
    lab: std::collections::BTreeMap<String, String>,
    dn: Vec<i16>,
    lines: usize,
    samples: usize,
}

impl PdsRaster {
    fn parse(
        id: &str,
        label: &str,
        bytes: &[u8],
        sphere: Sphere,
        projection: &str,
    ) -> Result<Self, DemError> {
        let mut r = Self {
            id: id.to_owned(),
            lbl: PathBuf::from(format!("{id}.lbl")),
            lab: pds_label(label),
            dn: Vec::new(),
            lines: 0,
            samples: 0,
        };
        if r.get("SAMPLE_TYPE")? != "LSB_INTEGER"
            || r.get("SAMPLE_BITS")? != "16"
            || r.get("MAP_PROJECTION_TYPE")? != projection
        {
            return Err(contract(
                &r.lbl,
                format!("only 16-bit LSB {projection} LDEMs are supported"),
            ));
        }
        let offset = r.num("OFFSET")?;
        if (offset - sphere.radius_m()).abs() > 1e-6 {
            return Err(DemError::DatumMismatch {
                bundle: r.id,
                bundle_radius_m: offset,
                body_radius_m: sphere.radius_m(),
            });
        }
        (r.lines, r.samples) = (r.int("LINES")?, r.int("LINE_SAMPLES")?);
        if bytes.len() != r.lines * r.samples * 2 {
            return Err(DemError::SizeMismatch {
                bundle: r.id,
                expected_bytes: r.lines * r.samples * 2,
                actual_bytes: bytes.len(),
            });
        }
        r.dn = bytes
            .chunks_exact(2)
            .map(|b| i16::from_le_bytes([b[0], b[1]]))
            .collect();
        Ok(r)
    }

    fn get(&self, k: &str) -> Result<&String, DemError> {
        self.lab
            .get(k)
            .ok_or_else(|| contract(&self.lbl, format!("label lacks {k}")))
    }

    fn num(&self, k: &str) -> Result<f64, DemError> {
        self.get(k)?
            .parse::<f64>()
            .map_err(|e| contract(&self.lbl, format!("{k}: {e}")))
    }

    fn int(&self, k: &str) -> Result<usize, DemError> {
        self.get(k)?
            .parse::<usize>()
            .map_err(|e| contract(&self.lbl, format!("{k}: {e}")))
    }

    fn citation(&self) -> String {
        format!(
            "LRO LOLA {} ({}), PDS Geosciences Node",
            self.get("PRODUCT_ID")
                .map_or(self.id.as_str(), String::as_str),
            self.get("PRODUCT_VERSION_ID").map_or("", String::as_str)
        )
    }
}

/// A PDS polar-stereographic LOLA LDEM (e.g. `LDEM_85S_40M`): a regional tier around one pole, read whole.
/// Pixel centre (line l, sample s), 0-based, sits at easting `(s - SAMPLE_PROJECTION_OFFSET) * MAP_SCALE`,
/// northing `(LINE_PROJECTION_OFFSET - l) * MAP_SCALE` (GDAL's reading of the same label agrees).
#[derive(Debug)]
pub struct PolarGrid {
    id: String,
    citation: String,
    dn: Vec<i16>,
    lines: usize,
    samples: usize,
    scale: f64,
    cell_m: f64,
    line_offset: f64,
    sample_offset: f64,
    proj: PolarStereographic,
    sphere: Sphere,
}

impl PolarGrid {
    /// Open a polar LDEM image and its label on `sphere`.
    ///
    /// # Errors
    /// I/O failure, a label that is not a 16-bit LSB polar stereographic about a pole with central meridian 0
    /// on the body sphere, or an image whose size disagrees with the label.
    pub fn open(img: &Path, lbl: &Path, sphere: Sphere) -> Result<Self, DemError> {
        let text = fs::read_to_string(lbl).map_err(io(lbl))?;
        let bytes = fs::read(img).map_err(io(img))?;
        let id = img
            .file_stem()
            .map_or_else(String::new, |n| n.to_string_lossy().into_owned());
        Self::from_label_bytes(&id, &text, &bytes, sphere)
    }

    /// A grid from its PDS3 label text and image bytes.
    ///
    /// # Errors
    /// As [`PolarGrid::open`], without the I/O.
    pub fn from_label_bytes(
        id: &str,
        label: &str,
        bytes: &[u8],
        sphere: Sphere,
    ) -> Result<Self, DemError> {
        let r = PdsRaster::parse(id, label, bytes, sphere, "POLAR STEREOGRAPHIC")?;
        let a_m = r.num("A_AXIS_RADIUS")? * 1000.0;
        let (lat_c, lon_c) = (r.num("CENTER_LATITUDE")?, r.num("CENTER_LONGITUDE")?);
        let proj = match lat_c {
            -90.0 => PolarStereographic::south(sphere),
            90.0 => PolarStereographic::north(sphere),
            _ => {
                return Err(contract(
                    &r.lbl,
                    format!("CENTER_LATITUDE {lat_c} is not a pole"),
                ));
            }
        };
        if lon_c != 0.0
            || (a_m - sphere.radius_m()).abs() > 1e-6
            || r.num("MAP_PROJECTION_ROTATION")? != 0.0
        {
            return Err(contract(
                &r.lbl,
                format!(
                    "projection (radius {a_m} m, central meridian {lon_c}) is not the body's polar stereographic"
                ),
            ));
        }
        Ok(Self {
            scale: r.num("SCALING_FACTOR")?,
            cell_m: r.num("MAP_SCALE")?,
            line_offset: r.num("LINE_PROJECTION_OFFSET")?,
            sample_offset: r.num("SAMPLE_PROJECTION_OFFSET")?,
            citation: r.citation(),
            id: r.id,
            dn: r.dn,
            lines: r.lines,
            samples: r.samples,
            proj,
            sphere,
        })
    }
}

impl TerrainSource for PolarGrid {
    fn id(&self) -> &str {
        &self.id
    }
    fn citation(&self) -> &str {
        &self.citation
    }
    fn resolution_m(&self) -> f64 {
        self.cell_m
    }
    fn sphere(&self) -> Sphere {
        self.sphere
    }
    /// Bilinear between pixel centres; `None` outside their hull (never extrapolated).
    #[allow(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss
    )] // pixel indices are far below 2^52
    fn sample_latlon(&self, ll: LatLon) -> Option<f64> {
        let (e, n) = self.proj.forward(ll).ok()?;
        let col = self.sample_offset + e / self.cell_m;
        let row = self.line_offset - n / self.cell_m;
        let (wmax, hmax) = ((self.samples - 1) as f64, (self.lines - 1) as f64);
        if !(col >= 0.0 && row >= 0.0 && col <= wmax && row <= hmax) {
            return None;
        }
        let c0 = (col.floor() as usize).min(self.samples - 2);
        let r0 = (row.floor() as usize).min(self.lines - 2);
        let (tx, ty) = (col - c0 as f64, row - r0 as f64);
        let z = |r: usize, c: usize| f64::from(self.dn[r * self.samples + c]);
        let v = (1.0 - ty) * ((1.0 - tx) * z(r0, c0) + tx * z(r0, c0 + 1))
            + ty * ((1.0 - tx) * z(r0 + 1, c0) + tx * z(r0 + 1, c0 + 1));
        Some(v * self.scale)
    }
}

impl TerrainSource for GlobalGrid {
    fn is_global(&self) -> bool {
        true
    }
    fn id(&self) -> &str {
        &self.id
    }
    fn citation(&self) -> &str {
        &self.citation
    }
    fn resolution_m(&self) -> f64 {
        2.0 * std::f64::consts::PI * self.sphere.radius_m() / 360.0 / self.res_ppd
    }
    fn sphere(&self) -> Sphere {
        self.sphere
    }
    /// Bilinear between pixel centres, wrapping in longitude; `None` within half a pixel of a pole.
    #[allow(
        clippy::cast_precision_loss,
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        clippy::cast_possible_wrap
    )] // pixel indices are far below 2^62; longitude wrap needs a signed modulo
    fn sample_latlon(&self, ll: LatLon) -> Option<f64> {
        let row = self.line_offset - ll.lat_deg * self.res_ppd;
        let lon = (ll.lon_deg - self.west_lon).rem_euclid(360.0) + self.west_lon;
        let col = self.sample_offset + (lon - self.center_lon) * self.res_ppd;
        if !(row >= 0.0 && row <= (self.lines - 1) as f64) {
            return None;
        }
        let r0 = (row.floor() as usize).min(self.lines - 2);
        let c0f = col.floor();
        let (ty, tx) = (row - r0 as f64, col - c0f);
        let n = self.samples as i64;
        let c0 = (c0f as i64).rem_euclid(n) as usize;
        let c1 = (c0f as i64 + 1).rem_euclid(n) as usize;
        let z = |r: usize, c: usize| f64::from(self.dn[r * self.samples + c]);
        let v = (1.0 - ty) * ((1.0 - tx) * z(r0, c0) + tx * z(r0, c1))
            + ty * ((1.0 - tx) * z(r0 + 1, c0) + tx * z(r0 + 1, c1));
        Some(v * self.scale)
    }
}

/// Identity of a terrain source inside a stack: what answered, at what resolution, and why it ranks.
#[derive(Debug, Clone, PartialEq)]
pub struct SourceDescriptor {
    pub id: String,
    pub resolution_m: f64,
    /// 1 is the highest priority.
    pub priority: u32,
    pub citation: String,
    pub global: bool,
}

/// The outcome of resolving a point against a [`TerrainStack`].
#[derive(Debug)]
pub enum Resolved<'a> {
    Covered {
        source: &'a SourceDescriptor,
        height_m: f64,
    },
    /// No installed source covers the point: the caller must report "cannot assess".
    NotCovered,
}

/// Terrain sources ordered by priority; each point resolves to the highest-priority source covering it.
#[derive(Debug)]
pub struct TerrainStack {
    sources: Vec<(SourceDescriptor, Box<dyn TerrainSource>)>,
}

impl TerrainStack {
    #[must_use]
    pub fn new(sources: Vec<(u32, Box<dyn TerrainSource>)>) -> Self {
        let mut sources: Vec<_> = sources
            .into_iter()
            .map(|(priority, t)| {
                let d = SourceDescriptor {
                    id: t.id().to_owned(),
                    resolution_m: t.resolution_m(),
                    priority,
                    citation: t.citation().to_owned(),
                    global: t.is_global(),
                };
                (d, t)
            })
            .collect();
        sources.sort_by_key(|(d, _)| d.priority);
        Self { sources }
    }

    /// Add a source, keeping the stack ordered by priority.
    pub fn push(&mut self, priority: u32, source: Box<dyn TerrainSource>) {
        let d = SourceDescriptor {
            id: source.id().to_owned(),
            resolution_m: source.resolution_m(),
            priority,
            citation: source.citation().to_owned(),
            global: source.is_global(),
        };
        let at = self
            .sources
            .partition_point(|(e, _)| e.priority <= priority);
        self.sources.insert(at, (d, source));
    }

    /// The stack's sources in priority order.
    pub fn descriptors(&self) -> impl Iterator<Item = &SourceDescriptor> {
        self.sources.iter().map(|(d, _)| d)
    }

    /// The stack's shape: regional tiers by resolution and global tiers by identity, in priority order. Two
    /// answers are comparable only when their stacks share a signature (navigator: no ranking across
    /// different terrain stacks).
    #[must_use]
    pub fn signature(&self) -> String {
        self.descriptors()
            .map(|d| {
                if d.global {
                    format!("{}@{:.1}m", d.id, d.resolution_m)
                } else {
                    format!("regional@{:.1}m", d.resolution_m)
                }
            })
            .collect::<Vec<_>>()
            .join(" > ")
    }

    /// The body sphere shared by the stack's sources (`None` for an empty stack).
    #[must_use]
    pub fn sphere(&self) -> Option<Sphere> {
        self.sources.first().map(|(_, t)| t.sphere())
    }

    #[must_use]
    pub fn resolve(&self, ll: LatLon) -> Resolved<'_> {
        self.sources
            .iter()
            .find_map(|(d, t)| {
                t.sample_latlon(ll).map(|height_m| Resolved::Covered {
                    source: d,
                    height_m,
                })
            })
            .unwrap_or(Resolved::NotCovered)
    }
}
