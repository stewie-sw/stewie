"""SHIM [REQ:PO-18]. The bearing-capacity models moved to the standalone `stewie-forge` package
(packages/stewie-forge/stewie_forge/bearing.py); this re-exports them verbatim so `from forge.bearing import
...` callers are unchanged. New code should import from `stewie_forge`."""
from stewie_forge.bearing import *  # noqa: F401,F403
