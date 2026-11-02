//! [REQ:EG-12] The physics-model ledger and the LIVE rule (Python `stewie.contracts.physics_model_control`): a model
//! may drive a live session only when it is validated, frozen, not deprecated, backed by a mass-conserving engine,
//! and validated for the body (a body in the gravity-loaded Bekker regime). The resolver fails closed before any
//! world is built.

use stewie_contracts::body::{BodyBekkerRegime, BodyRegistry};

/// One registered, versioned model.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PhysicsModel {
    pub model_id: &'static str,
    pub backend_id: &'static str,
    pub validated: bool,
    pub frozen: bool,
    pub deprecated: bool,
    pub calibration: &'static str,
    /// `None`: every body in the gravity-loaded Bekker regime (the Python's `_TIER2_VALIDATED_BODIES`).
    pub validated_bodies: Option<&'static [&'static str]>,
}

/// The ledger (Python `MODELS`).
pub const MODELS: [PhysicsModel; 3] = [
    PhysicsModel {
        model_id: "tier2_numpy@1.0",
        backend_id: "tier2_numpy",
        validated: true,
        frozen: true,
        deprecated: false,
        calibration: "sourced-analog",
        validated_bodies: None,
    },
    PhysicsModel {
        model_id: "tier2_numpy@0.1",
        backend_id: "tier2_numpy",
        validated: true,
        frozen: true,
        deprecated: true,
        calibration: "superseded",
        validated_bodies: Some(&["moon"]),
    },
    PhysicsModel {
        model_id: "tier3_chrono@0.0",
        backend_id: "tier2_chrono",
        validated: false,
        frozen: false,
        deprecated: false,
        calibration: "uncalibrated",
        validated_bodies: Some(&[]),
    },
];

/// The LIVE default.
pub const LIVE_DEFAULT_MODEL_ID: &str = "tier2_numpy@1.0";

/// The Python registry's declaration order (`stewie.specs.bodies.BODIES`), which its refusals list bodies in; a
/// registry body it does not name follows, sorted.
const BODY_ORDER: [&str; 7] = [
    "moon",
    "mars",
    "ceres",
    "bennu",
    "phobos",
    "earth",
    "bp1_testbed",
];

/// The bodies a model is validated for.
#[must_use]
pub fn validated_bodies(m: &PhysicsModel, reg: &BodyRegistry) -> Vec<String> {
    if let Some(b) = m.validated_bodies {
        return b.iter().map(|s| (*s).to_owned()).collect();
    }
    let mut names: Vec<&String> = reg.keys().collect();
    names.sort_by_key(|n| {
        (
            BODY_ORDER
                .iter()
                .position(|o| o == n)
                .unwrap_or(BODY_ORDER.len()),
            (*n).clone(),
        )
    });
    names
        .into_iter()
        .filter(|n| !matches!(reg[*n].bekker_regime, BodyBekkerRegime::Microgravity))
        .cloned()
        .collect()
}

/// Python repr of a str.
fn q(s: &str) -> String {
    format!("'{s}'")
}

/// The backend a LIVE session may mutate with (Python `resolve_live_backend`): the model's `backend_id`, or the
/// refusal, in the Python's words.
///
/// # Errors
/// An unknown model, or one the LIVE rule refuses.
pub fn resolve_live_backend(
    model_id: Option<&str>,
    body: Option<&str>,
    reg: &BodyRegistry,
) -> Result<&'static str, String> {
    let id = model_id.unwrap_or(LIVE_DEFAULT_MODEL_ID);
    let Some(m) = MODELS.iter().find(|m| m.model_id == id) else {
        let mut ids: Vec<&str> = MODELS.iter().map(|m| m.model_id).collect();
        ids.sort_unstable();
        let ids: Vec<String> = ids.iter().map(|s| q(s)).collect();
        return Err(format!(
            "unknown physics model {}; registered: [{}]",
            q(id),
            ids.join(", ")
        ));
    };
    if !m.validated {
        return Err(format!(
            "model {} is unvalidated (calibration {}) -- cannot be selected for LIVE",
            q(m.model_id),
            q(m.calibration)
        ));
    }
    if m.deprecated {
        return Err(format!(
            "model {} is deprecated -- cannot be selected for LIVE",
            q(m.model_id)
        ));
    }
    if !m.frozen {
        return Err(format!(
            "model {} is not frozen -- cannot be selected for LIVE",
            q(m.model_id)
        ));
    }
    // the one registered engine, and it conserves mass (Python `Tier2NumpyBackend`: authority_class "conserved")
    if m.backend_id != "tier2_numpy" {
        return Err(format!("backend {} is not implemented", q(m.backend_id)));
    }
    if let Some(b) = body {
        let ok = validated_bodies(m, reg);
        if !ok.iter().any(|x| x == b) {
            let list: Vec<String> = ok.iter().map(|s| q(s)).collect();
            return Err(format!(
                "model {} has no validated LIVE profile for body {} (validated for [{}])",
                q(m.model_id),
                q(b),
                list.join(", ")
            ));
        }
    }
    Ok(m.backend_id)
}
