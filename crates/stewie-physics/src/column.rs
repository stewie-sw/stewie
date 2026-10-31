//! Per-column regolith state (Python `stewie.physics.column_state`): the conserved quantity is areal mass
//! [kg/m^2]; height is always derived, `datum + mass_areal / density`, never stored. Cutting into the
//! drum and dumping or depositing from it move mass between the grid and the drum inventory, so
//! [`ColumnState::total_mass`] is invariant across every operation here. Dumped material lands at loose
//! spoil density, so the same mass stands taller than the cut it came from (bulking).
//!
//! Grids are row-major, `width` columns by `height` rows. Masks are one `bool` per cell.

use stewie_contracts::soil_baseline::SoilBaseline;

use crate::PhysicsError;

/// Discrete terrain class over the continuous state (Python `StateLabel`; codes are the contract's).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum StateLabel {
    Virgin = 0,
    Tread = 1,
    Excavated = 2,
    Spoil = 3,
    CompactedBerm = 4,
    Sintered = 5,
}

/// The regolith density ladder and limits a column state needs, from the body and the soil baseline.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Regolith {
    pub rho_surface: f64,
    pub rho_deep: f64,
    pub rho_grain: f64,
    pub rho_spoil: f64,
    pub rho_sintered: f64,
    /// Thickness of the default loose layer [m].
    pub z_t_m: f64,
    /// Median grain size [m]: a sandpile donor must hold more than this (D-R52).
    pub d50_m: f64,
    pub w_ice_max: f64,
}

impl Regolith {
    /// `rho_surface` is the body's (see [`crate::soil::SoilParams`]); the rest is the soil baseline.
    #[must_use]
    pub fn new(rho_surface: f64, base: &SoilBaseline) -> Self {
        Self {
            rho_surface,
            rho_deep: base.rho_deep.value,
            rho_grain: base.rho_grain.value,
            rho_spoil: base.rho_spoil.value,
            rho_sintered: base.rho_sintered.value,
            z_t_m: base.z_t_m.value,
            d50_m: base.d50_m.value,
            w_ice_max: base.w_ice_max.value,
        }
    }
}

/// Every field of a column state, for construction from a bundle.
#[derive(Debug, Clone, PartialEq)]
pub struct Fields {
    pub mass_areal: Vec<f64>,
    pub density: Vec<f64>,
    pub state_label: Vec<u8>,
    pub disturbance: Vec<f64>,
    pub datum: Vec<f64>,
    pub ice: Option<Vec<f64>>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ColumnState {
    width: usize,
    height: usize,
    cell_m: f64,
    f: Fields,
    drum_inventory: f64,
}

fn bad(m: impl Into<String>) -> PhysicsError {
    PhysicsError::InvalidInput(m.into())
}

fn finite_nonneg(name: &str, v: &[f64]) -> Result<(), PhysicsError> {
    if v.iter().all(|x| x.is_finite() && *x >= 0.0) {
        Ok(())
    } else {
        Err(bad(format!("{name} must be finite and >= 0")))
    }
}

impl ColumnState {
    /// A uniform loose layer `z_t_m` thick at surface density on a zero datum (Python's default).
    ///
    /// # Errors
    /// An empty grid or a non-positive cell size.
    pub fn uniform(
        width: usize,
        height: usize,
        cell_m: f64,
        r: &Regolith,
    ) -> Result<Self, PhysicsError> {
        let n = width * height;
        Self::new(
            width,
            height,
            cell_m,
            Fields {
                mass_areal: vec![r.rho_surface * r.z_t_m; n],
                density: vec![r.rho_surface; n],
                state_label: vec![StateLabel::Virgin as u8; n],
                disturbance: vec![0.0; n],
                datum: vec![0.0; n],
                ice: None,
            },
            0.0,
            r,
        )
    }

    /// A state from explicit fields, each checked against its whole physical domain: mass >= 0, density in
    /// `(0, rho_grain]`, disturbance in `[0, 1]`, datum finite, label a [`StateLabel`] code, ice in
    /// `[0, w_ice_max]`, drum inventory >= 0.
    ///
    /// # Errors
    /// The first field outside its domain or of the wrong length.
    pub fn new(
        width: usize,
        height: usize,
        cell_m: f64,
        f: Fields,
        drum_inventory: f64,
        r: &Regolith,
    ) -> Result<Self, PhysicsError> {
        if width == 0 || height == 0 || !(cell_m.is_finite() && cell_m > 0.0) {
            return Err(bad(format!("grid {width}x{height} at {cell_m} m")));
        }
        let n = width * height;
        let lens = [
            f.mass_areal.len(),
            f.density.len(),
            f.state_label.len(),
            f.disturbance.len(),
            f.datum.len(),
            f.ice.as_ref().map_or(n, Vec::len),
        ];
        if lens.iter().any(|&l| l != n) {
            return Err(bad(format!("field lengths {lens:?} != {n} cells")));
        }
        finite_nonneg("mass_areal", &f.mass_areal)?;
        if !f
            .density
            .iter()
            .all(|d| d.is_finite() && *d > 0.0 && *d <= r.rho_grain)
        {
            return Err(bad(format!("density must be in (0, {}]", r.rho_grain)));
        }
        if !f.disturbance.iter().all(|d| (0.0..=1.0).contains(d)) {
            return Err(bad("disturbance must be in [0, 1]"));
        }
        if !f.datum.iter().all(|d| d.is_finite()) {
            return Err(bad("datum must be finite"));
        }
        if f.state_label
            .iter()
            .any(|&l| l > StateLabel::Sintered as u8)
        {
            return Err(bad("state_label code outside StateLabel"));
        }
        if let Some(ice) = &f.ice
            && !ice.iter().all(|w| (0.0..=r.w_ice_max).contains(w))
        {
            return Err(bad(format!("ice must be in [0, {}]", r.w_ice_max)));
        }
        finite_nonneg("drum_inventory", &[drum_inventory])?;
        Ok(Self {
            width,
            height,
            cell_m,
            f,
            drum_inventory,
        })
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

    #[must_use]
    pub fn fields(&self) -> &Fields {
        &self.f
    }

    /// Crate-internal mutation for operations whose conservation is proven in their own module.
    pub(crate) fn fields_mut(&mut self) -> &mut Fields {
        &mut self.f
    }

    #[must_use]
    pub fn drum_inventory(&self) -> f64 {
        self.drum_inventory
    }

    #[must_use]
    pub fn cell_area(&self) -> f64 {
        self.cell_m * self.cell_m
    }

    /// Surface height [m] of every cell: `datum + mass_areal / density`.
    #[must_use]
    pub fn derive_height(&self) -> Vec<f64> {
        (0..self.f.datum.len())
            .map(|i| self.f.datum[i] + self.f.mass_areal[i] / self.f.density[i])
            .collect()
    }

    /// Loose-column thickness [m] above the datum.
    #[must_use]
    pub fn thickness(&self) -> Vec<f64> {
        self.f
            .mass_areal
            .iter()
            .zip(&self.f.density)
            .map(|(m, d)| m / d)
            .collect()
    }

    /// Mass on the grid [kg].
    #[must_use]
    pub fn grid_mass(&self) -> f64 {
        self.f.mass_areal.iter().sum::<f64>() * self.cell_area()
    }

    /// The conserved total [kg]: grid plus drum.
    #[must_use]
    pub fn total_mass(&self) -> f64 {
        self.grid_mass() + self.drum_inventory
    }

    /// Runtime guard on the conserved-state invariants: mass finite and >= 0, density finite and > 0,
    /// derived height finite, drum inventory >= 0.
    ///
    /// # Errors
    /// The first violated invariant.
    pub fn check_invariants(&self) -> Result<(), PhysicsError> {
        finite_nonneg("mass_areal", &self.f.mass_areal)?;
        if !self.f.density.iter().all(|d| d.is_finite() && *d > 0.0) {
            return Err(bad("density must be finite and > 0"));
        }
        if !self.derive_height().iter().all(|h| h.is_finite()) {
            return Err(bad("derived height is not finite"));
        }
        finite_nonneg("drum_inventory", &[self.drum_inventory])
    }

    fn check_len(&self, what: &str, len: usize) -> Result<(), PhysicsError> {
        if len == self.f.mass_areal.len() {
            Ok(())
        } else {
            Err(bad(format!(
                "{what} has {len} cells, grid has {}",
                self.f.mass_areal.len()
            )))
        }
    }

    /// Back a desired surface out to the conserved mass field at the current density and datum.
    ///
    /// # Errors
    /// A target of the wrong length or not finite.
    pub fn set_height_via_mass(&mut self, target: &[f64]) -> Result<(), PhysicsError> {
        self.check_len("target", target.len())?;
        if !target.iter().all(|t| t.is_finite()) {
            return Err(bad("target height must be finite"));
        }
        for (i, t) in target.iter().enumerate() {
            self.f.mass_areal[i] = (t - self.f.datum[i]).max(0.0) * self.f.density[i];
        }
        Ok(())
    }

    /// Move up to `mass_per_cell` [kg/m^2] from each masked cell into the drum (never below zero).
    /// Returns the kg moved.
    ///
    /// # Errors
    /// A mask or field of the wrong length, or a negative or non-finite amount.
    pub fn cut_to_inventory(
        &mut self,
        mask: &[bool],
        mass_per_cell: &[f64],
    ) -> Result<f64, PhysicsError> {
        self.check_len("mask", mask.len())?;
        self.check_len("mass_per_cell", mass_per_cell.len())?;
        finite_nonneg("mass_per_cell", mass_per_cell)?;
        let mut moved = 0.0;
        for i in (0..mask.len()).filter(|&i| mask[i]) {
            let m = self.f.mass_areal[i].min(mass_per_cell[i]);
            self.f.mass_areal[i] -= m;
            moved += m;
        }
        let kg = moved * self.cell_area();
        self.drum_inventory += kg;
        Ok(kg)
    }

    /// Spoil placed on masked cells: mass added, density mixed by volume, label `Spoil`, disturbance up.
    fn place_spoil(&mut self, i: usize, add: f64, spoil_density: f64) {
        let old = self.f.mass_areal[i];
        let mixed = (old + add) / (old / self.f.density[i] + add / spoil_density);
        self.f.mass_areal[i] = old + add;
        self.f.density[i] = if mixed.is_finite() {
            mixed
        } else {
            spoil_density
        };
        self.f.state_label[i] = StateLabel::Spoil as u8;
        self.f.disturbance[i] = (self.f.disturbance[i] + 0.3).clamp(0.0, 1.0);
    }

    fn check_spoil(spoil_density: f64) -> Result<(), PhysicsError> {
        if spoil_density.is_finite() && spoil_density > 0.0 {
            Ok(())
        } else {
            Err(bad("spoil density must be finite and > 0"))
        }
    }

    /// Spread up to `total_kg` from the drum evenly over the masked cells as spoil. Returns the kg placed
    /// (limited by the drum).
    ///
    /// # Errors
    /// A mask of the wrong length, a negative or non-finite amount, or a bad spoil density.
    #[allow(clippy::cast_precision_loss)] // cell counts are far below 2^52
    pub fn dump_from_inventory(
        &mut self,
        mask: &[bool],
        total_kg: f64,
        spoil_density: f64,
    ) -> Result<f64, PhysicsError> {
        self.check_len("mask", mask.len())?;
        finite_nonneg("total_kg", &[total_kg])?;
        Self::check_spoil(spoil_density)?;
        let n = mask.iter().filter(|&&m| m).count();
        if n == 0 {
            return Ok(0.0);
        }
        let place = total_kg.min(self.drum_inventory);
        let per_cell = (place / n as f64) / self.cell_area();
        for i in (0..mask.len()).filter(|&i| mask[i]) {
            self.place_spoil(i, per_cell, spoil_density);
        }
        self.drum_inventory -= place;
        Ok(place)
    }

    /// Deposit a per-cell areal mass field [kg/m^2] from the drum as spoil, scaled down to the drum's
    /// inventory if it asks for more, so a fill never overshoots. Negative entries count as zero. Returns
    /// the kg placed.
    ///
    /// # Errors
    /// A mask or field of the wrong length, a non-finite field, or a bad spoil density.
    pub fn deposit_field(
        &mut self,
        mask: &[bool],
        mass_per_cell: &[f64],
        spoil_density: f64,
    ) -> Result<f64, PhysicsError> {
        self.check_len("mask", mask.len())?;
        self.check_len("mass_per_cell", mass_per_cell.len())?;
        if !mass_per_cell.iter().all(|m| m.is_finite()) {
            return Err(bad("mass_per_cell must be finite"));
        }
        Self::check_spoil(spoil_density)?;
        let mut field: Vec<f64> = (0..mask.len())
            .map(|i| {
                if mask[i] {
                    mass_per_cell[i].max(0.0)
                } else {
                    0.0
                }
            })
            .collect();
        let mut want = field.iter().sum::<f64>() * self.cell_area();
        if want <= 0.0 || self.drum_inventory <= 0.0 {
            return Ok(0.0);
        }
        if want > self.drum_inventory {
            let s = self.drum_inventory / want;
            for v in &mut field {
                *v *= s;
            }
            want = self.drum_inventory;
        }
        for (i, &add) in field.iter().enumerate() {
            if add > 0.0 {
                self.place_spoil(i, add, spoil_density);
            }
        }
        self.drum_inventory -= want;
        Ok(want)
    }

    /// Raise masked cells toward `target` (never above it), each by at most `max_lift_m` if given, from the
    /// drum. Returns the kg placed.
    ///
    /// # Errors
    /// As [`ColumnState::deposit_field`].
    pub fn fill_toward(
        &mut self,
        mask: &[bool],
        target: &[f64],
        max_lift_m: Option<f64>,
        spoil_density: f64,
    ) -> Result<f64, PhysicsError> {
        self.check_len("target", target.len())?;
        let h = self.derive_height();
        let deficit: Vec<f64> = (0..h.len())
            .map(|i| {
                let d = (target[i] - h[i]).max(0.0);
                max_lift_m.map_or(d, |m| d.min(m)) * spoil_density
            })
            .collect();
        self.deposit_field(mask, &deficit, spoil_density)
    }

    /// Fuse masked cells into a sintered crust: density up to at least `sintered_density`, mass unchanged
    /// (the column thins), label `Sintered`, disturbance cleared. Returns the kg fused.
    ///
    /// # Errors
    /// A mask of the wrong length.
    pub fn sinter(&mut self, mask: &[bool], sintered_density: f64) -> Result<f64, PhysicsError> {
        self.check_len("mask", mask.len())?;
        let mut kg = 0.0;
        for i in (0..mask.len()).filter(|&i| mask[i]) {
            kg += self.f.mass_areal[i];
            self.f.density[i] = self.f.density[i].max(sintered_density);
            self.f.state_label[i] = StateLabel::Sintered as u8;
            self.f.disturbance[i] = 0.0;
        }
        Ok(kg * self.cell_area())
    }

    /// Cut masked cells above `target_m` toward it, into the drum; a cell floors at its datum. Returns the
    /// kg moved and the cells cut (Python `worksite.flatten_to_level`).
    ///
    /// # Errors
    /// A mask of the wrong length.
    pub fn flatten_to_level(
        &mut self,
        mask: &[bool],
        target_m: f64,
    ) -> Result<(f64, Vec<bool>), PhysicsError> {
        self.check_len("mask", mask.len())?;
        let h = self.derive_height();
        let hi: Vec<bool> = (0..h.len()).map(|i| mask[i] && h[i] > target_m).collect();
        let per: Vec<f64> = (0..h.len())
            .map(|i| ((h[i] - target_m) * self.f.density[i]).max(0.0))
            .collect();
        let moved = self.cut_to_inventory(&hi, &per)?;
        Ok((moved, hi))
    }

    /// Cells eligible for sandpile relaxation: not tread or berm, below the mid density, and not cemented
    /// by ice above half the ceiling.
    #[must_use]
    pub fn loose_mask(&self, r: &Regolith) -> Vec<bool> {
        let mid = 0.5 * (r.rho_surface + r.rho_deep);
        (0..self.f.density.len())
            .map(|i| {
                let l = self.f.state_label[i];
                let paved = l == StateLabel::Tread as u8 || l == StateLabel::CompactedBerm as u8;
                let cemented = self
                    .f
                    .ice
                    .as_ref()
                    .is_some_and(|w| w[i] > 0.5 * r.w_ice_max);
                !paved && self.f.density[i] < mid && !cemented
            })
            .collect()
    }
}
