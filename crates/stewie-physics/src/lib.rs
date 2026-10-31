//! STEWIE's single physics authority (RW-20).
//!
//! [`soil`] builds one parameter set per body from the sourced registry; [`terra`] is Bekker
//! pressure-sinkage, Janosi-Hanamoto shear and the slip-sinkage equilibrium; [`bearing`] is the
//! Terzaghi/Vesic shallow-foundation capacity. Every function is a port of the Python implementation it
//! replaces and is checked against that oracle to 1e-9 relative.

pub mod bearing;
pub mod column;
pub mod soil;
pub mod terra;

use std::fmt;

#[derive(Debug, Clone, PartialEq)]
pub enum PhysicsError {
    UnknownBody(String),
    /// The gravity-loaded Bekker model does not apply to a microgravity body; refused unless the caller
    /// asks for the flagged lunar analog.
    OutOfRegime {
        body: String,
        g: f64,
    },
    InvalidInput(String),
}

impl fmt::Display for PhysicsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            PhysicsError::UnknownBody(b) => write!(f, "unknown body {b:?}"),
            PhysicsError::OutOfRegime { body, g } => write!(
                f,
                "{body}: the gravity-loaded Bekker model is out of regime at g={g:.1e} m/s^2"
            ),
            PhysicsError::InvalidInput(m) => write!(f, "invalid input: {m}"),
        }
    }
}

impl std::error::Error for PhysicsError {}
