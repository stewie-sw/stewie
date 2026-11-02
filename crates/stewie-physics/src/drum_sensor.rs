//! [REQ:PX-14] Drum-fill sensing (Python `stewie.physics.rassor_mass_model`): the free-spinning drum-motor current a
//! drum carrying a mass draws (the FDC linear structure, NTRS 20210022781 Fig 8; its baseline and slope are CALIB
//! values the caller passes from `deploy/planner.json`), a least-squares inverse calibrated on synthesised fills,
//! the realistic relative error of that estimate, and the offload decision on its upper bound.

/// The paper's low-error drum fill [kg]: more than about half full (above 20 kg).
pub const HALF_FULL_KG: f64 = 20.0;

/// The published error bands of a motor-current mass estimate (`plan_report.json`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ErrorBands {
    /// Over the range, without the two outlier cycles (7.40%).
    pub mpe_all: f64,
    /// Above half full (2.56%).
    pub mpe_half_full: f64,
}

/// The relative error of an estimate at `mass_kg` (Python `drum_mass_uncertainty_frac`): the half-full band above
/// [`HALF_FULL_KG`], else a continuous blend from the over-range band, so the upper bound is monotone in the fill.
#[must_use]
pub fn uncertainty_frac(mass_kg: f64, bands: ErrorBands) -> f64 {
    if mass_kg >= HALF_FULL_KG {
        return bands.mpe_half_full;
    }
    let f = mass_kg.max(0.0) / HALF_FULL_KG;
    bands.mpe_all + f * (bands.mpe_half_full - bands.mpe_all)
}

/// `mass = slope * feature + intercept` (Python `LinearMassModel`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct LinearMassModel {
    pub slope: f64,
    pub intercept: f64,
}

impl LinearMassModel {
    /// The least-squares fit of paired features and masses (Python `LinearMassModel.fit`, its sums in order).
    ///
    /// # Errors
    /// Fewer than two pairs, unequal lengths, or constant features.
    #[allow(clippy::cast_precision_loss)] // a handful of samples
    pub fn fit(features: &[f64], masses: &[f64]) -> Result<Self, String> {
        let n = features.len();
        if n < 2 || n != masses.len() {
            return Err("need >= 2 paired (feature, mass) samples of equal length".to_owned());
        }
        let sum = |it: &mut dyn Iterator<Item = f64>| it.fold(0.0, |a, x| a + x);
        let mx = sum(&mut features.iter().copied()) / n as f64;
        let my = sum(&mut masses.iter().copied()) / n as f64;
        let sxx = sum(&mut features.iter().map(|x| (x - mx).powi(2)));
        if sxx == 0.0 {
            return Err("features are constant; cannot fit a slope".to_owned());
        }
        let sxy = sum(&mut features
            .iter()
            .zip(masses)
            .map(|(x, y)| (x - mx) * (y - my)));
        let slope = sxy / sxx;
        Ok(Self {
            slope,
            intercept: my - slope * mx,
        })
    }

    #[must_use]
    pub fn predict(&self, feature: f64) -> f64 {
        self.slope * feature + self.intercept
    }
}

/// A noise-free drum sensor (Python `DrumSensor` with `noise_frac == 0`, at 1 g).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct DrumSensor {
    pub model: LinearMassModel,
    pub baseline_a: f64,
    pub slope_a_per_kg: f64,
    pub capacity_kg: f64,
    pub bands: ErrorBands,
}

/// The offload decision on the upper confidence bound (Python `should_offload`, conservative).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Offload {
    pub offload: bool,
    pub uncertainty_frac: f64,
    pub lower_kg: f64,
    pub upper_kg: f64,
}

impl DrumSensor {
    /// The sensor whose inverse is fitted on the currents the forward model gives at `masses` (Python
    /// `DrumSensor.calibrated`).
    ///
    /// # Errors
    /// A negative mass, or masses the fit refuses.
    pub fn calibrated(
        masses: &[f64],
        baseline_a: f64,
        slope_a_per_kg: f64,
        capacity_kg: f64,
        bands: ErrorBands,
    ) -> Result<Self, String> {
        let currents = masses
            .iter()
            .map(|&m| current_a(m, baseline_a, slope_a_per_kg))
            .collect::<Result<Vec<_>, _>>()?;
        Ok(Self {
            model: LinearMassModel::fit(&currents, masses)?,
            baseline_a,
            slope_a_per_kg,
            capacity_kg,
            bands,
        })
    }

    /// The current a true drum mass draws.
    ///
    /// # Errors
    /// A negative mass.
    pub fn current(&self, true_mass_kg: f64) -> Result<f64, String> {
        current_a(true_mass_kg, self.baseline_a, self.slope_a_per_kg)
    }

    /// The mass inferred from a current.
    #[must_use]
    pub fn infer(&self, current_a: f64) -> f64 {
        self.model.predict(current_a)
    }

    /// The offload decision on this sensor's capacity.
    #[must_use]
    pub fn offload(&self, inferred_kg: f64) -> Offload {
        let unc = uncertainty_frac(inferred_kg, self.bands);
        let (lower_kg, upper_kg) = (inferred_kg * (1.0 - unc), inferred_kg * (1.0 + unc));
        Offload {
            offload: upper_kg >= self.capacity_kg,
            uncertainty_frac: unc,
            lower_kg,
            upper_kg,
        }
    }
}

/// The free-spinning current `baseline + slope * mass` at 1 g (Python `freespin_drum_current_a`).
///
/// # Errors
/// A negative mass.
pub fn current_a(mass_kg: f64, baseline_a: f64, slope_a_per_kg: f64) -> Result<f64, String> {
    if mass_kg < 0.0 {
        return Err("mass_kg must be >= 0".to_owned());
    }
    Ok(baseline_a + slope_a_per_kg * mass_kg)
}
