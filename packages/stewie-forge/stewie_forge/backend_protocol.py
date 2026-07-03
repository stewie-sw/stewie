"""[REQ:PO-18] The PhysicsBackend seam (abstract). A stable interface over the terrain-physics authority so
Tier-2 (conserved NumPy) and future engines (Tier-3 Chrono/hybrid) are selectable per mission WITHOUT the
planner or any client mutating terrain directly. This is the PROTOCOL + its self-describing info only; the
concrete Tier2NumpyBackend (which resolves body soil params via the stewie-core body_params adapter) stays in
stewie-core (`stewie.physics.backend`). A backend that does not conserve mass cannot claim release authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stewie_forge.terramechanics import TerramechanicsParams

AuthorityClass = Literal["conserved", "geometry_oracle", "advisory"]


@dataclass(frozen=True)
class PhysicsBackendInfo:
    id: str
    label: str
    authority_class: AuthorityClass    # "conserved" may drive release/execute; others may not
    conserves_mass: bool
    fidelity_tier: int                 # 2 = conserved NumPy, 3 = granular/Chrono
    notes: str = ""


@runtime_checkable
class PhysicsBackend(Protocol):
    """The contract every physics engine implements. A backend that does not conserve mass cannot be selected
    for release/execute authority (checked by the caller against `info().conserves_mass`)."""

    def info(self) -> PhysicsBackendInfo: ...
    def conserves_mass(self) -> bool: ...
    def resolve_soil_params(self, body_name: str, *, allow_analog: bool = ...) -> "TerramechanicsParams": ...
    def wheel_static_sinkage(self, *args, **kwargs) -> float: ...
    def static_wheel_load_n(self, *args, **kwargs) -> float: ...
    def allowable_bearing_pa(self, *args, **kwargs) -> float: ...
