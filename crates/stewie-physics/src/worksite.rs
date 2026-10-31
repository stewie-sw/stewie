//! The worksite session (Python `stewie.physics.worksite.WorkSite`, RW-22a): a coarse base loaded from a
//! real terrain bundle, a worked window that follows the rover, one global drum ledger, and worked-tile
//! paging, so mass is conserved across every window move.
//!
//! Two entry paths, mutually exclusive as in the Python: [`WorkSite::open_window`] works one tile, and
//! [`WorkSite::recenter`] / [`WorkSite::step`] stream the window with the rover. A refused command, a target
//! outside the site, or terrain whose DEM round-trip was never verified changes nothing. This node is the
//! native path (worked cell = base cell); sub-cell refinement is RW-22b.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::path::Path;

use stewie_contracts::dem_bundle::{self, DemBundle};

use crate::PhysicsError;
use crate::column::{ColumnState, Fields, Regolith, StateLabel};
use crate::drive::{self, StepCommand, Telemetry, Vehicle};
use crate::material::MaterialModel;
use crate::rover;
use crate::sandpile::{Sandpile, SandpileConfig};
use crate::soil::SoilParams;

#[derive(Debug, Clone, PartialEq)]
pub enum WorkSiteError {
    /// A non-finite or over-limit command (M-04). Nothing changed.
    Command(String),
    /// A target outside the site (NM-7). Nothing changed.
    Bounds(String),
    /// Terrain whose DEM round-trip was never verified (NM-7 clause 2). Nothing changed.
    Datum(String),
    /// The wrong entry path, or no open window.
    Path(String),
    /// A terrain bundle that breaks its contract or fails the datum round-trip (CT-06).
    Bundle(String),
    Physics(PhysicsError),
}

impl fmt::Display for WorkSiteError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            WorkSiteError::Command(m) => write!(f, "command refused: {m}"),
            WorkSiteError::Bounds(m) => write!(f, "outside the site: {m}"),
            WorkSiteError::Datum(m) => write!(f, "datum not verified: {m}"),
            WorkSiteError::Path(m) => write!(f, "entry path: {m}"),
            WorkSiteError::Bundle(m) => write!(f, "bundle: {m}"),
            WorkSiteError::Physics(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for WorkSiteError {}

impl From<PhysicsError> for WorkSiteError {
    fn from(e: PhysicsError) -> Self {
        WorkSiteError::Physics(e)
    }
}

/// Everything the session needs besides terrain.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Setup {
    pub vehicle: Vehicle,
    pub soil: SoilParams,
    /// Density-driven soil strength under the rover; `None` uses `soil` everywhere.
    pub material: Option<MaterialModel>,
    pub regolith: Regolith,
    pub gravity_ms2: f64,
    /// Drive-speed ceiling [m/s] (the profile's `drive_speed_ms`); the yaw-rate ceiling is `2 v_max / gauge`.
    pub v_max: f64,
    /// Base cells per paging tile side.
    pub tile_base_cells: usize,
}

/// One [`WorkSite::step`]: the drive telemetry plus the session's own flags.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct StepReport {
    pub drive: Telemetry,
    pub bounds_clamped: bool,
    pub recentered: bool,
    pub pose_xy: (f64, f64),
    pub window_origin: (f64, f64),
    /// Worked-window cells the wheels carved, `[r0, c0, r1, c1]` half-open.
    pub dirty: [usize; 4],
}

/// A [`WorkSite::drive`] run (Python `closed_loop_drive`).
#[derive(Debug, Clone, PartialEq)]
pub struct DriveRun {
    pub steps: Vec<Telemetry>,
    pub commanded_dist_m: f64,
    pub achieved_dist_m: f64,
    pub final_rc: (f64, f64),
    pub final_yaw: f64,
    pub any_entrapped: bool,
}

type TileKey = (i64, i64);

fn bundle_err(m: impl fmt::Display) -> WorkSiteError {
    WorkSiteError::Bundle(m.to_string())
}

fn read_field(
    dir: &Path,
    meta: &DemBundle,
    name: &str,
    n: usize,
) -> Result<Vec<u8>, WorkSiteError> {
    let f = &meta.fields;
    let spec = match name {
        "heightmap" => Some(&f.heightmap),
        "mass_areal" => f.mass_areal.as_ref(),
        "density" => f.density.as_ref(),
        "disturbance" => f.disturbance.as_ref(),
        _ => f.state_label.as_ref(),
    }
    .ok_or_else(|| bundle_err(format!("{}: no {name} field", dir.display())))?;
    let (dtype, width) = if name == "state_label" {
        ("u1", 1)
    } else {
        ("<f4", 4)
    };
    if spec.dtype.to_string() != dtype {
        return Err(bundle_err(format!(
            "{name} dtype {} is not {dtype}",
            spec.dtype
        )));
    }
    let path = dir.join(spec.file.as_str());
    let bytes = fs::read(&path).map_err(|e| bundle_err(format!("{}: {e}", path.display())))?;
    if bytes.len() != n * width {
        return Err(bundle_err(format!(
            "{}: {} bytes, the grid needs {}",
            path.display(),
            bytes.len(),
            n * width
        )));
    }
    Ok(bytes)
}

fn f32s(bytes: &[u8]) -> Vec<f64> {
    bytes
        .chunks_exact(4)
        .map(|b| f64::from(f32::from_le_bytes([b[0], b[1], b[2], b[3]])))
        .collect()
}

/// Load a terrain bundle (`metadata.json` plus field rasters) as a coarse base, with its world origin
/// `(x0, y0)`. The bundle stores the height, not the datum: `datum = height - mass/density`, then the derived
/// height must reproduce the saved one (CT-06, `numpy.allclose` with `atol` 1e-3 and `rtol` 1e-5).
///
/// # Errors
/// A missing or malformed file, a field of the wrong size or type, or a failed round-trip.
pub fn coarse_base_from_bundle(
    dir: &Path,
    regolith: &Regolith,
) -> Result<(ColumnState, (f64, f64)), WorkSiteError> {
    let mpath = dir.join("metadata.json");
    let text =
        fs::read_to_string(&mpath).map_err(|e| bundle_err(format!("{}: {e}", mpath.display())))?;
    let meta: DemBundle = serde_json::from_str(&text).map_err(bundle_err)?;
    dem_bundle::check(&meta).map_err(bundle_err)?;
    let w = usize::try_from(meta.grid.width.get()).map_err(bundle_err)?;
    let h = usize::try_from(meta.grid.height.get()).map_err(bundle_err)?;
    let n = w * h;
    let height = f32s(&read_field(dir, &meta, "heightmap", n)?);
    let mass_areal = f32s(&read_field(dir, &meta, "mass_areal", n)?);
    let density = f32s(&read_field(dir, &meta, "density", n)?);
    let disturbance = f32s(&read_field(dir, &meta, "disturbance", n)?);
    let state_label = read_field(dir, &meta, "state_label", n)?;
    let datum = (0..n)
        .map(|i| height[i] - mass_areal[i] / density[i])
        .collect();
    let base = ColumnState::new(
        w,
        h,
        meta.grid.cell_m,
        Fields {
            mass_areal,
            density,
            state_label,
            disturbance,
            datum,
            ice: None,
        },
        0.0,
        regolith,
    )?;
    let derived = base.derive_height();
    if let Some(i) =
        (0..n).find(|&i| (derived[i] - height[i]).abs() > 1e-3 + 1e-5 * height[i].abs())
    {
        return Err(bundle_err(format!(
            "datum round-trip: derived {} vs saved {} at cell {i}",
            derived[i], height[i]
        )));
    }
    Ok((base, (meta.world_bounds_m.x0, meta.world_bounds_m.y0)))
}

/// The cells `[r0, r1) x [c0, c1)` of a field set whose rows are `width` long.
fn block(f: &Fields, width: usize, [r0, c0, r1, c1]: [usize; 4]) -> Fields {
    let take = |v: &[f64]| -> Vec<f64> {
        (r0..r1)
            .flat_map(|r| v[r * width + c0..r * width + c1].iter().copied())
            .collect()
    };
    Fields {
        mass_areal: take(&f.mass_areal),
        density: take(&f.density),
        state_label: (r0..r1)
            .flat_map(|r| {
                f.state_label[r * width + c0..r * width + c1]
                    .iter()
                    .copied()
            })
            .collect(),
        disturbance: take(&f.disturbance),
        datum: take(&f.datum),
        ice: None,
    }
}

/// Write `src` (`tw` wide) into `dst` (`width` wide) with its corner at `(r0, c0)`.
fn paste(dst: &mut Fields, width: usize, src: &Fields, tw: usize, (r0, c0): (usize, usize)) {
    for r in 0..src.mass_areal.len() / tw {
        let (d, s) = ((r0 + r) * width + c0, r * tw);
        dst.mass_areal[d..d + tw].copy_from_slice(&src.mass_areal[s..s + tw]);
        dst.density[d..d + tw].copy_from_slice(&src.density[s..s + tw]);
        dst.state_label[d..d + tw].copy_from_slice(&src.state_label[s..s + tw]);
        dst.disturbance[d..d + tw].copy_from_slice(&src.disturbance[s..s + tw]);
        dst.datum[d..d + tw].copy_from_slice(&src.datum[s..s + tw]);
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorkSite {
    base: ColumnState,
    setup: Setup,
    cell_m: f64,
    /// Site box `[x0, y0, x1, y1]` [m]: x grows with column, y with row.
    world: [f64; 4],
    datum_verified: bool,
    n_tiles: (i64, i64),
    fine: Option<ColumnState>,
    window_region_rc: Option<[usize; 4]>,
    window_origin: Option<(f64, f64)>,
    inventory_kg: f64,
    peak_inventory_kg: f64,
    cut_total_kg: f64,
    placed_total_kg: f64,
    /// Single-window (`open_window`) conservation baseline.
    baseline_mass: Option<f64>,
    /// Streaming conservation baseline: the virgin mass of every tile that has entered the worked domain.
    baseline_virgin_kg: f64,
    worked_store: BTreeMap<TileKey, Fields>,
    active_blocks: BTreeSet<TileKey>,
    active_origin: Option<(usize, usize)>,
    recenters: usize,
    pose_xy: Option<(f64, f64)>,
    yaw: f64,
    last_rover_xy: Option<(f64, f64)>,
    /// Per-tick command ceilings (M-04).
    pub v_max: f64,
    pub omega_max: f64,
}

impl WorkSite {
    /// A session over `base`, placed with its `(0, 0)` cell corner at world `origin` `(x0, y0)`.
    /// `datum_verified` is true only for terrain loaded through the round-trip check ([`Self::from_bundle`]).
    ///
    /// # Errors
    /// A zero tile size or a non-positive drive speed or gauge.
    pub fn new(
        base: ColumnState,
        origin: (f64, f64),
        setup: Setup,
        datum_verified: bool,
    ) -> Result<Self, WorkSiteError> {
        let s = &setup;
        if s.tile_base_cells == 0
            || !(s.v_max.is_finite() && s.v_max > 0.0)
            || !(s.vehicle.gauge_m.is_finite() && s.vehicle.gauge_m > 0.0)
        {
            return Err(WorkSiteError::Command(format!(
                "tile {} cells, v_max {}, gauge {}",
                s.tile_base_cells, s.v_max, s.vehicle.gauge_m
            )));
        }
        let cell_m = base.cell_m();
        #[allow(clippy::cast_precision_loss)] // grid sizes are far below 2^52
        let world = [
            origin.0,
            origin.1,
            origin.0 + base.width() as f64 * cell_m,
            origin.1 + base.height() as f64 * cell_m,
        ];
        let tiles = |n: usize| i64::try_from(n.div_ceil(s.tile_base_cells)).unwrap_or(i64::MAX);
        let n_tiles = (tiles(base.height()), tiles(base.width()));
        Ok(Self {
            base,
            cell_m,
            world,
            datum_verified,
            n_tiles,
            fine: None,
            window_region_rc: None,
            window_origin: None,
            inventory_kg: 0.0,
            peak_inventory_kg: 0.0,
            cut_total_kg: 0.0,
            placed_total_kg: 0.0,
            baseline_mass: None,
            baseline_virgin_kg: 0.0,
            worked_store: BTreeMap::new(),
            active_blocks: BTreeSet::new(),
            active_origin: None,
            recenters: 0,
            pose_xy: None,
            yaw: 0.0,
            last_rover_xy: None,
            v_max: setup.v_max,
            omega_max: 2.0 * setup.v_max / setup.vehicle.gauge_m,
            setup,
        })
    }

    /// A session over a terrain bundle, datum-verified by the load.
    ///
    /// # Errors
    /// As [`coarse_base_from_bundle`] and [`Self::new`].
    pub fn from_bundle(dir: &Path, setup: Setup) -> Result<Self, WorkSiteError> {
        let (base, origin) = coarse_base_from_bundle(dir, &setup.regolith)?;
        Self::new(base, origin, setup, true)
    }

    #[must_use]
    pub fn fine(&self) -> Option<&ColumnState> {
        self.fine.as_ref()
    }

    #[must_use]
    pub fn window_origin(&self) -> Option<(f64, f64)> {
        self.window_origin
    }

    #[must_use]
    pub fn window_region_rc(&self) -> Option<[usize; 4]> {
        self.window_region_rc
    }

    /// The global drum ledger [kg].
    #[must_use]
    pub fn inventory_kg(&self) -> f64 {
        self.inventory_kg
    }

    #[must_use]
    pub fn peak_inventory_kg(&self) -> f64 {
        self.peak_inventory_kg
    }

    /// Total mass ever cut into the drum [kg]; never reduced by a dump.
    #[must_use]
    pub fn cut_total_kg(&self) -> f64 {
        self.cut_total_kg
    }

    /// Total mass ever placed by a dump [kg].
    #[must_use]
    pub fn placed_total_kg(&self) -> f64 {
        self.placed_total_kg
    }

    #[must_use]
    pub fn recenters(&self) -> usize {
        self.recenters
    }

    #[must_use]
    pub fn yaw(&self) -> f64 {
        self.yaw
    }

    #[must_use]
    pub fn world(&self) -> [f64; 4] {
        self.world
    }

    /// Paged-out tiles with their grid mass [kg/m^2 summed], in tile order.
    #[must_use]
    pub fn worked_tiles(&self) -> Vec<(TileKey, f64)> {
        self.worked_store
            .iter()
            .map(|(&t, f)| (t, f.mass_areal.iter().sum()))
            .collect()
    }

    /// Base `(row, col)` to world `(x, y)`.
    #[must_use]
    pub fn base_rc_to_xy(&self, (br, bc): (f64, f64)) -> (f64, f64) {
        (
            self.world[0] + bc * self.cell_m,
            self.world[1] + br * self.cell_m,
        )
    }

    fn require_fine(&self) -> Result<&ColumnState, WorkSiteError> {
        self.fine
            .as_ref()
            .ok_or_else(|| WorkSiteError::Path("open_window or recenter must come first".into()))
    }

    fn require_fine_mut(&mut self) -> Result<&mut ColumnState, WorkSiteError> {
        self.fine
            .as_mut()
            .ok_or_else(|| WorkSiteError::Path("open_window or recenter must come first".into()))
    }

    /// Base-cell region `[r0, c0, r1, c1]` of tile `t`, clipped to the base.
    #[allow(clippy::cast_sign_loss, clippy::cast_possible_truncation)] // tiles are in-site, so >= 0
    fn tile_region(&self, (tr, tc): TileKey) -> [usize; 4] {
        let t = self.setup.tile_base_cells;
        let (r0, c0) = (tr as usize * t, tc as usize * t);
        [
            r0,
            c0,
            (r0 + t).min(self.base.height()),
            (c0 + t).min(self.base.width()),
        ]
    }

    /// Unworked fields of tile `t` (native path: the base cells themselves).
    fn virgin_tile(&self, t: TileKey) -> Fields {
        block(self.base.fields(), self.base.width(), self.tile_region(t))
    }

    fn tile_grid_mass(&self, f: &Fields) -> f64 {
        f.mass_areal.iter().sum::<f64>() * self.cell_m * self.cell_m
    }

    /// Tiles whose base region meets the disc of `radius_m` around `xy`, in scan order.
    #[allow(clippy::cast_possible_truncation)] // floor of a bounded tile index
    fn tiles_in_disc(&self, (x, y): (f64, f64), radius_m: f64) -> Vec<TileKey> {
        let (row, col) = (
            (y - self.world[1]) / self.cell_m,
            (x - self.world[0]) / self.cell_m,
        );
        let rad = radius_m / self.cell_m;
        #[allow(clippy::cast_precision_loss)]
        let t = self.setup.tile_base_cells as f64;
        let lo_hi = |v: f64| {
            (
                ((v - rad) / t).floor() as i64,
                ((v + rad) / t).floor() as i64,
            )
        };
        let ((r_lo, r_hi), (c_lo, c_hi)) = (lo_hi(row), lo_hi(col));
        let mut out = Vec::new();
        for tr in r_lo.max(0)..=r_hi.min(self.n_tiles.0 - 1) {
            for tc in c_lo.max(0)..=c_hi.min(self.n_tiles.1 - 1) {
                out.push((tr, tc));
            }
        }
        out
    }

    fn note_inventory(&mut self) {
        self.peak_inventory_kg = self.peak_inventory_kg.max(self.inventory_kg);
    }

    /// Work the single tile under base cell `base_rc` (the tile containing it among those within
    /// `radius_m`). The single-window entry: refused once the streaming path has started.
    ///
    /// # Errors
    /// [`WorkSiteError::Path`] after [`Self::recenter`]; [`WorkSiteError::Bounds`] when no tile is near.
    #[allow(clippy::cast_precision_loss)] // region corners are far below 2^52
    pub fn open_window(&mut self, base_rc: (f64, f64), radius_m: f64) -> Result<(), WorkSiteError> {
        if self.baseline_virgin_kg != 0.0 {
            return Err(WorkSiteError::Path(
                "open_window after recenter: the streaming conservation baseline is active".into(),
            ));
        }
        let tiles = self.tiles_in_disc(self.base_rc_to_xy(base_rc), radius_m);
        let (br, bc) = base_rc;
        let tile = tiles
            .iter()
            .copied()
            .find(|&t| {
                let [r0, c0, r1, c1] = self.tile_region(t);
                (r0 as f64) <= br && br < r1 as f64 && (c0 as f64) <= bc && bc < c1 as f64
            })
            .or_else(|| tiles.first().copied())
            .ok_or_else(|| WorkSiteError::Bounds(format!("no tile near base cell {base_rc:?}")))?;
        let region = self.tile_region(tile);
        let fields = self.virgin_tile(tile);
        let (h, w) = (region[2] - region[0], region[3] - region[1]);
        self.fine = Some(ColumnState::new(
            w,
            h,
            self.cell_m,
            fields,
            0.0,
            &self.setup.regolith,
        )?);
        self.window_region_rc = Some(region);
        self.window_origin = Some((
            self.world[0] + region[1] as f64 * self.cell_m,
            self.world[1] + region[0] as f64 * self.cell_m,
        ));
        self.baseline_mass = Some(self.total_mass());
        Ok(())
    }

    /// Page the active window's worked state back into the store, per tile.
    fn commit_active(&mut self) {
        let (Some(fine), Some((br0, bc0))) = (&self.fine, self.active_origin) else {
            return;
        };
        for &t in &self.active_blocks {
            let [r0, c0, r1, c1] = self.tile_region(t);
            let region = [r0 - br0, c0 - bc0, r1 - br0, c1 - bc0];
            self.worked_store
                .insert(t, block(fine.fields(), fine.width(), region));
        }
    }

    /// Slide the worked window to cover the rover's tile and `radius_tiles` around it, paging the old
    /// window's worked state out and assembling the new one from worked or virgin tiles. Returns whether the
    /// window moved. The drum ledger carries over unchanged; a first-visit tile adds its virgin mass to the
    /// conservation baseline.
    ///
    /// # Errors
    /// [`WorkSiteError::Path`] after [`Self::open_window`]; [`WorkSiteError::Bounds`] when no tile of the box
    /// lies on the site. Either leaves the session unchanged.
    #[allow(clippy::cast_possible_truncation, clippy::cast_precision_loss)]
    pub fn recenter(
        &mut self,
        target: (f64, f64),
        radius_tiles: i64,
    ) -> Result<bool, WorkSiteError> {
        if self.baseline_mass.is_some() {
            return Err(WorkSiteError::Path(
                "recenter cannot follow open_window: the entry paths are mutually exclusive".into(),
            ));
        }
        // Python int(round(.)) rounds half to even and // floors, also for positions off the site
        let cell = |v: f64, v0: f64| ((v - v0) / self.cell_m).round_ties_even() as i64;
        let side = i64::try_from(self.setup.tile_base_cells).unwrap_or(i64::MAX);
        let centre = (
            cell(target.1, self.world[1]).div_euclid(side),
            cell(target.0, self.world[0]).div_euclid(side),
        );
        let new_tiles: Vec<TileKey> = (centre.0 - radius_tiles..=centre.0 + radius_tiles)
            .flat_map(|tr| {
                (centre.1 - radius_tiles..=centre.1 + radius_tiles).map(move |tc| (tr, tc))
            })
            .filter(|&(tr, tc)| {
                (0..self.n_tiles.0).contains(&tr) && (0..self.n_tiles.1).contains(&tc)
            })
            .collect();
        if new_tiles.is_empty() {
            return Err(WorkSiteError::Bounds(format!(
                "recenter target {target:?} is outside the site {:?} at radius_tiles {radius_tiles}",
                self.world
            )));
        }
        self.last_rover_xy = Some(target);
        let new_set: BTreeSet<TileKey> = new_tiles.iter().copied().collect();
        if self.fine.is_some() && new_set == self.active_blocks {
            return Ok(false);
        }
        self.commit_active();
        let regions: Vec<(TileKey, [usize; 4])> = new_tiles
            .iter()
            .map(|&t| (t, self.tile_region(t)))
            .collect();
        let br0 = regions.iter().map(|r| r.1[0]).min().unwrap_or(0);
        let bc0 = regions.iter().map(|r| r.1[1]).min().unwrap_or(0);
        let br1 = regions.iter().map(|r| r.1[2]).max().unwrap_or(0);
        let bc1 = regions.iter().map(|r| r.1[3]).max().unwrap_or(0);
        let (h, w) = (br1 - br0, bc1 - bc0);
        let mut out = Fields {
            mass_areal: vec![0.0; h * w],
            density: vec![0.0; h * w],
            state_label: vec![0; h * w],
            disturbance: vec![0.0; h * w],
            datum: vec![0.0; h * w],
            ice: None,
        };
        for (t, [r0, c0, _, c1]) in regions {
            let tf = if let Some(f) = self.worked_store.get(&t) {
                f.clone()
            } else {
                let f = self.virgin_tile(t);
                self.baseline_virgin_kg += self.tile_grid_mass(&f);
                f
            };
            paste(&mut out, w, &tf, c1 - c0, (r0 - br0, c0 - bc0));
        }
        self.fine = Some(ColumnState::new(
            w,
            h,
            self.cell_m,
            out,
            0.0,
            &self.setup.regolith,
        )?);
        self.active_blocks = new_set;
        self.active_origin = Some((br0, bc0));
        self.window_region_rc = Some([br0, bc0, br1, bc1]);
        self.window_origin = Some((
            self.world[0] + bc0 as f64 * self.cell_m,
            self.world[1] + br0 as f64 * self.cell_m,
        ));
        self.recenters += 1;
        Ok(true)
    }

    /// World `(x, y)` to `(row, col)` in the current window.
    ///
    /// # Errors
    /// No open window.
    pub fn active_rc_for_xy(&self, (x, y): (f64, f64)) -> Result<(f64, f64), WorkSiteError> {
        let (ox, oy) = self
            .window_origin
            .ok_or_else(|| WorkSiteError::Path("no open window".into()))?;
        Ok(((y - oy) / self.cell_m, (x - ox) / self.cell_m))
    }

    fn active_rc_to_xy(&self, (r, c): (f64, f64)) -> Result<(f64, f64), WorkSiteError> {
        let (ox, oy) = self
            .window_origin
            .ok_or_else(|| WorkSiteError::Path("no open window".into()))?;
        Ok((ox + c * self.cell_m, oy + r * self.cell_m))
    }

    /// Cut every masked window cell above `target_m` toward it into the global ledger (a cell floors at its
    /// datum). With `relabel`, cut cells become `Excavated` and their disturbance rises by 0.4. Returns kg.
    ///
    /// # Errors
    /// No open window, or a mask of the wrong length.
    pub fn flatten(
        &mut self,
        mask: &[bool],
        target_m: f64,
        relabel: bool,
    ) -> Result<f64, WorkSiteError> {
        let cs = self.require_fine_mut()?;
        let (moved, hi) = cs.flatten_to_level(mask, target_m)?;
        let drummed = cs.drum_inventory();
        cs.set_drum_inventory(0.0);
        if relabel {
            let f = cs.fields_mut();
            for i in (0..hi.len()).filter(|&i| hi[i]) {
                f.state_label[i] = StateLabel::Excavated as u8;
                f.disturbance[i] = (f.disturbance[i] + 0.4).clamp(0.0, 1.0);
            }
        }
        self.inventory_kg += drummed;
        self.cut_total_kg += moved;
        self.note_inventory();
        Ok(moved)
    }

    /// Place up to `kg` (the whole ledger when `None`) from the global ledger evenly over the masked cells as
    /// spoil. Returns the kg placed.
    ///
    /// # Errors
    /// No open window, a mask of the wrong length, or a non-finite amount.
    pub fn dump(&mut self, mask: &[bool], kg: Option<f64>) -> Result<f64, WorkSiteError> {
        let rho_spoil = self.setup.regolith.rho_spoil;
        let inventory = self.inventory_kg;
        if kg.is_some_and(|k| !k.is_finite()) {
            return Err(WorkSiteError::Command(format!("dump amount {kg:?}")));
        }
        let cs = self.require_fine_mut()?;
        if !mask.iter().any(|&m| m) {
            return Ok(0.0);
        }
        let want = kg.unwrap_or(inventory).min(inventory).max(0.0);
        cs.set_drum_inventory(want);
        let placed = cs.dump_from_inventory(mask, want, rho_spoil);
        cs.set_drum_inventory(0.0);
        let placed = placed?;
        self.inventory_kg -= placed;
        self.placed_total_kg += placed;
        Ok(placed)
    }

    /// Relax the window to the angle of repose `theta_r` (8 neighbours, no cohesion, rest within 0.5 deg).
    /// Returns the sweeps taken.
    ///
    /// # Errors
    /// No open window, or a transfer fraction outside `(0, 1]`.
    pub fn relax(
        &mut self,
        max_steps: usize,
        theta_r: f64,
        transfer_fraction: f64,
    ) -> Result<usize, WorkSiteError> {
        let regolith = self.setup.regolith;
        let cs = self.require_fine_mut()?;
        let cfg = SandpileConfig {
            theta_r,
            eight_connected: true,
            cohesion_steepening: 0.0,
            transfer_fraction,
        };
        let mut sp = Sandpile::new(cs, cfg, regolith)?;
        Ok(sp.relax_to_rest(max_steps, None, 0.5f64.to_radians()).0)
    }

    fn command(
        &self,
        v: f64,
        omega: f64,
        dt: f64,
        payload_kg: f64,
        dig_reaction_n: f64,
    ) -> StepCommand {
        StepCommand {
            v_cmd: v,
            omega_cmd: omega,
            dt_s: dt,
            payload_kg,
            gravity_ms2: self.setup.gravity_ms2,
            dig_reaction_n,
            skid_steer: false,
        }
    }

    /// Drive the window through `twists` (`(v, omega)` pairs) from `start_rc`, laying ruts; the payload is the
    /// live ledger unless given.
    ///
    /// # Errors
    /// No open window, or a drive step outside its model.
    pub fn drive(
        &mut self,
        twists: &[(f64, f64)],
        start_rc: (f64, f64),
        start_yaw: f64,
        dt: f64,
        payload_kg: Option<f64>,
    ) -> Result<DriveRun, WorkSiteError> {
        let payload = payload_kg.unwrap_or(self.inventory_kg);
        let cmds: Vec<StepCommand> = twists
            .iter()
            .map(|&(v, w)| self.command(v, w, dt, payload, 0.0))
            .collect();
        let s = self.setup;
        let cs = self.require_fine_mut()?;
        let (mut rc, mut yaw) = (start_rc, start_yaw);
        let mut run = DriveRun {
            steps: Vec::with_capacity(cmds.len()),
            commanded_dist_m: 0.0,
            achieved_dist_m: 0.0,
            final_rc: rc,
            final_yaw: yaw,
            any_entrapped: false,
        };
        for cmd in &cmds {
            let t = drive::drive_step(
                cs,
                rc,
                yaw,
                cmd,
                &s.vehicle,
                &s.soil,
                s.material.as_ref(),
                &[],
            )?;
            run.commanded_dist_m += cmd.v_cmd.abs() * dt;
            run.achieved_dist_m += t.v_achieved.abs() * dt;
            run.any_entrapped |= t.entrapped;
            (rc, yaw) = (t.rc, t.yaw);
            run.steps.push(t);
        }
        (run.final_rc, run.final_yaw) = (rc, yaw);
        Ok(run)
    }

    /// Circumscribing radius [m] of the four-wheel footprint about the rover centre.
    fn footprint_radius_m(&self) -> f64 {
        let v = &self.setup.vehicle;
        (0.5 * v.wheelbase_m).hypot(0.5 * v.gauge_m) + 0.5 * v.wheel_width_m
    }

    /// Clamp `(x, y)` into the site box shrunk by `margin`; a site narrower than `2 margin` clamps to its centre.
    fn clamp_to_bounds(&self, (x, y): (f64, f64), margin: f64) -> ((f64, f64), bool) {
        let c = |v: f64, lo: f64, hi: f64| {
            if lo > hi {
                0.5 * (lo + hi)
            } else {
                v.max(lo).min(hi)
            }
        };
        let [x0, y0, x1, y1] = self.world;
        let (cx, cy) = (
            c(x, x0 + margin, x1 - margin),
            c(y, y0 + margin, y1 - margin),
        );
        #[allow(clippy::float_cmp)] // exactly "was it moved"
        let moved = cx != x || cy != y;
        ((cx, cy), moved)
    }

    /// Seat the drive pose at `xy`, or at the last recenter target, or at the window centre.
    ///
    /// # Errors
    /// No open window.
    #[allow(clippy::cast_precision_loss)]
    pub fn set_pose(
        &mut self,
        xy: Option<(f64, f64)>,
        yaw: f64,
    ) -> Result<(f64, f64), WorkSiteError> {
        let fine = self.require_fine()?;
        let xy = match (xy, self.last_rover_xy, self.window_origin) {
            (Some(p), _, _) | (None, Some(p), _) => p,
            (None, None, Some((ox, oy))) => (
                ox + 0.5 * fine.width() as f64 * self.cell_m,
                oy + 0.5 * fine.height() as f64 * self.cell_m,
            ),
            (None, None, None) => return Err(WorkSiteError::Path("no open window".into())),
        };
        self.pose_xy = Some(xy);
        self.yaw = yaw;
        Ok(xy)
    }

    /// Window-cell box `[r0, c0, r1, c1]` the four wheels carve at one pose.
    #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)] // clamped to the grid first
    fn dirty_bbox(&self, fine: &ColumnState, center: (f64, f64), yaw: f64) -> [usize; 4] {
        let v = &self.setup.vehicle;
        let pts = rover::wheel_contact_points(center, yaw, self.cell_m, v.gauge_m, v.wheelbase_m);
        let half_w = (0.5 * v.wheel_width_m / self.cell_m).max(0.5);
        let fold = |f: fn(f64, f64) -> f64, init: f64, i: usize| {
            pts.iter()
                .map(|p| if i == 0 { p.0 } else { p.1 })
                .fold(init, f)
        };
        let lo = |i: usize| (fold(f64::min, f64::INFINITY, i) - half_w).floor().max(0.0) as usize;
        let hi = |i: usize, n: usize| {
            ((fold(f64::max, f64::NEG_INFINITY, i) + half_w).ceil() as i64 + 1)
                .clamp(0, i64::try_from(n).unwrap_or(i64::MAX)) as usize
        };
        [lo(0), lo(1), hi(0, fine.height()), hi(1, fine.width())]
    }

    /// One conserved drive tick on the streaming window. Refuses, before any state changes, terrain that was
    /// never datum-verified, a single-window session, and a non-finite or over-limit command. Then it holds
    /// the start pose a footprint (plus one tick) inside the site, recenters, drives one
    /// [`drive::drive_step`] with the live ledger as payload, and clamps the result to the same box.
    ///
    /// # Errors
    /// [`WorkSiteError::Datum`], [`WorkSiteError::Path`] or [`WorkSiteError::Command`] with the session
    /// unchanged; a drive step outside its model.
    pub fn step(
        &mut self,
        v_cmd: f64,
        omega_cmd: f64,
        dt: f64,
        dig_reaction_n: f64,
    ) -> Result<StepReport, WorkSiteError> {
        self.require_fine()?;
        if !self.datum_verified {
            return Err(WorkSiteError::Datum(
                "step requires terrain loaded through the datum round-trip check".into(),
            ));
        }
        if self.baseline_mass.is_some() {
            return Err(WorkSiteError::Path(
                "step is streaming-only; this session was opened with open_window".into(),
            ));
        }
        let finite = [v_cmd, omega_cmd, dt, dig_reaction_n]
            .iter()
            .all(|x| x.is_finite());
        if !finite || dt <= 0.0 {
            return Err(WorkSiteError::Command(format!(
                "v {v_cmd}, omega {omega_cmd}, dt {dt}, dig {dig_reaction_n} must be finite with dt > 0"
            )));
        }
        if v_cmd.abs() > self.v_max {
            return Err(WorkSiteError::Command(format!(
                "|v| {} exceeds v_max {}",
                v_cmd.abs(),
                self.v_max
            )));
        }
        if omega_cmd.abs() > self.omega_max {
            return Err(WorkSiteError::Command(format!(
                "|omega| {} exceeds omega_max {}",
                omega_cmd.abs(),
                self.omega_max
            )));
        }
        let pose = match self.pose_xy {
            Some(p) => p,
            None => self.set_pose(None, self.yaw)?,
        };
        let margin = self.footprint_radius_m() + self.v_max.abs() * dt.abs();
        let (pose, _) = self.clamp_to_bounds(pose, margin);
        self.pose_xy = Some(pose);
        let recentered = self.recenter(pose, 1)?;
        let rc = self.active_rc_for_xy(pose)?;
        let cmd = self.command(v_cmd, omega_cmd, dt, self.inventory_kg, dig_reaction_n);
        let (yaw, s) = (self.yaw, self.setup);
        let fine = self.require_fine_mut()?;
        let t = drive::drive_step(
            fine,
            rc,
            yaw,
            &cmd,
            &s.vehicle,
            &s.soil,
            s.material.as_ref(),
            &[],
        )?;
        let dirty = self.dirty_bbox(self.require_fine()?, t.rc, t.yaw);
        let (pose_xy, bounds_clamped) = self.clamp_to_bounds(self.active_rc_to_xy(t.rc)?, margin);
        self.pose_xy = Some(pose_xy);
        self.yaw = t.yaw;
        Ok(StepReport {
            drive: t,
            bounds_clamped,
            recentered,
            pose_xy,
            window_origin: self.window_origin.unwrap_or_default(),
            dirty,
        })
    }

    /// The conserved total [kg]: the window, the ledger, and every paged-out tile not currently active.
    #[must_use]
    pub fn total_mass(&self) -> f64 {
        let mut total = self.inventory_kg + self.fine.as_ref().map_or(0.0, ColumnState::grid_mass);
        total += self
            .worked_store
            .iter()
            .filter(|(t, _)| !self.active_blocks.contains(t))
            .map(|(_, f)| self.tile_grid_mass(f))
            .sum::<f64>();
        total
    }

    /// `|total_mass - baseline|` [kg]; the streaming baseline grows with each first-visit tile.
    #[must_use]
    pub fn conservation_residual(&self) -> f64 {
        if self.baseline_virgin_kg != 0.0 {
            return (self.total_mass() - self.baseline_virgin_kg).abs();
        }
        self.baseline_mass
            .map_or(0.0, |b| (self.total_mass() - b).abs())
    }

    /// The unworked height [m] over the current streaming window.
    ///
    /// # Errors
    /// No streaming window (the single-window path has no per-tile bookkeeping).
    // shortcut: recomputed per call (cheap at the native cell); cache per window position when refined
    // windows (RW-22b) make it costly
    pub fn window_virgin_height(&self) -> Result<Vec<f64>, WorkSiteError> {
        let (Some(fine), Some((br0, bc0))) = (&self.fine, self.active_origin) else {
            return Err(WorkSiteError::Path(
                "window_virgin_height needs a streaming window (recenter)".into(),
            ));
        };
        let w = fine.width();
        let mut virgin = vec![0.0; fine.width() * fine.height()];
        for &t in &self.active_blocks {
            let [r0, c0, r1, c1] = self.tile_region(t);
            let f = self.virgin_tile(t);
            let tw = c1 - c0;
            for r in 0..r1 - r0 {
                for c in 0..tw {
                    let s = r * tw + c;
                    virgin[(r0 - br0 + r) * w + c0 - bc0 + c] =
                        f.datum[s] + f.mass_areal[s] / f.density[s];
                }
            }
        }
        Ok(virgin)
    }

    /// `height now - virgin height` [m] over the streaming window: negative where cut, positive where placed.
    ///
    /// # Errors
    /// As [`Self::window_virgin_height`].
    pub fn diff_field(&self) -> Result<Vec<f64>, WorkSiteError> {
        let virgin = self.window_virgin_height()?;
        let now = self.require_fine()?.derive_height();
        Ok(now.iter().zip(&virgin).map(|(a, b)| a - b).collect())
    }
}
