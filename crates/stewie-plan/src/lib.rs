//! The LODE build planner (RW-33): takes a mission (build orders on a map), balances cut against fill, plans the
//! trips and recharges, sequences them, and emits the executable plan IR. Ported node by node from
//! `lode/planner_*.py` against Python oracles (D-R85).

pub mod acceptance;
pub mod assemble;
pub mod balance;
pub mod endurance;
pub mod fleet;
pub mod ir;
pub mod mission;
pub mod optimize;
pub mod provenance;
pub mod release;
pub mod report;
pub mod sim;
pub mod trips;
