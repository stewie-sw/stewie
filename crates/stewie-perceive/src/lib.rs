//! Rover state estimation (RW-40): one pose-graph core with typed factors. RW-40a is the SE(2) graph the live
//! perception, resync and SLAM-seam paths use (Python `dart.pose_graph_se2`).

pub mod localize;
pub mod pose_graph_se2;
pub mod slam_seam;
