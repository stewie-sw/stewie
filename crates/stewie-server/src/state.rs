//! The server's terrain state (RW-55b3b; Python `stewie.server.state`): the per-site DEM cache with its flattest
//! anchor, the per-(site, source) durable observed twins with the SR-03 journal-identity guards, and the composed
//! current terrain view (observed where measured, else as-built, else pristine) every planner and mesh reads.
//!
//! Site DEMs are the real 5 m bundles (`samples/lunar_dem/<bundle>`, the site registry naming each bundle;
//! Haworth honours `STEWIE_DEM_DIR`). A site with no DEM degrades to `None`, the flat slope-check, as the Python
//! does; the observed twin of such a site sits on a 64 x 64 zero base, as the Python's.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

use lunar_dem::{DemTile, flattest_anchor};
use lunar_frames::Sphere;
use serde_json::{Value, json};
use sha1::{Digest, Sha1};
use stewie_twin::terrain_memory;
use stewie_twin::terrain_view::{TerrainView, compose};
use stewie_twin::twin_store::TwinStore;

use crate::operators::py_repr;

/// The default observed twin's site and depth source (its journal keeps the plain `haworth.journal`).
pub const DEFAULT_TWIN_SITE: &str = "haworth";
pub const DEFAULT_TWIN_SOURCE: &str = "stereo_sgbm";
const IDENTITY_SCHEMA: &str = "stewie.twin-journal-identity/v1";
/// The window the flattest anchor averages slope over [m].
const ANCHOR_WINDOW_M: f64 = 20.0;
/// The observed twin's cell [m], as the Python fixes it.
const TWIN_CELL_M: f64 = 5.0;

/// A loaded site DEM: row-major heights [m] and the grid.
#[derive(Debug, Clone, PartialEq)]
pub struct SiteDem {
    pub z: Vec<f64>,
    pub rows: usize,
    pub cols: usize,
    pub cell_m: f64,
}

/// A twin journal that cannot be assigned to one (site, source) without operator evidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MigrationRequired(pub String);

impl std::fmt::Display for MigrationRequired {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for MigrationRequired {}

type Loaded = Option<(Arc<SiteDem>, (f64, f64))>;
/// The registry of observed twins, by normalised (site, source).
type Twins = HashMap<(String, String), Arc<Mutex<TwinStore>>>;

/// The terrain state of one server process.
pub struct Terrain {
    data_dir: PathBuf,
    samples_dir: PathBuf,
    dem_dir: Option<PathBuf>,
    sites: Value,
    sphere: Sphere,
    dems: Mutex<HashMap<String, Loaded>>,
    twins: Mutex<Twins>,
    /// One lock per site's Terrain Memory file (keyed as the file is), for its load-apply-save.
    site_locks: Mutex<HashMap<String, Arc<Mutex<()>>>>,
}

impl std::fmt::Debug for Terrain {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Terrain")
            .field("samples_dir", &self.samples_dir)
            .finish_non_exhaustive()
    }
}

/// `str(value).strip().lower()`.
fn canonical(v: &str) -> String {
    v.trim().to_lowercase()
}

/// The pre-SR-03 lossy stem: runs of anything outside `[a-z0-9]` become `_`, trimmed of `_`.
fn legacy_safe_site(site: &str) -> String {
    let raw = canonical(site);
    let mut out = String::new();
    let mut gap = false;
    for c in raw.chars() {
        if c.is_ascii_lowercase() || c.is_ascii_digit() {
            if gap && !out.is_empty() {
                out.push('_');
            }
            gap = false;
            out.push(c);
        } else {
            gap = true;
        }
    }
    if out.is_empty() {
        "site".to_owned()
    } else {
        out
    }
}

/// The collision-safe stem: the legacy stem, plus the first 8 hex digits of the sha1 of the canonical name when
/// sanitising rewrote it (so a name already in `[a-z0-9_]` keeps its historical filename).
#[must_use]
pub fn safe_site(site: &str) -> String {
    let raw = canonical(site);
    let stem = legacy_safe_site(&raw);
    if stem == raw {
        return stem;
    }
    let digest = Sha1::digest(raw.as_bytes());
    let hex = digest.iter().take(4).fold(String::new(), |mut h, b| {
        use std::fmt::Write as _;
        let _ = write!(h, "{b:02x}");
        h
    });
    format!("{stem}_{hex}")
}

fn pair(site: &str, source: &str) -> String {
    format!("({}, {})", py_repr(site), py_repr(source))
}

fn shown(p: &Path) -> String {
    py_repr(&p.display().to_string())
}

fn marker_of(journal: &Path) -> PathBuf {
    PathBuf::from(format!("{}.identity.json", journal.display()))
}

/// The identity a journal's marker records, `None` without a marker.
fn read_identity(journal: &Path) -> Result<Option<(String, String)>, MigrationRequired> {
    let marker = marker_of(journal);
    if !marker.exists() {
        return Ok(None);
    }
    let invalid = |e: String| {
        MigrationRequired(format!(
            "twin journal identity marker {} is invalid: {e}",
            shown(&marker)
        ))
    };
    let body: Value = serde_json::from_str(
        &std::fs::read_to_string(&marker).map_err(|e| invalid(e.to_string()))?,
    )
    .map_err(|e| invalid(e.to_string()))?;
    if body["schema"] != IDENTITY_SCHEMA {
        return Err(invalid("invalid identity schema".to_owned()));
    }
    match (body["site"].as_str(), body["source"].as_str()) {
        (Some(site), Some(source)) => Ok(Some((canonical(site), canonical(source)))),
        _ => Err(invalid("the marker names no site and source".to_owned())),
    }
}

/// Persist a journal's identity before it can receive observations (`json.dumps(indent=1, sort_keys=True)`).
fn write_identity(journal: &Path, site: &str, source: &str) -> Result<(), String> {
    let s = |v: &str| stewie_twin::pyjson::dumps(&json!(canonical(v))).unwrap_or_default();
    let body = format!(
        "{{\n \"schema\": {},\n \"site\": {},\n \"source\": {}\n}}\n",
        s(IDENTITY_SCHEMA),
        s(site),
        s(source)
    );
    crate::atomic_write(&marker_of(journal), body.as_bytes())?;
    if let Some(dir) = journal.parent() {
        std::fs::File::open(dir)
            .and_then(|d| d.sync_all())
            .map_err(|e| format!("{}: {e}", dir.display()))?;
    }
    Ok(())
}

impl Terrain {
    /// The state over `data_dir`, with the bundles under `samples_dir` (Haworth's at `dem_dir` when given), the
    /// site registry and the body's sphere.
    #[must_use]
    pub fn new(
        data_dir: PathBuf,
        samples_dir: PathBuf,
        dem_dir: Option<PathBuf>,
        sites: Value,
        sphere: Sphere,
    ) -> Self {
        Self {
            data_dir,
            samples_dir,
            dem_dir,
            sites,
            sphere,
            dems: Mutex::new(HashMap::new()),
            twins: Mutex::new(HashMap::new()),
            site_locks: Mutex::new(HashMap::new()),
        }
    }

    /// The bundle directory of an imported site.
    ///
    /// # Errors
    /// An unknown site, or one with no bundle on disk.
    pub fn bundle_for_site(&self, site: &str) -> Result<PathBuf, String> {
        let Some(entry) = self.sites.get(site) else {
            let mut known: Vec<String> = self
                .sites
                .as_object()
                .map(|m| m.keys().map(|k| py_repr(k)).collect())
                .unwrap_or_default();
            known.sort();
            return Err(format!(
                "unknown site {} (known: [{}])",
                py_repr(site),
                known.join(", ")
            ));
        };
        if site == DEFAULT_TWIN_SITE
            && let Some(d) = &self.dem_dir
        {
            return Ok(d.clone());
        }
        entry["bundle"]
            .as_str()
            .map(|b| self.samples_dir.join(b))
            .filter(|d| d.is_dir())
            .ok_or_else(|| {
                format!(
                    "site {} is not imported (no DEM bundle); fetch it first",
                    py_repr(site)
                )
            })
    }

    /// The lock serialising a site's Terrain Memory read-modify-write (two spellings of one file share it).
    #[must_use]
    pub fn site_lock(&self, site: &str) -> Arc<Mutex<()>> {
        let key = terrain_memory::safe_site(site);
        self.site_locks
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .entry(key)
            .or_default()
            .clone()
    }

    /// The registry's bundle name of a site (its DEM provenance id), when it has one.
    #[must_use]
    pub fn bundle_name(&self, site: &str) -> Option<String> {
        self.sites.get(site)?["bundle"].as_str().map(str::to_owned)
    }

    /// The site's DEM and flattest anchor, loaded once; `None` (the flat slope-check) when there is none.
    pub fn moon_dem(&self, site: &str) -> Loaded {
        if let Some(hit) = self
            .dems
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(site)
        {
            return hit.clone();
        }
        let loaded = self
            .bundle_for_site(site)
            .and_then(|dir| DemTile::open(&dir, self.sphere).map_err(|e| e.to_string()));
        let out = match loaded {
            Ok(t) => {
                let z = t.heights_f64();
                let anchor =
                    flattest_anchor(&z, t.width(), t.height(), t.cell_m(), ANCHOR_WINDOW_M);
                Some((
                    Arc::new(SiteDem {
                        z,
                        rows: t.height(),
                        cols: t.width(),
                        cell_m: t.cell_m(),
                    }),
                    anchor,
                ))
            }
            Err(e) => {
                eprintln!(
                    "DEM for site {} unavailable; falling back to flat slope-check: {e}",
                    py_repr(site)
                );
                None
            }
        };
        self.dems
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(site.to_owned(), out.clone());
        out
    }

    fn twin_dir(&self) -> PathBuf {
        self.data_dir.join("twin")
    }

    /// Refuse a journal the pre-SR-03 raw source comparison may have written (`<site>__stereo_sgbm`).
    fn guard_raw_legacy(
        &self,
        raw_site: &str,
        raw_source: &str,
        site: &str,
        source: &str,
    ) -> Result<(), MigrationRequired> {
        let old_stem = if raw_source == DEFAULT_TWIN_SOURCE {
            legacy_safe_site(raw_site)
        } else {
            format!(
                "{}__{}",
                legacy_safe_site(raw_site),
                legacy_safe_site(raw_source)
            )
        };
        let current_stem = if source == DEFAULT_TWIN_SOURCE {
            safe_site(site)
        } else {
            format!("{}__{}", safe_site(site), safe_site(source))
        };
        let old = self.twin_dir().join(format!("{old_stem}.journal"));
        let current = self.twin_dir().join(format!("{current_stem}.journal"));
        if old == current || !old.exists() {
            return Ok(());
        }
        let expected = (site.to_owned(), source.to_owned());
        match read_identity(&old)? {
            None => Err(MigrationRequired(format!(
                "raw-source legacy twin journal {} has no identity marker for {}; inspect it and explicitly \
                 migrate/quarantine it",
                shown(&old),
                pair(site, source)
            ))),
            Some(id) if id == expected => Err(MigrationRequired(format!(
                "raw-source legacy twin journal {} is assigned to {}; move it and its identity marker to canonical \
                 path {}",
                shown(&old),
                pair(site, source),
                shown(&current)
            ))),
            Some(_) => Ok(()),
        }
    }

    /// Cold-restore (or create) the durable twin of a canonical (site, source), after the identity checks.
    fn build_twin(&self, site: &str, source: &str) -> Result<TwinStore, String> {
        let (base, rows, cols) = match self.moon_dem(site) {
            Some((d, _)) => (d.z.clone(), d.rows, d.cols),
            None => (vec![0.0; 64 * 64], 64, 64),
        };
        let jdir = self.twin_dir();
        std::fs::create_dir_all(&jdir).map_err(|e| format!("{}: {e}", jdir.display()))?;
        let stem = |f: fn(&str) -> String| {
            if f(source) == f(DEFAULT_TWIN_SOURCE) {
                f(site)
            } else {
                format!("{}__{}", f(site), f(source))
            }
        };
        let jp = jdir.join(format!("{}.journal", stem(safe_site)));
        let legacy = jdir.join(format!("{}.journal", stem(legacy_safe_site)));
        let identity = (site.to_owned(), source.to_owned());
        let id_str = pair(site, source);
        let ambiguous =
            self.sites.get(site).is_none() || source != DEFAULT_TWIN_SOURCE || legacy != jp;
        let legacy_identity = read_identity(&legacy).map_err(|e| e.0)?;
        let current_identity = read_identity(&jp).map_err(|e| e.0)?;
        let refuse = |m: String| Err(MigrationRequired(m).0);
        if ambiguous && legacy.exists() {
            match &legacy_identity {
                None => {
                    return refuse(format!(
                        "legacy twin journal {} has no identity marker and is ambiguous for {id_str}; inspect it, then \
                         migrate/quarantine it and create {}",
                        shown(&legacy),
                        shown(&marker_of(&legacy))
                    ));
                }
                Some(l) if *l != identity && legacy == jp => {
                    return refuse(format!(
                        "twin journal {} is assigned to {}, not {id_str}",
                        shown(&legacy),
                        pair(&l.0, &l.1)
                    ));
                }
                Some(l) if *l == identity && legacy != jp => {
                    return refuse(format!(
                        "legacy twin journal {} is explicitly assigned to {id_str}; move it and its identity marker to \
                         collision-safe path {} before continuing",
                        shown(&legacy),
                        shown(&jp)
                    ));
                }
                Some(_) => {}
            }
        }
        if jp.exists() {
            if current_identity.is_none() && ambiguous {
                return refuse(format!(
                    "twin journal {} has no collision-safe identity marker for {id_str}",
                    shown(&jp)
                ));
            }
            if let Some(c) = &current_identity
                && *c != identity
            {
                return refuse(format!(
                    "twin journal {} is assigned to {}, not {id_str}",
                    shown(&jp),
                    pair(&c.0, &c.1)
                ));
            }
        } else if let Some(c) = &current_identity
            && *c != identity
        {
            return refuse(format!(
                "twin journal marker {} is assigned to {}, not {id_str}",
                shown(&marker_of(&jp)),
                pair(&c.0, &c.1)
            ));
        }
        if current_identity.is_none() {
            write_identity(&jp, site, source)?;
        }
        TwinStore::from_journal(base, rows, cols, TWIN_CELL_M, &jp).map_err(|e| e.to_string())
    }

    /// The durable observed twin of `(site, source)`, one per normalised key, built once.
    ///
    /// # Errors
    /// A journal that needs migration ([`MigrationRequired`]'s text), or an unreadable journal.
    pub fn twin(&self, site: &str, source: &str) -> Result<Arc<Mutex<TwinStore>>, String> {
        let (cs, csrc) = (canonical(site), canonical(source));
        self.guard_raw_legacy(site, source, &cs, &csrc)
            .map_err(|e| e.0)?;
        let key = (safe_site(&cs), safe_site(&csrc));
        let mut twins = self
            .twins
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(t) = twins.get(&key) {
            return Ok(t.clone());
        }
        let default = key == (safe_site(DEFAULT_TWIN_SITE), safe_site(DEFAULT_TWIN_SOURCE));
        let built = if default {
            self.build_twin(DEFAULT_TWIN_SITE, DEFAULT_TWIN_SOURCE)
        } else {
            self.build_twin(&cs, &csrc)
        }?;
        let t = Arc::new(Mutex::new(built));
        twins.insert(key, t.clone());
        Ok(t)
    }

    /// The composed planning surface of a site's DEM (`origin` the order-frame anchor): the recorded Terrain
    /// Memory imprinted, then the site's observed twin where it has measured cells on the same grid. A layer
    /// that cannot be read is skipped, never failing the consumer.
    #[must_use]
    pub fn current_terrain_view(
        &self,
        site: &str,
        dem: &SiteDem,
        origin: (f64, f64),
    ) -> TerrainView {
        let as_built = match terrain_memory::load_site(&self.data_dir, site) {
            Ok(Some(mem)) => {
                match mem.imprint_on_dem_resampled(&dem.z, dem.cols, dem.cell_m, origin) {
                    Ok(z) => Some((z, mem.version())),
                    Err(e) => {
                        eprintln!("as-built imprint skipped for site {}: {e}", py_repr(site));
                        None
                    }
                }
            }
            Ok(None) => None,
            Err(e) => {
                eprintln!("as-built imprint skipped for site {}: {e}", py_repr(site));
                None
            }
        };
        let observed = match self.twin(site, DEFAULT_TWIN_SOURCE) {
            Ok(t) => {
                let tw = t.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
                let mask = tw.observed_mask();
                (tw.shape() == (dem.rows, dem.cols) && mask.iter().any(|&m| m))
                    .then(|| (tw.current(), mask, tw.version()))
            }
            Err(e) => {
                eprintln!(
                    "observed-twin overlay skipped for site {}: {e}",
                    py_repr(site)
                );
                None
            }
        };
        compose(
            &dem.z,
            dem.cell_m,
            as_built.as_ref().map(|(z, v)| (z.as_slice(), *v)),
            observed
                .as_ref()
                .map(|(h, m, v)| (h.as_slice(), m.as_slice(), *v)),
        )
    }
}
