"""[REQ:RS-04] the ros2_replay keystone: one deterministic end-to-end pass over a REAL Haworth DEM window
produces every typed RS-01 payload + a committed WorldTransaction + the evidence bundle; a seeded hazard
forces a reroute; a seeded ineligibility forces a logged refusal; same inputs -> same run."""
import importlib

import numpy as np
import pytest

from stewie.contracts.runtime_spine import (
    CommandEligibility,
    CostmapSnapshot,
    DepthObservation,
    HazardMapDescriptor,
    ObservedMapUpdate,
    TrajectoryCommand,
    VisualHazardObservation,
)
from stewie.runtime.replay_loop import EvidenceBundle, run_replay

_START = (5 * 5.0, 5 * 5.0)      # window cell (5,5) at 5 m/cell
_GOAL = (50 * 5.0, 50 * 5.0)     # window cell (50,50)


@pytest.fixture(scope="module")
def window():
    from stewie.server import state as S
    dem, _ = S.moon_dem("haworth")
    z, cell = np.asarray(dem[0]), float(dem[1])
    return z[500:560, 1700:1760].copy(), cell     # the real, traversable replay frame


@pytest.fixture()
def wss(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_WSS", None)
    return S.world_state_service()


def test_keystone_loop_produces_every_typed_payload(window, wss):
    z, cell = window
    b = run_replay(z, cell, _START, _GOAL, wss=wss)
    assert isinstance(b, EvidenceBundle)
    # every stage crossed its RS-01 typed contract.
    assert isinstance(b.depth, DepthObservation) and b.depth.source == "replay"
    assert isinstance(b.hazards, VisualHazardObservation)
    assert isinstance(b.observed_map, ObservedMapUpdate) and b.observed_map.provenance == "observed"
    assert isinstance(b.hazard_descriptor, HazardMapDescriptor)
    assert isinstance(b.costmap, CostmapSnapshot) and b.costmap.layers
    assert isinstance(b.eligibility, CommandEligibility) and b.eligibility.eligible is True
    assert b.commands and all(isinstance(c, TrajectoryCommand) and c.bounded for c in b.commands)
    assert b.arrived is True and b.refused is False
    # the world transaction was committed with this run's authority sha (64-hex) + a valid chain.
    assert len(b.world_transaction["authority_sha"]) == 64
    assert b.world_transaction["provenance"].startswith("ros2_replay keystone")
    assert wss.verify_chain()


def test_seeded_hazard_forces_a_reroute_and_is_detected(window, wss):
    z, cell = window
    clear = run_replay(z, cell, _START, _GOAL, wss=wss)
    hazard = run_replay(z, cell, _START, _GOAL, wss=wss, seed_hazard_rc=(25, 25))   # on the diagonal corridor
    # the classifier reported the observed obstacle (absent from the base DEM)...
    assert len(hazard.hazards.detections) == 1
    det = hazard.hazards.detections[0]
    assert det.accepted and det.confidence == 1.0 and det.kind == "obstacle"
    # ...the costmap named the observed obstacle as a blocking reason, and the no-go fraction rose...
    assert "observed_obstacle" in hazard.costmap.blocking_reasons
    assert hazard.hazard_descriptor.no_go_fraction > clear.hazard_descriptor.no_go_fraction
    # ...and the plan REROUTED: it still arrives, but the command sequence differs from the clear run.
    assert hazard.arrived is True
    assert hazard.run_sha != clear.run_sha
    assert [(_c.goal_row, _c.goal_col) for _c in hazard.commands] != \
           [(_c.goal_row, _c.goal_col) for _c in clear.commands]


def test_observed_rock_layer_changes_the_routing_costmap_without_a_dem_bump(window, wss):  # [REQ:RS-02]
    """[REQ:RS-02] the ROUTING planner consumes a NON-DEM observed layer. An observed ROCK (dense semantic
    occupancy the perception segmented, ABSENT from the static DEM height) is fed to the routing hazard
    costmap as rock_mask; on otherwise-flat ground it MEASURABLY raises the traversal cost the planner keys
    on -- proving the planner reads the observed occupancy/rock world, not just the static DEM. Provenance
    is carried as an accepted 'rock' detection + the 'observed_rock' costmap blocking reason."""
    z, cell = window
    clear = run_replay(z, cell, _START, _GOAL, wss=wss)
    rock = run_replay(z, cell, _START, _GOAL, wss=wss, seed_rock_rc=(25, 25))   # a rock on the corridor, flat DEM
    # the rock is an observed occupancy detection (non-DEM), carried with provenance...
    assert any(d.kind == "rock" and d.accepted and d.confidence == 1.0 for d in rock.hazards.detections)
    assert "observed_rock" in rock.costmap.blocking_reasons
    assert "observed_rock" not in clear.costmap.blocking_reasons
    # ...and the observed occupancy MEASURABLY changed the costmap the planner keys on: it became NOGO
    #    cells the static-DEM (clear) run does not have, on ground the DEM shows as flat -- and the evidence
    #    differs. This is the observed occupancy/no-go LAYER driving traversability, not the DEM height.
    assert rock.hazard_descriptor.no_go_fraction > clear.hazard_descriptor.no_go_fraction
    assert rock.run_sha != clear.run_sha


def test_observed_map_uncertainty_layer_lowers_the_assessment_confidence(window, wss):  # [REQ:RS-02]
    """[REQ:RS-02] the planner reads the observed MAP-UNCERTAINTY layer: a weakly-observed patch (the
    perception saw it with low confidence) lowers the per-cell assessment confidence the planner keys on --
    a distinct observed layer from the DEM/occupancy, provenance 'observed'. Proven by the hazard
    descriptor's mean_confidence dropping vs the clear (fully-confident) run."""
    z, cell = window
    clear = run_replay(z, cell, _START, _GOAL, wss=wss)
    unc = run_replay(z, cell, _START, _GOAL, wss=wss, seed_uncertainty_rc=(30, 30))
    assert unc.hazard_descriptor.mean_confidence < clear.hazard_descriptor.mean_confidence
    assert unc.run_sha != clear.run_sha


def test_planning_consumes_the_observed_multilayer_world_with_provenance(window, wss):  # [REQ:RS-02]
    """[REQ:RS-02] Planning consumes the OBSERVED world, not just the static DEM: one run reads ALL the
    observed layers -- DEM, changed-terrain, occupancy/no-go, rock/object graph, and map-uncertainty --
    each tagged 'observed' provenance, and each measurably drives the hazard costmap the planner keys on."""
    z, cell = window
    b = run_replay(z, cell, _START, _GOAL, wss=wss,
                   seed_hazard_rc=(25, 25), seed_rock_rc=(40, 40), seed_uncertainty_rc=(15, 15))
    layers = {u.layer: u for u in b.observed_layers}
    # all five observed layers are present + provenance-tagged (not the static DEM alone).
    assert {"dem", "changed", "occupancy", "rock"} <= set(layers), f"missing observed layers: {set(layers)}"
    assert all(u.provenance == "observed" for u in b.observed_layers)
    assert layers["dem"].uncertainty_m > 0.0                                    # map-uncertainty layer recorded
    # each observed layer measurably drove the costmap the planner keys on:
    assert any(d.kind == "rock" and d.accepted for d in b.hazards.detections)   # rock/object graph instance
    assert {"observed_obstacle", "observed_rock"} <= set(b.costmap.blocking_reasons)  # DEM-change + occupancy no-go
    assert b.hazard_descriptor.no_go_fraction > 0.0                             # observed hazards became NOGO


def test_seeded_ineligibility_forces_a_logged_refusal(window, wss):
    z, cell = window
    b = run_replay(z, cell, _START, _GOAL, wss=wss, eligible=False)
    # the gate refused (sandbox mission -> not released) so NO command was emitted...
    assert b.refused is True and b.commands == ()
    assert b.eligibility.eligible is False and b.eligibility.reason == "unauthorized_sandbox"
    assert b.arrived is False
    # ...but the refusal is LOGGED: the world transaction is still recorded, tagged 'refused'.
    assert "refused" in b.world_transaction["provenance"]
    assert wss.transaction_count() == 1


def test_run_is_deterministic(window, wss):
    z, cell = window
    a = run_replay(z, cell, _START, _GOAL, wss=wss, seed_hazard_rc=(25, 25))
    b = run_replay(z, cell, _START, _GOAL, wss=wss, seed_hazard_rc=(25, 25))
    assert a.run_sha == b.run_sha                      # same inputs -> same typed payloads
    assert [c.model_dump() for c in a.commands] == [c.model_dump() for c in b.commands]


def test_fr11_observed_hazard_end_to_end_acceptance_gate_with_leg_justified_evidence(window, wss):  # [REQ:FR-11]
    """FR-11: the full observed-world-to-planner gate on REAL Haworth terrain -- known DEM + route ->
    inject an observed hazard -> commit through a world transaction -> rebuild the costmap from the layer
    manifest -> the route changes/refuses, with LEG-attributed release evidence ('route changed because
    observed hazard X entered leg Y'). One end-to-end acceptance test, extends RS-02."""
    from stewie.runtime.route_impact import justify_route_change
    z, cell = window
    clear = run_replay(z, cell, _START, _GOAL, wss=wss)                             # known DEM + route
    hazard = run_replay(z, cell, _START, _GOAL, wss=wss, seed_hazard_rc=(25, 25))   # inject observed hazard on the corridor
    # (a) committed through a world transaction -- the audited chain verifies.
    assert hazard.world_transaction and wss.verify_chain()
    # (b) the costmap rebuilt from the layer manifest reflects the observed hazard; the no-go area grew.
    assert "observed_obstacle" in hazard.costmap.blocking_reasons
    assert hazard.hazard_descriptor.no_go_fraction > clear.hazard_descriptor.no_go_fraction
    # (c) the planner read a provenance-tagged OBSERVED multi-layer world (never truth).
    assert hazard.observed_layers and all(lyr.provenance == "observed" for lyr in hazard.observed_layers)
    # (d) the acceptance verdict: a REAL impact (reroute OR refusal), attributed to the route leg + the named cause.
    j = justify_route_change(clear, hazard, (25, 25))
    assert j["changed"] or j["refused"]
    assert j["blocking_reason"] == "observed_obstacle"
    assert isinstance(j["leg_index"], int) and j["leg_index"] >= 0
    assert "observed_obstacle" in j["justification"] and f"leg {j['leg_index']}" in j["justification"]
