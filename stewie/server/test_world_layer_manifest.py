"""[REQ:FR-10] Unified typed layer manifest world contract. /world carries a per-layer manifest -- each of
the DEM/material/traversability/observed/uncertainty/hazard layers + the costmap planning layers is
discoverable + typed with consumer eligibility (display/planning/release/execute) -- and the planner's
costmap layers are ALL planning-eligible in the manifest, so the planner builds its costmap from the SAME
manifest the cockpit reads. Extends TW-05 (WorldState) + AS-11 (lode.costmap_layers)."""
import os

from lode.costmap_layers import LAYER_NAMES
from stewie.contracts import LayerManifest, WorldLayer, WorldState

_SRV = os.path.dirname(os.path.abspath(__file__))


def _world():
    return WorldState(body="moon", frame="MOON_ME", rows=120, cols=120, cell_m=5.0, observed_fraction=0.3)


def test_named_layers_are_discoverable_and_typed_with_eligibility():  # [REQ:FR-10]
    m = LayerManifest.for_world(_world(), transaction_id="txn-1")
    ids = m.layer_ids()
    for req in ("dem", "material", "traversability", "observed_mask", "uncertainty", "hazard"):
        assert req in ids, f"{req} layer not discoverable in the manifest"
    for lyr in m.layers:
        assert isinstance(lyr, WorldLayer)
        assert lyr.layer_type and lyr.crs == "MOON_ME" and lyr.resolution_m == 5.0
        assert isinstance(lyr.display, bool) and isinstance(lyr.planning, bool)   # typed consumer eligibility


def test_planner_costmap_layers_are_all_planning_eligible():  # [REQ:FR-10]
    m = LayerManifest.for_world(_world(), transaction_id="txn")
    planning = set(m.planning_layers())
    # the planner builds its costmap from these -> every costmap layer must be planning-eligible here.
    assert set(LAYER_NAMES) <= planning, "the planner's costmap layers are not all planning-eligible"


def test_planner_builds_the_costmap_from_the_manifest():  # [REQ:FR-10]
    import numpy as np

    from lode.costmap_layers import CostmapContext, compose_from_manifest
    m = LayerManifest.for_world(_world(), transaction_id="txn")
    cm = compose_from_manifest(CostmapContext(np.zeros((8, 8))), m)
    # the planner composed EXACTLY the manifest's planning cost layers (== its LAYER_NAMES) -- one source of truth.
    assert set(cm.per_layer_cost) == set(LAYER_NAMES), "the planner did not build from the manifest's layers"
    assert cm.cost.shape == (8, 8) and cm.passable.shape == (8, 8)


def test_eligibility_and_provenance_are_per_layer_not_uniform():  # [REQ:FR-10]
    m = LayerManifest.for_world(_world(), transaction_id="txn")   # observed_fraction 0.3 -> observed
    by = {lyr.layer_id: lyr for lyr in m.layers}
    assert by["dem"].provenance == "observed" and by["dem"].release is True
    assert by["hazard"].execute is True                          # hazard is execute-eligible
    assert by["imagery"].planning is False                       # imagery is display-only, not planning
    assert by["uncertainty"].uncertainty_model == "observed-band"


def test_world_router_builds_and_carries_the_manifest():  # [REQ:FR-10]
    src = open(os.path.join(_SRV, "routers", "world.py"), encoding="utf-8").read()
    assert "LayerManifest" in src, "world.py does not build the LayerManifest"
    assert "layer_manifest" in src, "the /world response does not carry the manifest"
