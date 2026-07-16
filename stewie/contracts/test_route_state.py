"""[REQ:FS-25] Product mode + runnable profile in the route/state model -- the BACKEND contract.

The cockpit route/state model must carry the PRD product mode (GIS-PLAN/TRAIN/SIM-OPERATE/EVALUATE/OPERATE)
and the runnable profile (desktop_sil/.../monte_carlo) as first-class routeable/persisted/shareable fields
(review finding 4). The frontend (frontend/src/workspace.ts) declares this vocabulary; this proves the BACKEND
is its authoritative source of truth -- a typed, strict, versioned route/state contract that validates the
mode+profile at the boundary, round-trips them (persisted/shareable), and CANNOT drift from the frontend
route/state model. Distinct from the EG-01 EnvironmentMode authority axis (governance.py) and the RT-01
runtime-profile REGISTRY (runtime_profiles.py): this is the route/state VOCABULARY the cockpit routes on.

Run: <venv>/bin/python -m pytest stewie/contracts/test_route_state.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from stewie.contracts import route_state as RS

_ROOT = Path(__file__).resolve().parents[2]
_WORKSPACE_TS = _ROOT / "frontend" / "src" / "workspace.ts"


def _ts_string_array(src: str, name: str) -> list[str]:
    """Extract the string-literal members of a `const NAME ... = [ ... ];` array in workspace.ts."""
    m = re.search(rf"{name}\b[^=]*=\s*\[(.*?)\]", src, re.DOTALL)
    assert m, f"{name} array not found in workspace.ts"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_backend_enumerates_the_five_product_modes_and_eight_runnable_profiles():  # [REQ:FS-25]
    assert RS.PRODUCT_MODES == ("GIS-PLAN", "TRAIN", "SIM-OPERATE", "EVALUATE", "OPERATE")
    assert RS.RUNNABLE_PROFILES == (
        "desktop_sil", "digital_twin", "ros2_replay", "hil_jetson",
        "sensor_bench", "rover_bench", "field_traverse", "monte_carlo",
    )


def test_route_state_default_is_the_planning_default_and_versioned():  # [REQ:FS-25]
    rs = RS.RouteState()
    # matches frontend/src/workspace.ts defaultWorkspace (productMode "GIS-PLAN", runnableProfile "desktop_sil")
    assert rs.product_mode == "GIS-PLAN" and rs.runnable_profile == "desktop_sil"
    assert rs.schema_version  # version-stamped for migratability (spine contract)


def test_every_mode_and_profile_constructs():  # [REQ:FS-25]
    for mode in RS.PRODUCT_MODES:
        assert RS.RouteState(product_mode=mode, runnable_profile="desktop_sil").product_mode == mode
    for prof in RS.RUNNABLE_PROFILES:
        assert RS.RouteState(product_mode="GIS-PLAN", runnable_profile=prof).runnable_profile == prof


def test_unknown_mode_or_profile_is_rejected_at_the_boundary():  # [REQ:FS-25]
    with pytest.raises(ValidationError):
        RS.RouteState(product_mode="banana", runnable_profile="desktop_sil")
    with pytest.raises(ValidationError):
        RS.RouteState(product_mode="GIS-PLAN", runnable_profile="warp_drive")
    # a SIM-OPERATE-style typo (lowercase) is not silently accepted -- fail-closed vocabulary
    with pytest.raises(ValidationError):
        RS.RouteState(product_mode="sim-operate", runnable_profile="desktop_sil")


def test_strict_rejects_unknown_fields():  # [REQ:FS-25]
    with pytest.raises(ValidationError):  # extra='forbid' -> boundary validation, no smuggled fields
        RS.RouteState.model_validate(
            {"product_mode": "GIS-PLAN", "runnable_profile": "desktop_sil", "rogue": 1})


def test_route_state_round_trips_persisted_and_shareable():  # [REQ:FS-25]
    # "a shared link restores mode+profile": the route/state serializes and reloads with the SAME mode+profile.
    rs = RS.RouteState(product_mode="SIM-OPERATE", runnable_profile="ros2_replay")
    restored = RS.RouteState.model_validate(rs.model_dump())
    assert restored == rs
    assert restored.product_mode == "SIM-OPERATE" and restored.runnable_profile == "ros2_replay"


def test_validate_route_state_helper_is_fail_closed():  # [REQ:FS-25]
    assert RS.validate_route_state("EVALUATE", "monte_carlo") == ("EVALUATE", "monte_carlo")
    with pytest.raises(ValueError):
        RS.validate_route_state("EVALUATE", "nope")
    with pytest.raises(ValueError):
        RS.validate_route_state("nope", "monte_carlo")


def test_backend_is_the_source_of_truth_frontend_route_state_cannot_drift():  # [REQ:FS-25]
    # The frontend route/state model (workspace.ts) must mirror the backend vocabulary EXACTLY, so the
    # mode/profile fields are backend-anchored, not a unilateral frontend declaration that can diverge.
    src = _WORKSPACE_TS.read_text(encoding="utf-8")
    assert list(RS.PRODUCT_MODES) == _ts_string_array(src, "PRODUCT_MODES"), "product-mode vocabulary drifted"
    assert list(RS.RUNNABLE_PROFILES) == _ts_string_array(src, "RUNNABLE_PROFILES"), "profile vocabulary drifted"
