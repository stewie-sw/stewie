//! The LODE build planner (RW-33): takes a mission (build orders on a map), balances cut against fill, plans the
//! trips and recharges, sequences them, and emits the executable plan IR. Ported node by node from
//! `lode/planner_*.py` against Python oracles (D-R85).

pub mod balance;
pub mod mission;
pub mod sim;
pub mod trips;
