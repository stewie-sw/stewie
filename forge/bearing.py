"""SHIM [REQ:PO-18]. The bearing-capacity models moved to the standalone `stewie-forge` package
(packages/stewie-forge/stewie_forge/bearing.py); this re-exports them so `from forge.bearing import ...`
callers are unchanged. Explicit re-exports (not `import *`) so static analysis resolves the names. New code
should import from `stewie_forge`."""
from stewie_forge.bearing import (
    allowable_bearing_pa,
    bearing_capacity_factors,
    ultimate_bearing_capacity_pa,
)

__all__ = ["allowable_bearing_pa", "bearing_capacity_factors", "ultimate_bearing_capacity_pa"]
