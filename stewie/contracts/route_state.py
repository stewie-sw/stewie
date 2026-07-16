"""[REQ:FS-25] Product mode + runnable profile: the BACKEND route/state contract (review finding 4).

The cockpit route/state model carries the PRD PRODUCT MODE and the RUNNABLE PROFILE as first-class
routeable / persisted / shareable fields -- beyond the coarse ``source`` (live/sim/eval) + ``mode``
(sandbox/live) axes. This module is the backend SOURCE OF TRUTH for that vocabulary: the five product
modes and the eight runnable profiles, plus a strict, frozen, version-stamped ``RouteState`` contract
that validates the mode+profile at the route boundary and round-trips them (so a persisted / shared
route-state restores a VALIDATED mode+profile). ``frontend/src/workspace.ts`` mirrors this vocabulary;
the FS-25 gate proves the two cannot drift.

This is DISTINCT from two neighbouring axes and must not be conflated with either:

* ``governance.EnvironmentMode`` (EG-01) -- dev/training/rehearsal/live/replay/archive -- is the
  AUTHORITY axis (what a session may command), not the route/state product mode.
* ``specs.runtime_profiles`` (RT-01) -- desktop_sil/.../live_rover -- is the execution-environment
  REGISTRY with per-profile command/evidence capabilities, a related but larger taxonomy.

RouteState carries only the mode/profile slice of the route/state; the rest of the routeable context
(site/body/mission/vehicle/role) lives in the mission-authority tuple (lode.mission_package).
"""
from __future__ import annotations

from pydantic import field_validator

from stewie.contracts import Contract

#: the five PRD product modes the cockpit route/state carries (workspace.ts PRODUCT_MODES).
PRODUCT_MODES: tuple[str, ...] = ("GIS-PLAN", "TRAIN", "SIM-OPERATE", "EVALUATE", "OPERATE")

#: the eight runnable profiles the cockpit route/state carries (workspace.ts RUNNABLE_PROFILES). The
#: backend wires desktop_sil + ros2_replay today; the rest are declared route/state values.
RUNNABLE_PROFILES: tuple[str, ...] = (
    "desktop_sil", "digital_twin", "ros2_replay", "hil_jetson",
    "sensor_bench", "rover_bench", "field_traverse", "monte_carlo",
)


class RouteState(Contract):
    """The mode/profile slice of the cockpit route/state, as a strict/frozen/versioned contract. Defaults
    match ``workspace.ts`` defaultWorkspace (GIS-PLAN planning on the desktop software-in-loop profile).
    An unknown mode or profile is rejected at the boundary (fail-closed), so a persisted/shared route-state
    can never carry an off-vocabulary value."""

    product_mode: str = "GIS-PLAN"
    runnable_profile: str = "desktop_sil"

    @field_validator("product_mode")
    @classmethod
    def _known_mode(cls, v: str) -> str:
        if v not in PRODUCT_MODES:
            raise ValueError(f"unknown product_mode {v!r}; must be one of {PRODUCT_MODES}")
        return v

    @field_validator("runnable_profile")
    @classmethod
    def _known_profile(cls, v: str) -> str:
        if v not in RUNNABLE_PROFILES:
            raise ValueError(f"unknown runnable_profile {v!r}; must be one of {RUNNABLE_PROFILES}")
        return v


def validate_route_state(product_mode: str, runnable_profile: str) -> tuple[str, str]:
    """Validate a (product_mode, runnable_profile) pair against the route/state vocabulary, fail-closed.
    Returns the pair unchanged when both are known; raises (pydantic ValidationError, a ValueError) otherwise.
    The single chokepoint any route boundary calls before persisting or sharing a mode+profile."""
    rs = RouteState(product_mode=product_mode, runnable_profile=runnable_profile)
    return (rs.product_mode, rs.runnable_profile)
