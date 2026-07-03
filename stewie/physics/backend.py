"""[REQ:PX-04] The PhysicsBackend seam.

A stable interface over the terrain-physics authority so Tier-2 (conserved NumPy) and future engines (Tier-3
Chrono/hybrid) are selectable per mission WITHOUT the planner or any client mutating terrain directly.
`Tier2NumpyBackend` is a thin passthrough adapter over the existing terramechanics / FORGE bearing /
body-params functions -- the numbers are byte-identical, now behind one interface that reports its
authority_class + conserves_mass. Lives on the physics side (physics/forge -> bodies direction), so
`stewie-forge` can own the protocol; the conserved authority stays the ONLY terrain mutator.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from stewie.physics import terramechanics as TM
from stewie.physics.body_params import params_for_body

if TYPE_CHECKING:
    from stewie.physics.terramechanics import TerramechanicsParams

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


class Tier2NumpyBackend:
    """The conserved Tier-2 NumPy authority behind the interface. Delegates VERBATIM to the existing functions
    (byte-identical output); the value added is the selectable, self-describing interface."""

    def info(self) -> PhysicsBackendInfo:
        return PhysicsBackendInfo(
            id="tier2_numpy", label="Tier-2 conserved NumPy authority",
            authority_class="conserved", conserves_mass=True, fidelity_tier=2,
            notes="Bekker/Wong-Reece + slip + mass-conserving compaction; the sim authority.")

    def conserves_mass(self) -> bool:
        return True

    def resolve_soil_params(self, body_name: str, *, allow_analog: bool = False) -> "TerramechanicsParams":
        return params_for_body(body_name, allow_analog=allow_analog)

    def wheel_static_sinkage(self, *args, **kwargs) -> float:
        return TM.wheel_static_sinkage(*args, **kwargs)

    def static_wheel_load_n(self, *args, **kwargs) -> float:
        return TM.static_wheel_load_n(*args, **kwargs)

    def allowable_bearing_pa(self, *args, **kwargs) -> float:
        from forge.bearing import allowable_bearing_pa as _ab
        return _ab(*args, **kwargs)


TIER2 = Tier2NumpyBackend()
_BACKENDS: dict[str, PhysicsBackend] = {"tier2_numpy": TIER2}


def get_backend(backend_id: str = "tier2_numpy") -> PhysicsBackend:
    """Resolve a physics backend by id. Only `tier2_numpy` is registered now; the Chrono/hybrid backend is
    PX-03 (geometry-oracle, NOT release-authority until it conserves mass)."""
    b = _BACKENDS.get(backend_id)
    if b is None:
        raise ValueError(f"unknown physics backend {backend_id!r}; registered: {sorted(_BACKENDS)}")
    return b


def list_backends() -> list[str]:
    return sorted(_BACKENDS)
