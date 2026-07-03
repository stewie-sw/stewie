"""stewie-forge: sourced planetary geotechnics + terramechanics + the PhysicsBackend interface.

Public API (concept-first): `estimate_sinkage` and `estimate_bearing_capacity` wrap the underlying
Bekker/Wong-Reece and Terzaghi/Vesic models; the full model set + `TerramechanicsParams` + the
`PhysicsBackend` protocol are re-exported for advanced use. Analytical + conserved-first; numeric-only deps.
"""
from __future__ import annotations

from stewie_forge.backend_protocol import AuthorityClass, PhysicsBackend, PhysicsBackendInfo
from stewie_forge.bearing import (
    allowable_bearing_pa,
    bearing_capacity_factors,
    ultimate_bearing_capacity_pa,
)
from stewie_forge.terramechanics import (
    TerramechanicsParams,
    bekker_pressure_sinkage,
    density_stiffening,
    domain_randomize,
    lyasko_reduce,
    physical_compaction_field,
    physical_compaction_target_density,
    sinkage_to_density_factor,
    slip_sinkage_multiplier,
    static_wheel_load_n,
    wheel_static_sinkage,
)


def estimate_sinkage(load_n: float, *, params: TerramechanicsParams | None = None, **kwargs) -> float:
    """Concept-first: static wheel sinkage [m] under a per-wheel normal load, via Bekker pressure-sinkage."""
    return wheel_static_sinkage(load_n, params=params, **kwargs)


def estimate_bearing_capacity(cohesion_pa: float, phi_rad: float, unit_weight_n_m3: float, width_m: float,
                              **kwargs) -> float:
    """Concept-first: allowable static bearing capacity [Pa] of a built pad/berm (Terzaghi/Vesic)."""
    return allowable_bearing_pa(cohesion_pa, phi_rad, unit_weight_n_m3, width_m, **kwargs)


__all__ = [
    "AuthorityClass", "PhysicsBackend", "PhysicsBackendInfo",
    "TerramechanicsParams", "estimate_sinkage", "estimate_bearing_capacity",
    "wheel_static_sinkage", "static_wheel_load_n", "bekker_pressure_sinkage", "density_stiffening",
    "sinkage_to_density_factor", "slip_sinkage_multiplier", "physical_compaction_field",
    "physical_compaction_target_density", "lyasko_reduce", "domain_randomize",
    "allowable_bearing_pa", "ultimate_bearing_capacity_pa", "bearing_capacity_factors",
]
