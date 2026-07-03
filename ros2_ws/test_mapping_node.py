"""[REQ:AS-10] the live mapping node maintains the OBSERVED world model as separate per-layer arrays,
updated only from perception (provenance 'observed'), with simulator truth structurally denied. The pure
MappingCore is host-testable (rclpy-optional); the live subscription is exercised in the ROS2 container."""
import importlib.util
import os

import numpy as np
import pytest

_NODE = os.path.join(os.path.dirname(__file__), "src", "stewie_mapping", "stewie_mapping", "node.py")


def _mod():
    spec = importlib.util.spec_from_file_location("stewie_mapping_node", _NODE)
    assert spec and spec.loader, f"cannot load {_NODE}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mapping_core_maintains_separate_observed_layers_denying_truth():  # [REQ:AS-10]
    mod = _mod()
    core = mod.MappingCore(4, 4)
    # the AS-10 semantic layers are each a SEPARATE backing array (not one shared grid).
    assert {"dem", "occupancy", "rock", "uncertainty", "changed", "excavation"} <= set(mod.SEMANTIC_LAYERS)
    assert core.layer("dem") is not core.layer("occupancy")
    # ingesting a perception observation updates ONLY that layer, tagged with the perception source.
    n = core.ingest_observation("occupancy", np.ones((4, 4)), source="stereo_mapper")
    assert n == 16 and core.provenance("occupancy") == "stereo_mapper"
    assert core.layer("dem").sum() == 0.0                 # other layers untouched -> genuinely separate
    assert core.coverage_frac("occupancy") == 1.0 and core.observed_count == 1
    # a masked write folds in only the observed cells, leaving the rest.
    m = np.zeros((4, 4), dtype=bool)
    m[0, 0] = True
    core.ingest_observation("rock", np.full((4, 4), 5.0), mask=m, source="perception:rocks")
    assert core.layer("rock")[0, 0] == 5.0 and core.layer("rock")[3, 3] == 0.0
    # simulator TRUTH is structurally denied: the mapper has NO truth/authority write path.
    assert core.truth_denied is True
    assert not hasattr(core, "set_truth") and not hasattr(core, "set_authority")


def test_mapping_core_rejects_unknown_layer_and_bad_shape():  # [REQ:AS-10]
    core = _mod().MappingCore(4, 4)
    with pytest.raises(KeyError):
        core.ingest_observation("truth", np.ones((4, 4)))   # 'truth' is not a mapper layer -- refused
    with pytest.raises(ValueError):
        core.ingest_observation("dem", np.ones((3, 3)))     # shape mismatch refused, not silently resized
