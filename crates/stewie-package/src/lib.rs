//! Installable data packages (navigator N11) and the resolution and coverage guard (N12, requirement R6).
//!
//! [`Package::open`] reads `manifest.json`, checks every file's size and sha256 before using a byte of it,
//! and builds the terrain stack and ephemeris the manifest names. [`Package::guard`] is the single gate
//! before any assessment: it names the terrain tier that answers at a point, and returns
//! [`CannotAssess`] when no tier covers the point, when the answering tier is coarser than the task needs,
//! or when any part of the requested time range is outside the ephemeris span. It never returns a partial
//! answer.

use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use lunar_dem::{
    DemError, GlobalGrid, PolarGrid, Resolved, SourceDescriptor, TerrainSource, TerrainStack,
};
use lunar_ephem::{EphemError, Ephemeris};
use lunar_frames::{LatLon, Sphere};
use sha2::{Digest, Sha256};
use stewie_contracts::package_manifest::{File, LayerKind, PackageManifest};

#[derive(Debug)]
pub enum PackageError {
    Io {
        path: PathBuf,
        source: std::io::Error,
    },
    Manifest(String),
    /// A file's size or sha256 differs from the manifest: the package is refused whole.
    Integrity {
        path: PathBuf,
        expected: String,
        actual: String,
    },
    Dem(DemError),
    Ephemeris(EphemError),
}

impl fmt::Display for PackageError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PackageError::Io { path, source } => write!(f, "{}: {source}", path.display()),
            PackageError::Manifest(m) => write!(f, "manifest: {m}"),
            PackageError::Integrity {
                path,
                expected,
                actual,
            } => write!(f, "{}: expected {expected}, found {actual}", path.display()),
            PackageError::Dem(e) => write!(f, "{e}"),
            PackageError::Ephemeris(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for PackageError {}

/// Why a request cannot be assessed. Never converted into a favourable answer.
#[derive(Debug, Clone, PartialEq)]
pub enum CannotAssess {
    /// No installed terrain covers the point.
    NoTerrain,
    /// The tier that answers here is coarser than the task needs.
    TooCoarse {
        source: String,
        resolution_m: f64,
        required_m: f64,
    },
    /// Part of the requested time range lies outside the ephemeris span `[start, end)` (TDB seconds).
    OutsideEphemeris { start_tdb: f64, end_tdb: f64 },
    /// The request itself is malformed (non-finite, reversed range, non-positive resolution).
    InvalidRequest(String),
}

impl fmt::Display for CannotAssess {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CannotAssess::NoTerrain => write!(f, "no installed terrain covers this point"),
            CannotAssess::TooCoarse {
                source,
                resolution_m,
                required_m,
            } => write!(
                f,
                "terrain here is {source} at {resolution_m:.1} m; the task needs {required_m:.1} m or finer"
            ),
            CannotAssess::OutsideEphemeris { start_tdb, end_tdb } => write!(
                f,
                "time outside the installed ephemeris (TDB {start_tdb} to {end_tdb} s)"
            ),
            CannotAssess::InvalidRequest(m) => write!(f, "invalid request: {m}"),
        }
    }
}

/// The tier that answers at a point, and its height there.
#[derive(Debug, Clone, Copy)]
pub struct Coverage<'a> {
    pub source: &'a SourceDescriptor,
    pub height_m: f64,
}

#[derive(Debug)]
pub struct Package {
    manifest: PackageManifest,
    stack: TerrainStack,
    ephemeris: Ephemeris,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().fold(String::new(), |mut s, b| {
        use fmt::Write as _;
        let _ = write!(s, "{b:02x}");
        s
    })
}

/// Read a manifest file entry and verify its size and sha256.
fn verified(dir: &Path, f: &File) -> Result<Vec<u8>, PackageError> {
    let path = dir.join(f.path.as_str());
    let bytes = fs::read(&path).map_err(|source| PackageError::Io {
        path: path.clone(),
        source,
    })?;
    if bytes.len() as u64 != f.bytes.get() {
        return Err(PackageError::Integrity {
            path,
            expected: format!("{} bytes", f.bytes),
            actual: format!("{} bytes", bytes.len()),
        });
    }
    let actual = hex(&Sha256::digest(&bytes));
    if actual != f.sha256.as_str() {
        return Err(PackageError::Integrity {
            path,
            expected: f.sha256.to_string(),
            actual,
        });
    }
    Ok(bytes)
}

impl Package {
    /// Open the package in `dir` on the registry body's `sphere`.
    ///
    /// # Errors
    /// I/O failure, a manifest that breaks the contract, any file whose size or sha256 differs, a layer
    /// whose label disagrees with the manifest, or an ephemeris that fails its own checks.
    pub fn open(dir: &Path, sphere: Sphere) -> Result<Self, PackageError> {
        let mpath = dir.join("manifest.json");
        let text = fs::read_to_string(&mpath).map_err(|source| PackageError::Io {
            path: mpath.clone(),
            source,
        })?;
        let manifest: PackageManifest =
            serde_json::from_str(&text).map_err(|e| PackageError::Manifest(e.to_string()))?;
        // the schema's `const` is not enforced by the generated type, so the format is checked here
        if manifest.format.as_str() != Some("stewie-package-v1") {
            return Err(PackageError::Manifest(format!(
                "format {} is not stewie-package-v1",
                manifest.format
            )));
        }
        let mut stack = TerrainStack::new(Vec::new());
        for l in &manifest.layers {
            let image = verified(dir, &l.image)?;
            let label = String::from_utf8(verified(dir, &l.label)?)
                .map_err(|e| PackageError::Manifest(format!("{}: {e}", l.label.path.as_str())))?;
            let source: Box<dyn TerrainSource> = match l.kind {
                LayerKind::PdsSimpleCylindrical => Box::new(
                    GlobalGrid::from_label_bytes(l.id.as_str(), &label, &image, sphere)
                        .map_err(PackageError::Dem)?,
                ),
                LayerKind::PdsPolarStereographic => Box::new(
                    PolarGrid::from_label_bytes(l.id.as_str(), &label, &image, sphere)
                        .map_err(PackageError::Dem)?,
                ),
            };
            if (source.resolution_m() - l.resolution_m).abs() > 1e-6
                || l.lat_min_deg > l.lat_max_deg
            {
                return Err(PackageError::Manifest(format!(
                    "{}: manifest says {} m over [{}, {}], the label gives {} m",
                    l.id.as_str(),
                    l.resolution_m,
                    l.lat_min_deg,
                    l.lat_max_deg,
                    source.resolution_m()
                )));
            }
            let priority = u32::try_from(l.priority.get())
                .map_err(|e| PackageError::Manifest(format!("{}: {e}", l.id.as_str())))?;
            stack.push(priority, source);
        }
        let e = &manifest.ephemeris;
        verified(dir, &e.data)?;
        verified(dir, &e.header)?;
        let ephemeris = Ephemeris::load(dir, e.name.as_str()).map_err(PackageError::Ephemeris)?;
        Ok(Self {
            manifest,
            stack,
            ephemeris,
        })
    }

    #[must_use]
    pub fn manifest(&self) -> &PackageManifest {
        &self.manifest
    }

    #[must_use]
    pub fn stack(&self) -> &TerrainStack {
        &self.stack
    }

    #[must_use]
    pub fn ephemeris(&self) -> &Ephemeris {
        &self.ephemeris
    }

    /// The gate before any assessment at `at` over TDB `[t0, t1]` needing terrain of `finest_needed_m` or
    /// finer. Both ends of the range must lie in the ephemeris span `[start, end)`.
    ///
    /// # Errors
    /// [`CannotAssess`] naming the first unmet condition; there is no partial answer.
    pub fn guard(
        &self,
        at: LatLon,
        t0: f64,
        t1: f64,
        finest_needed_m: f64,
    ) -> Result<Coverage<'_>, CannotAssess> {
        let finite = [at.lat_deg, at.lon_deg, t0, t1, finest_needed_m]
            .iter()
            .all(|v| v.is_finite());
        if !finite || t0 > t1 || finest_needed_m <= 0.0 || at.lat_deg.abs() > 90.0 {
            return Err(CannotAssess::InvalidRequest(format!(
                "{at:?}, TDB {t0}..{t1}, {finest_needed_m} m"
            )));
        }
        let (start_tdb, end_tdb) = self.ephemeris.span_tdb();
        if !(t0 >= start_tdb && t1 < end_tdb) {
            return Err(CannotAssess::OutsideEphemeris { start_tdb, end_tdb });
        }
        let Resolved::Covered { source, height_m } = self.stack.resolve(at) else {
            return Err(CannotAssess::NoTerrain);
        };
        if source.resolution_m > finest_needed_m {
            return Err(CannotAssess::TooCoarse {
                source: source.id.clone(),
                resolution_m: source.resolution_m,
                required_m: finest_needed_m,
            });
        }
        Ok(Coverage { source, height_m })
    }
}
