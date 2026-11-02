//! The viz2 pixel-stream service (RW-51d; Python `stewie.stream`), a binary of its own beside `stewie-server`.
//!
//! [REQ:RT-07] It runs under the `godot_sim` runtime profile: bounded command of the simulated rover only. That is
//! structural here, as the Python's AST guard made it there: this crate links no rover-command, plan-lowering,
//! plugin-host or ROS crate, which `tests/rt06_no_egress.rs` checks over `cargo metadata`.

pub mod app;
pub mod framing;
pub mod previews;
pub mod protocol;
pub mod py;
pub mod security;

/// The runtime profile the service runs under (RT-01).
pub const RUNTIME_PROFILE: &str = "godot_sim";
