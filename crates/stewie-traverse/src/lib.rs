//! Terrain-aware traverse planning (Python `lode.planner_routing`): a slope costmap where steeper ground
//! costs more per metre (`1 + alpha * tan(slope)`) and ground past the slope cap, or overlooking a
//! drop-off, is impassable; keep-out shapes; an 8-connected least-cost route that never cuts a corner
//! between two blocked cells; and route legs that widen their search window until a corridor is found
//! or the whole DEM has been searched. Optional illumination and map-uncertainty layers add soft cost,
//! each kept as its own inspectable term, and never change passability.

pub mod costmap;
pub mod route;
