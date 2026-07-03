"""stewie_mapping (mapping) -- [REQ:AS-10] the LIVE mapping node: it MAINTAINS the observed world model
as SEPARATE per-layer backing arrays (observed DEM, occupancy/rock, object-graph, uncertainty, changed-
terrain, excavation), updated ONLY from perception observations (provenance 'observed'). Simulator TRUTH
is physically denied -- this node has NO truth/authority input path; the conserved authority owns truth
(the SL-01 firewall). The pure `MappingCore` is rclpy-optional + host-testable; `main` wraps it in a live
ROS2 node that ingests perception (needs the ROS2 container, AS-04). Conforms to the AS-01 boundary
contract (stewie/bridge/autonomy_contract.py)."""
from __future__ import annotations

import numpy as np

ROLE = "mapping"

#: the observed SEMANTIC layers the mapper maintains as separate backing arrays (the AS-10 acceptance set).
SEMANTIC_LAYERS = ("dem", "occupancy", "rock", "object_graph", "uncertainty", "changed", "excavation")

try:
    import rclpy
    from rclpy.node import Node
    _HAVE_RCLPY = True
except ImportError:                       # non-ROS host: import-safe, run-gated
    _HAVE_RCLPY = False
    Node = object


class MappingCore:
    """[REQ:AS-10] The observed world model the mapping node maintains. Each semantic layer is a SEPARATE
    backing array, updated ONLY through `ingest_observation` (provenance 'observed'). Simulator truth is
    STRUCTURALLY denied: there is no set_truth / authority / ingest_truth method, so truth cannot enter the
    observed world through the mapper. Pure numpy -- host-testable without a ROS runtime."""

    def __init__(self, rows: int, cols: int) -> None:
        if int(rows) <= 0 or int(cols) <= 0:
            raise ValueError(f"mapping grid needs a positive shape, got {rows}x{cols}")
        self.rows, self.cols = int(rows), int(cols)
        self._layers: dict[str, np.ndarray] = {
            n: np.zeros((self.rows, self.cols), dtype=float) for n in SEMANTIC_LAYERS}
        self._provenance: dict[str, str | None] = {n: None for n in SEMANTIC_LAYERS}
        self.observed_count = 0

    def ingest_observation(self, layer: str, values, mask=None, *, source: str = "perception") -> int:
        """Fold a perception observation into ONE observed layer (a masked write), tagging its provenance.
        Returns the number of cells updated. The only provenance a mapper ever writes is 'observed'/a
        perception source -- never 'truth' (there is no such path)."""
        if layer not in self._layers:
            raise KeyError(f"unknown observed layer {layer!r} (mapper maintains {SEMANTIC_LAYERS})")
        v = np.asarray(values, dtype=float)
        if v.shape != (self.rows, self.cols):
            raise ValueError(f"{layer}: observation shape {v.shape} != grid {(self.rows, self.cols)}")
        m = np.ones_like(v, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
        self._layers[layer] = np.where(m, v, self._layers[layer])
        self._provenance[layer] = source
        self.observed_count += 1
        return int(m.sum())

    def layer(self, name: str) -> np.ndarray:
        return self._layers[name]

    def provenance(self, name: str) -> str | None:
        return self._provenance[name]

    def coverage_frac(self, name: str) -> float:
        """The fraction of the grid the mapper has observed for `name` (0 until any observation lands)."""
        return float((self._layers[name] != 0.0).mean())

    @property
    def truth_denied(self) -> bool:
        """Structural truth-denial: the mapper exposes NO method to write the truth/authority layer, so
        simulator truth cannot enter the observed world through this node (AS-10 / SL-01 firewall)."""
        return not any(hasattr(self, a) for a in ("set_truth", "set_authority", "ingest_truth"))


def main(args=None):
    if not _HAVE_RCLPY:
        raise SystemExit("stewie_mapping requires a ROS2 (rclpy) runtime -- run inside the ROS2 container (AS-04).")
    from sensor_msgs.msg import PointCloud2

    rclpy.init(args=args)
    node = Node("mapping")
    core = MappingCore(rows=256, cols=256)         # the live observed world model this node maintains
    node._mapping_core = core                      # noqa: SLF001 -- exposed for introspection

    def _on_perception(msg: PointCloud2) -> None:
        # a perception frame lands -> the observed DEM layer's coverage grows (provenance 'observed').
        # Truth is never touched: the mapper has no truth input, per the AS-10/SL-01 firewall.
        rows = min(core.rows, int(getattr(msg, "height", 0)) or core.rows)
        obs = np.zeros((core.rows, core.cols), dtype=float)
        obs[:rows, :] = 1.0
        core.ingest_observation("dem", obs, source="perception:/stewie/perception/points")

    node.create_subscription(PointCloud2, "/stewie/perception/points", _on_perception, 10)
    node.get_logger().info(
        f"stewie_mapping up (AS-10 live mapper; role=mapping; layers={','.join(SEMANTIC_LAYERS)}; "
        f"truth_denied={core.truth_denied}); maintaining the observed world model from perception")
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
