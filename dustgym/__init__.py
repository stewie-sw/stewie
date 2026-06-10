"""DEPRECATED import name. The package is ``stewie`` (renamed 2026-06-10; "dustgym" retired).

``import dustgym`` keeps working for one transition cycle: it forwards to the same registration
(the Gymnasium env IDs are now ``Stewie/*``; the legacy ``Dust/*`` IDs are registered as aliases).
"""
import warnings

warnings.warn("'dustgym' is renamed 'stewie' (2026-06-10); update imports", DeprecationWarning,
              stacklevel=2)
from stewie.envs.registration import register_envs as _register_envs   # noqa: E402

_register_envs()
