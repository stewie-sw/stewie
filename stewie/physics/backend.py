"""[REQ:PO-18] The concrete Tier-2 physics backend (stewie-core).

The abstract PhysicsBackend PROTOCOL + PhysicsBackendInfo + AuthorityClass live in the `stewie-forge` package
(`stewie_forge.backend_protocol`). `Tier2NumpyBackend` stays HERE because it resolves body soil params via the
stewie-core `body_params` adapter (which applies the `stewie.specs.config` overlay), so it is not a
zero-STEWIE-dependency artifact. The protocol names are re-exported so existing
`from stewie.physics.backend import PhysicsBackend` callers are unchanged.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from stewie_forge.backend_protocol import (  # noqa: F401  (re-exported for existing importers)
    AuthorityClass,
    PhysicsBackend,
    PhysicsBackendInfo,
)

from stewie.physics import terramechanics as TM
from stewie.physics.body_params import params_for_body

if TYPE_CHECKING:
    from stewie_forge.terramechanics import TerramechanicsParams


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
        from stewie_forge.bearing import allowable_bearing_pa as _ab
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
