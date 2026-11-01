//! The Rust STEWIE server (RW-55). This slice (RW-55a1) is the identity core: [`auth`] (session tokens,
//! revocation, roles, trusted-proxy identity) over [`operators`] (the account store); RW-55a2a adds [`services`]
//! (the audit ledger, revocation health, the rate limiter). Time and randomness enter
//! through [`Clock`] and [`Entropy`], so the oracle replays the Python's scenario with the same clock and bytes.

pub mod admin;
pub mod app;
pub mod auth;
pub mod construction;
pub mod operators;
pub mod planning;
pub mod services;
pub mod state;
pub mod twin;
pub mod validate;
pub mod world;
pub mod world_routes;

/// Wall-clock seconds since the Unix epoch.
pub trait Clock: Send + Sync {
    fn now(&self) -> f64;
}

/// Cryptographic randomness.
pub trait Entropy: Send + Sync {
    fn fill(&self, buf: &mut [u8]);
}

/// The system clock.
#[derive(Debug, Clone, Copy, Default)]
pub struct SystemClock;

impl Clock for SystemClock {
    fn now(&self) -> f64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0.0, |d| d.as_secs_f64())
    }
}

/// The operating system's CSPRNG.
#[derive(Debug, Clone, Copy, Default)]
pub struct OsEntropy;

impl Entropy for OsEntropy {
    fn fill(&self, buf: &mut [u8]) {
        // a host without an entropy source cannot mint credentials safely: stop rather than weaken them
        getrandom::fill(buf).expect("the OS entropy source is unavailable");
    }
}

/// Write a file atomically (temp, sync, rename), as the Python's `atomic_write_bytes`.
///
/// # Errors
/// An I/O failure, in words.
pub fn atomic_write(path: &std::path::Path, bytes: &[u8]) -> Result<(), String> {
    stewie_twin::write_atomic(path, bytes).map_err(|e| format!("{}: {e:?}", path.display()))
}
