//! Per-cell regolith strength from the conserved density field (Python `stewie.physics.material`).
//!
//! Friction and cohesion interpolate linearly in relative density `Dr = (rho - rho_surface) /
//! (rho_deep - rho_surface)`, clamped to `[0, 1]`, between a loose endpoint (the body's sourced surface
//! values) and the dense endpoint (spec section 5.2, in the soil baseline). Compacted berms come out strong
//! and loose spoil weak, from the real density, not a fabricated map.

use stewie_contracts::soil_baseline::SoilBaseline;

use crate::soil::SoilParams;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct MaterialModel {
    pub rho_surface: f64,
    pub rho_deep: f64,
    pub phi_loose_deg: f64,
    pub phi_dense_deg: f64,
    pub cohesion_loose_pa: f64,
    pub cohesion_dense_pa: f64,
}

/// Every per-cell material output for one density.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct CellMaterial {
    pub relative_density: f64,
    pub friction_deg: f64,
    pub cohesion_pa: f64,
    /// `c*A + N*tan(phi)` for the reference load and patch [N].
    pub traction_capacity_n: f64,
    /// 1 at the loose end, 0 at the dense end (anchored to the endpoints, not the field's range).
    pub slip_susceptibility: f64,
    /// 0 at the loose end, 1 at the dense end.
    pub cut_difficulty: f64,
}

impl MaterialModel {
    /// Loose endpoint from the body's parameter set, dense endpoint from the soil baseline.
    #[must_use]
    pub fn for_soil(p: &SoilParams, base: &SoilBaseline) -> Self {
        Self {
            rho_surface: p.rho_surface,
            rho_deep: p.rho_deep,
            phi_loose_deg: p.phi_rad.to_degrees(),
            phi_dense_deg: base.phi_dense_deg.value,
            cohesion_loose_pa: p.cohesion_pa,
            cohesion_dense_pa: base.cohesion_dense_pa.value,
        }
    }

    #[must_use]
    pub fn relative_density(&self, rho: f64) -> f64 {
        ((rho - self.rho_surface) / (self.rho_deep - self.rho_surface)).clamp(0.0, 1.0)
    }

    /// `(phi_rad, cohesion_pa)` at bulk density `rho`.
    #[must_use]
    pub fn cell_strength(&self, rho: f64) -> (f64, f64) {
        let dr = self.relative_density(rho);
        let phi = self.phi_loose_deg + dr * (self.phi_dense_deg - self.phi_loose_deg);
        let c = self.cohesion_loose_pa + dr * (self.cohesion_dense_pa - self.cohesion_loose_pa);
        (phi.to_radians(), c)
    }

    /// The full material record at `rho`, with the traction proxy for `normal_load_n` on
    /// `contact_area_m2` (these affect only the traction-derived outputs).
    #[must_use]
    pub fn cell(&self, rho: f64, normal_load_n: f64, contact_area_m2: f64) -> CellMaterial {
        let dr = self.relative_density(rho);
        let friction_deg = self.phi_loose_deg + dr * (self.phi_dense_deg - self.phi_loose_deg);
        let cohesion_pa =
            self.cohesion_loose_pa + dr * (self.cohesion_dense_pa - self.cohesion_loose_pa);
        let t =
            |c: f64, phi_deg: f64| c * contact_area_m2 + normal_load_n * phi_deg.to_radians().tan();
        let traction = t(cohesion_pa, friction_deg);
        let (lo, hi) = (
            t(self.cohesion_loose_pa, self.phi_loose_deg),
            t(self.cohesion_dense_pa, self.phi_dense_deg),
        );
        CellMaterial {
            relative_density: dr,
            friction_deg,
            cohesion_pa,
            traction_capacity_n: traction,
            slip_susceptibility: ((hi - traction) / (hi - lo).max(1e-9)).clamp(0.0, 1.0),
            cut_difficulty: ((cohesion_pa - self.cohesion_loose_pa)
                / (self.cohesion_dense_pa - self.cohesion_loose_pa))
                .clamp(0.0, 1.0),
        }
    }
}
