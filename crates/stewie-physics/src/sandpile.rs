//! Angle-of-repose relaxation over a [`ColumnState`] (Python `stewie.physics.sandpile`).
//!
//! Each sweep finds every loose donor whose downhill slope to a neighbour exceeds the threshold
//! (repose plus optional cohesion steepening), sheds one under-relaxed outflow budget split among its
//! over-repose neighbours by excess, and moves that **mass** (at the donor's density) to the receivers.
//! Every gram removed from a donor lands in exactly one receiver, so grid mass is invariant. The receiver's
//! density is re-mixed by volume; a receiver may be any in-bounds cell (loose spoil can spread onto a firm
//! floor), but only loose donors move, and only while they hold more than one median grain (D-R52).

use crate::PhysicsError;
use crate::column::{ColumnState, Regolith, StateLabel};

const N4: [(isize, isize); 4] = [(-1, 0), (1, 0), (0, -1), (0, 1)];
const N8: [(isize, isize); 8] = [
    (-1, 0),
    (1, 0),
    (0, -1),
    (0, 1),
    (-1, -1),
    (-1, 1),
    (1, -1),
    (1, 1),
];

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SandpileConfig {
    /// Critical repose angle [rad] (the body registry's `repose_deg`).
    pub theta_r: f64,
    /// 4 or 8 neighbours.
    pub eight_connected: bool,
    /// Extra angle [rad] a pile may hold before failing (metastability).
    pub cohesion_steepening: f64,
    /// Under-relaxation in `(0, 1]`; damps oscillation, never affects conservation.
    pub transfer_fraction: f64,
}

#[derive(Debug)]
pub struct Sandpile<'a> {
    cs: &'a mut ColumnState,
    cfg: SandpileConfig,
    regolith: Regolith,
}

impl<'a> Sandpile<'a> {
    /// # Errors
    /// A transfer fraction outside `(0, 1]` or a non-finite angle.
    pub fn new(
        cs: &'a mut ColumnState,
        cfg: SandpileConfig,
        regolith: Regolith,
    ) -> Result<Self, PhysicsError> {
        let valid = cfg.transfer_fraction > 0.0
            && cfg.transfer_fraction <= 1.0
            && cfg.theta_r.is_finite()
            && cfg.cohesion_steepening.is_finite();
        if !valid {
            return Err(PhysicsError::InvalidInput(format!("{cfg:?}")));
        }
        Ok(Self { cs, cfg, regolith })
    }

    fn neighbours(&self) -> &'static [(isize, isize)] {
        if self.cfg.eight_connected { &N8 } else { &N4 }
    }

    /// The in-bounds neighbour of cell `i` in direction `(dr, dc)`.
    #[allow(clippy::cast_possible_wrap, clippy::cast_sign_loss)] // grid sizes are far below isize::MAX
    fn neighbour(&self, cell: usize, (dr, dc): (isize, isize)) -> Option<usize> {
        let (cols, rows) = (self.cs.width() as isize, self.cs.height() as isize);
        let (row, col) = ((cell as isize) / cols + dr, (cell as isize) % cols + dc);
        (row >= 0 && row < rows && col >= 0 && col < cols).then(|| (row * cols + col) as usize)
    }

    fn run(&self, (dr, dc): (isize, isize)) -> f64 {
        if dr != 0 && dc != 0 {
            std::f64::consts::SQRT_2 * self.cs.cell_m()
        } else {
            self.cs.cell_m()
        }
    }

    /// Add `mass_kg` from outside the grid as loose spoil at `(r, c)`, or over a disc of `radius_cells`
    /// (clipped to the grid). Grid mass rises by `mass_kg`; a closed budget should come from the drum.
    ///
    /// # Errors
    /// A negative or non-finite mass, a bad spoil density, or a centre or disc wholly off the grid.
    #[allow(
        clippy::cast_possible_wrap,
        clippy::cast_sign_loss,
        clippy::cast_precision_loss
    )]
    pub fn deposit(
        &mut self,
        r: isize,
        c: isize,
        mass_kg: f64,
        radius_cells: isize,
        spoil_density: f64,
    ) -> Result<(), PhysicsError> {
        let valid = mass_kg.is_finite()
            && mass_kg >= 0.0
            && spoil_density.is_finite()
            && spoil_density > 0.0;
        if !valid {
            return Err(PhysicsError::InvalidInput(format!(
                "deposit {mass_kg} kg at {spoil_density}"
            )));
        }
        let (w, h) = (self.cs.width() as isize, self.cs.height() as isize);
        let inside = |rr: isize, cc: isize| rr >= 0 && rr < h && cc >= 0 && cc < w;
        let mut cells = Vec::new();
        if radius_cells <= 0 {
            if inside(r, c) {
                cells.push((r * w + c) as usize);
            }
        } else {
            for dr in -radius_cells..=radius_cells {
                for dc in -radius_cells..=radius_cells {
                    if dr * dr + dc * dc <= radius_cells * radius_cells && inside(r + dr, c + dc) {
                        cells.push(((r + dr) * w + c + dc) as usize);
                    }
                }
            }
        }
        if cells.is_empty() {
            return Err(PhysicsError::InvalidInput(format!(
                "deposit at ({r},{c}) is off the grid"
            )));
        }
        let add = mass_kg / cells.len() as f64 / self.cs.cell_area();
        for i in cells {
            self.cs.add_spoil_external(i, add, spoil_density);
        }
        Ok(())
    }

    /// Loose cells holding more than one median grain of column: the only cells that can shed mass or keep
    /// the pile from rest. A drained cell over bedrock steeper than repose would otherwise never settle.
    fn donor_mask(&self) -> Vec<bool> {
        let f = self.cs.fields();
        let mut m = self.cs.loose_mask(&self.regolith);
        for (i, d) in m.iter_mut().enumerate() {
            *d &= f.mass_areal[i] / f.density[i] > self.regolith.d50_m;
        }
        m
    }

    /// Largest downhill angle [rad] from a donor to any in-bounds neighbour.
    fn max_loose_slope(&self) -> f64 {
        let h = self.cs.derive_height();
        let loose = self.donor_mask();
        let mut max = 0.0f64;
        for &d in self.neighbours() {
            let run = self.run(d);
            for i in (0..h.len()).filter(|&i| loose[i]) {
                if let Some(j) = self.neighbour(i, d) {
                    max = max.max((h[i] - h[j]).max(0.0).atan2(run));
                }
            }
        }
        max
    }

    /// One stabilising sweep; true if any mass moved.
    #[allow(clippy::cast_precision_loss)]
    pub fn relax_step(&mut self) -> bool {
        let tan_thr = (self.cfg.theta_r + self.cfg.cohesion_steepening).tan();
        let h = self.cs.derive_height();
        let loose = self.donor_mask();
        let dirs = self.neighbours();
        let n = h.len();
        // Pass A: per direction, the loose donor's height above the repose plane toward that neighbour
        let mut excess = vec![vec![0.0; n]; dirs.len()];
        let mut total = vec![0.0; n];
        let mut moved = false;
        for (k, &d) in dirs.iter().enumerate() {
            let run = self.run(d);
            for i in (0..n).filter(|&i| loose[i]) {
                if let Some(j) = self.neighbour(i, d) {
                    let e = (h[i] - h[j]) - run * tan_thr;
                    if e > 0.0 {
                        excess[k][i] = e;
                        total[i] += e;
                        moved = true;
                    }
                }
            }
        }
        if !moved {
            return false;
        }
        // Pass B: one under-relaxed budget per donor (half the mean excess), capped by its column
        let f = self.cs.fields();
        let tf = self.cfg.transfer_fraction;
        let budget: Vec<f64> = (0..n)
            .map(|i| {
                let active = excess.iter().filter(|e| e[i] > 0.0).count();
                let mean = if active > 0 {
                    total[i] / active as f64
                } else {
                    0.0
                };
                (tf * 0.5 * mean).min(tf * f.mass_areal[i] / f.density[i])
            })
            .collect();
        let mut delta = vec![0.0; n];
        let (mut out_m, mut in_m, mut in_v) = (vec![0.0; n], vec![0.0; n], vec![0.0; n]);
        for (k, &d) in dirs.iter().enumerate() {
            for i in (0..n).filter(|&i| excess[k][i] > 0.0) {
                let move_h = budget[i] * (excess[k][i] / total[i]);
                let dm = move_h * f.density[i];
                // excess is recorded only toward in-bounds neighbours
                let Some(j) = self.neighbour(i, d) else {
                    continue;
                };
                delta[i] -= dm;
                out_m[i] += dm;
                delta[j] += dm;
                in_m[j] += dm;
                in_v[j] += move_h;
            }
        }
        self.cs.apply_relaxation(&delta, &out_m, &in_m, &in_v);
        true
    }

    /// Sweep until no mass moves or every loose slope is within `eps_angle` of the threshold, at most
    /// `max_steps` times. Returns the steps taken and, if `capture_every` is given, height snapshots (the
    /// first before any step, one every `capture_every` steps, and the final state if it differs).
    pub fn relax_to_rest(
        &mut self,
        max_steps: usize,
        capture_every: Option<usize>,
        eps_angle: f64,
    ) -> (usize, Vec<Vec<f64>>) {
        let mut snaps = Vec::new();
        if capture_every.is_some() {
            snaps.push(self.cs.derive_height());
        }
        let rest = self.cfg.theta_r + self.cfg.cohesion_steepening + eps_angle;
        let mut steps = 0;
        for i in 0..max_steps {
            let moved = self.relax_step();
            steps += 1;
            if capture_every.is_some_and(|e| i % e.max(1) == 0) {
                snaps.push(self.cs.derive_height());
            }
            if !moved || self.max_loose_slope() <= rest {
                break;
            }
        }
        if capture_every.is_some() && snaps.last() != Some(&self.cs.derive_height()) {
            snaps.push(self.cs.derive_height());
        }
        (steps, snaps)
    }
}

impl ColumnState {
    /// Sandpile deposit of external mass at cell `i` as spoil (no disturbance change, as in Python).
    pub(crate) fn add_spoil_external(&mut self, i: usize, add: f64, spoil_density: f64) {
        let f = self.fields_mut();
        let old = f.mass_areal[i];
        let denom = old / f.density[i] + add / spoil_density;
        f.density[i] = if denom > 0.0 {
            (old + add) / denom
        } else {
            spoil_density
        };
        f.mass_areal[i] = old + add;
        f.state_label[i] = StateLabel::Spoil as u8;
    }

    /// Apply one sandpile sweep: mass deltas, then the volume-conserving density mix at every receiver.
    pub(crate) fn apply_relaxation(
        &mut self,
        delta: &[f64],
        out_m: &[f64],
        in_m: &[f64],
        in_v: &[f64],
    ) {
        let f = self.fields_mut();
        for i in 0..delta.len() {
            let old = f.mass_areal[i];
            f.mass_areal[i] = (old + delta[i]).max(0.0);
            if in_m[i] > 0.0 {
                let kept_m = old - out_m[i];
                let new_v = kept_m / f.density[i] + in_v[i];
                if new_v > 1e-12 {
                    f.density[i] = (kept_m + in_m[i]) / new_v;
                }
            }
        }
    }
}
