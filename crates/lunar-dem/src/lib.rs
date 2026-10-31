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
        let meta: DemBundle = serde_json::from_str(&text).map_err(|e| contract(&meta_path, e))?;
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
        let hm_path = dir.join(hm.file.as_str());
        let bytes = fs::read(&hm_path).map_err(io(&hm_path))?;
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
        let z = |r: usize, c: usize| f64::from(self.z[r * self.width + c]);
        let d = |lo: f64, hi: f64, span: f64| (hi - lo) / span;
        let gx = if col == 0 {
            d(z(row, 0), z(row, 1), self.cell_m)
        } else if col == self.width - 1 {
            d(z(row, col - 1), z(row, col), self.cell_m)
        } else {
            d(z(row, col - 1), z(row, col + 1), 2.0 * self.cell_m)
        };
        let gy = if row == 0 {
            d(z(0, col), z(1, col), self.cell_m)
        } else if row == self.height - 1 {
            d(z(row - 1, col), z(row, col), self.cell_m)
        } else {
            d(z(row - 1, col), z(row + 1, col), 2.0 * self.cell_m)
        };
        Some(gx.hypot(gy).atan().to_degrees())
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

/// Identity of a terrain source inside a stack: what answered, at what resolution, and why it ranks.
#[derive(Debug, Clone, PartialEq)]
pub struct SourceDescriptor {
    pub id: String,
    pub resolution_m: f64,
    /// 1 is the highest priority.
    pub priority: u32,
    pub citation: String,
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
    sources: Vec<(SourceDescriptor, DemTile)>,
}

impl TerrainStack {
    #[must_use]
    pub fn new(tiles: Vec<(u32, DemTile)>) -> Self {
        let mut sources: Vec<_> = tiles
            .into_iter()
            .map(|(priority, t)| {
                let d = SourceDescriptor {
                    id: t.id.clone(),
                    resolution_m: t.cell_m,
                    priority,
                    citation: t.citation.clone(),
                };
                (d, t)
            })
            .collect();
        sources.sort_by_key(|(d, _)| d.priority);
        Self { sources }
    }

    /// The body sphere shared by the stack's sources (`None` for an empty stack).
    #[must_use]
    pub fn sphere(&self) -> Option<Sphere> {
        self.sources.first().map(|(_, t)| t.sphere)
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
