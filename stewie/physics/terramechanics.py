"""SHIM [REQ:PO-18]. The terramechanics models moved to the standalone `stewie-forge` package
(packages/stewie-forge/stewie_forge/terramechanics.py); this re-exports them so every
`from stewie.physics import terramechanics` and `from stewie.physics.terramechanics import ...` caller is
unchanged. Explicit re-exports (not `import *`) so static analysis resolves the names. New code should import
from `stewie_forge`."""
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

__all__ = [
    "TerramechanicsParams", "bekker_pressure_sinkage", "density_stiffening", "domain_randomize",
    "lyasko_reduce", "physical_compaction_field", "physical_compaction_target_density",
    "sinkage_to_density_factor", "slip_sinkage_multiplier", "static_wheel_load_n", "wheel_static_sinkage",
]
