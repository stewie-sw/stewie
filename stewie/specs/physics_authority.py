"""[REQ:PH-01] the physics backend AUTHORITY registry — the PRD2 physics spine. Every cost/risk/volume value
must name which backend produced it, and each backend declares its authority scope + what it is valid FOR
(planning / rehearsal / release / execute) + why it is refused where it isn't. The load-bearing invariants:
tier2_numpy is the conserved terrain/terramechanics authority (mass-conserving, release-eligible); gazebo is
robot/sensor/contact simulation and is NOT the terrain-mutation authority (truth-isolated, not release); chrono
is a high-fidelity reference that is NOT release-eligible until mass-conservation + calibration gates pass;
godot is rendering only and NEVER physics or command authority. Config sourced from the design doc, not
synthetic data. Complements the PX-02 model ledger (physics_model_control) with the authority model."""
from __future__ import annotations

from typing import TypedDict


class PhysicsBackendAuthority(TypedDict):
    id: str
    authority_scope: list[str]     # subset of terrain | terramechanics | robot | sensor | contact | rendering | hardware | clock
    conserves_mass: bool
    valid_for_planning: bool
    valid_for_rehearsal: bool
    valid_for_release: bool
    valid_for_execute: bool
    refusal_reason: str | None     # why NOT release/execute-eligible where it isn't
    description: str


_BACKENDS: tuple[PhysicsBackendAuthority, ...] = (
    {"id": "tier2_numpy", "authority_scope": ["terrain", "terramechanics"], "conserves_mass": True,
     "valid_for_planning": True, "valid_for_rehearsal": True, "valid_for_release": True, "valid_for_execute": True,
     "refusal_reason": None,
     "description": "The conserved terrain/terramechanics authority for local planning + mass-conserving excavation evidence."},
    {"id": "gazebo", "authority_scope": ["robot", "sensor", "contact", "clock"], "conserves_mass": False,
     "valid_for_planning": False, "valid_for_rehearsal": True, "valid_for_release": False, "valid_for_execute": False,
     "refusal_reason": "robot/sensor/contact simulation only; NOT the conserved terrain-mutation authority; truth-isolated.",
     "description": "Gazebo robot/sensor/contact/odometry/clock simulation: the SIM robot's OWN dynamics ARE the rehearsal truth (pose/odom from the robot model), truth-isolated from the perception stack; validates robot behavior, not terrain truth."},
    {"id": "chrono", "authority_scope": ["terramechanics", "contact"], "conserves_mass": False,
     "valid_for_planning": False, "valid_for_rehearsal": True, "valid_for_release": False, "valid_for_execute": False,
     "refusal_reason": "high-fidelity reference/oracle; not release-eligible until mass-conservation + calibration gates pass.",
     "description": "Optional high-fidelity terramechanics/contact reference; a benchmark/oracle only when its limits are labeled."},
    {"id": "hardware", "authority_scope": ["robot", "hardware", "sensor"], "conserves_mass": False,
     "valid_for_planning": False, "valid_for_rehearsal": True, "valid_for_release": True, "valid_for_execute": True,
     "refusal_reason": None,
     "description": "Real rover/testbed telemetry + actuator feedback; the live-execution authority under the release chain."},
    {"id": "godot", "authority_scope": ["rendering"], "conserves_mass": False,
     "valid_for_planning": False, "valid_for_rehearsal": False, "valid_for_release": False, "valid_for_execute": False,
     "refusal_reason": "visualization/rendering/replay only; never physics or command authority (no future promotion without an explicit tested row).",
     "description": "High-fidelity rendering/replay that renders FROM the conserved authority's Seam-1 state fields (heightmap/density/disturbance) + the robot pose -- it consumes physics as a ONE-WAY render input but computes no physics and holds no command authority (a drive-in-sim view would relay control to the authority, never simulate its own)."},
)

BACKENDS: dict[str, PhysicsBackendAuthority] = {b["id"]: b for b in _BACKENDS}


def list_backend_authority() -> list[PhysicsBackendAuthority]:
    return list(_BACKENDS)
