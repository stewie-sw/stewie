"""SHIM [REQ:PO-18]. The terramechanics models moved to the standalone `stewie-forge` package
(packages/stewie-forge/stewie_forge/terramechanics.py); this re-exports them verbatim so every
`from stewie.physics import terramechanics` and `from stewie.physics.terramechanics import ...` caller is
unchanged. New code should import from `stewie_forge`."""
from stewie_forge.terramechanics import *  # noqa: F401,F403
