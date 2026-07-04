"""[REQ:BA-06] Interop conversion between STEWIE's internal formats and the ROS/Godot/GIS ecosystem
(model / terrain / grid / bag round-trips, extending FR-12). Each converter is round-trip-tested on a real
fixture with the invariant its acceptance names preserved (georeference, bounds, or event count). The pure-data
converters (grid/terrain) are here; the ROS-bag + xacro converters are container-gated (rosbag2 / xacro)."""
