"""[REQ:RS-01] the runtime spine's hard contracts: every perception->mapping->localization->planning->
control->UI boundary carries ONE typed payload, and a raw / wrong-shape dict is REJECTED at the seam
(no module passes an ad-hoc dict across a stage boundary). These tests pin both halves -- a valid payload
validates, and an unknown-field / out-of-domain / missing-field dict raises -- for every spine stage."""
import dataclasses

import pytest
from pydantic import ValidationError

from stewie.contracts import BeliefState
from stewie.contracts.runtime_spine import (
    RUNTIME_SPINE,
    HazardDetection,
    LocalizationState,
    TrajectoryCommand,
    validate_boundary,
)

# one VALID minimal payload per new Contract stage.
_VALID = {
    "DepthObservation": {"t_s": 1.0, "source": "stereo", "point_count": 4096, "range_max_m": 12.0},
    "VisualHazardObservation": {"t_s": 1.0, "detections": [
        {"kind": "rock", "confidence": 0.8, "accepted": True, "reason": "size>gate", "size_m": 0.4}]},
    "ObservedMapUpdate": {"t_s": 1.0, "layer": "dem", "rows": 64, "cols": 64, "cell_m": 0.05,
                          "provenance": "observed", "coverage_fraction": 0.3},
    "HazardMap": {"rows": 64, "cols": 64, "cell_m": 0.05, "no_go_fraction": 0.1, "max_cost": 3.0},
    "CostmapSnapshot": {"t_s": 1.0, "rows": 64, "cols": 64, "cell_m": 0.05,
                        "layers": ["slope", "rock"], "blocking_reasons": ["tip_risk"], "max_cost": 9.0},
    "TrajectoryCommand": {"leg_id": 0, "kind": "goto", "goal_row": 10.0, "goal_col": 8.0, "v_max_mps": 0.3},
    "CommandEligibility": {"eligible": False, "reason": "stale_link", "sensor_fresh": False},
}
# a WRONG payload per stage: unknown field, out-of-domain value, or missing required field.
_WRONG = {
    "DepthObservation": {"t_s": 1.0, "bogus_field": 1},                      # unknown field (extra=forbid)
    "VisualHazardObservation": {"t_s": 1.0, "detections": [
        {"kind": "rock", "confidence": 5.0, "accepted": True}]},             # confidence > 1 (out of domain)
    "ObservedMapUpdate": {"t_s": 1.0, "layer": "teleport", "rows": 64, "cols": 64, "cell_m": 0.05},  # bad layer
    "HazardMap": {"rows": 0, "cols": 64, "cell_m": 0.05},                    # rows must be > 0
    "CostmapSnapshot": {"t_s": 1.0, "rows": 64, "cols": 64},                 # missing required cell_m
    "TrajectoryCommand": {"leg_id": 0, "kind": "warp", "goal_row": 1, "goal_col": 1, "v_max_mps": 0.3},  # bad kind
    "CommandEligibility": {"reason": "x"},                                   # missing required `eligible`
}


@pytest.mark.parametrize("stage", list(_VALID))
def test_each_boundary_validates_a_good_payload(stage):
    obj = validate_boundary(stage, _VALID[stage])
    assert isinstance(obj, RUNTIME_SPINE[stage])
    assert obj.schema_version  # version-stamped


@pytest.mark.parametrize("stage", list(_WRONG))
def test_each_boundary_rejects_a_raw_or_wrong_shape_dict(stage):
    # the core RS-01 guarantee: an ad-hoc / wrong-shape dict cannot cross the seam.
    with pytest.raises(ValidationError):
        validate_boundary(stage, _WRONG[stage])


def test_the_registry_covers_all_nine_spine_stages():
    assert list(RUNTIME_SPINE) == [
        "DepthObservation", "VisualHazardObservation", "ObservedMapUpdate", "HazardMap",
        "LocalizationState", "CostmapSnapshot", "TrajectoryCommand", "CommandEligibility",
        "WorldTransaction"]


def test_localization_state_is_the_existing_belief_contract_not_a_parallel_type():
    # RS-01 reuses the FS-02 spine: there is ONE localization contract (BeliefState), not two.
    assert LocalizationState is BeliefState
    assert RUNTIME_SPINE["LocalizationState"] is BeliefState


def test_world_transaction_stage_is_the_existing_envelope_type():
    from stewie.twin.envelope import WorldTransaction
    assert RUNTIME_SPINE["WorldTransaction"] is WorldTransaction
    # it is the canonical world-log record -- a frozen dataclass, not a re-invented schema.
    assert dataclasses.is_dataclass(WorldTransaction)


def test_contracts_are_frozen_immutable_snapshots():
    cmd = TrajectoryCommand(leg_id=0, goal_row=1.0, goal_col=2.0, v_max_mps=0.3)
    with pytest.raises(ValidationError):
        cmd.v_max_mps = 0.9  # frozen -> a boundary payload cannot be mutated after it crosses


def test_validate_boundary_rejects_an_unknown_stage():
    with pytest.raises(KeyError):
        validate_boundary("NotAStage", {})


def test_nested_detection_contract_bounds_confidence():
    with pytest.raises(ValidationError):
        HazardDetection(kind="rock", confidence=1.5, accepted=True)  # confidence in [0,1]
