"""bodies.py — SHIM [REQ:PO-17]. The per-planet body/regolith registry moved to the standalone `stewie-bodies`
package (packages/stewie-bodies); this re-exports it VERBATIM so every `from stewie.specs.bodies import ...`
caller is unchanged, and keeps the physics-dependent `params_for_body` compat wrapper (which cannot live in the
zero-dependency package — it needs `stewie.physics`)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from stewie_bodies import BODIES, DEFAULT_BODY, Body, body_in_regime, get_body

if TYPE_CHECKING:                                   # type-only; the bodies->physics edge stays broken (BD-04)
    from stewie.physics.terramechanics import TerramechanicsParams

__all__ = ["BODIES", "DEFAULT_BODY", "Body", "body_in_regime", "get_body", "params_for_body"]


def params_for_body(name, *, allow_analog: bool = False) -> TerramechanicsParams:
    """[REQ:BD-04] Compatibility wrapper. The body->terramechanics conversion lives in
    `stewie.physics.body_params` (physics -> bodies direction); this LAZY delegate keeps `stewie.specs.bodies`
    free of any `stewie.physics` MODULE-LEVEL import. Values + microgravity fail-closed behaviour unchanged."""
    from stewie.physics.body_params import params_for_body as _pfb
    return _pfb(name, allow_analog=allow_analog)
