"""[dispatch-audit R4] Chrono-id-mismatch regression: the frontend must advertise ONLY the physics backends
the server declares selectable, so a UI-selected backend always resolves. The audit found the React
workspace advertising "tier3_chrono" while the server's selectable set is ["tier2_numpy"] (the ledger's
Chrono model has backend_id "tier2_chrono", and Chrono is not selectable until it conserves mass) -- so
picking the advertised Chrono profile resolved an UNKNOWN backend. This static cross-check reads the
frontend PHYSICS_BACKENDS and asserts it equals the server's list_backends(), catching any future drift.
"""
from __future__ import annotations

import re
from pathlib import Path

from stewie.physics.backend import list_backends

_ROOT = Path(__file__).parents[2]
_WORKSPACE_TS = _ROOT / "frontend" / "src" / "workspace.ts"


def _frontend_physics_backends() -> list[str]:
    """The PHYSICS_BACKENDS array the React workspace advertises (parsed from the TS source)."""
    src = _WORKSPACE_TS.read_text(encoding="utf-8")
    m = re.search(r"PHYSICS_BACKENDS:\s*readonly\s+PhysicsBackend\[\]\s*=\s*\[([^\]]*)\]", src)
    assert m, "PHYSICS_BACKENDS array not found in workspace.ts"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_frontend_advertises_exactly_the_server_selectable_backends():  # [dispatch-audit R4]
    ui = _frontend_physics_backends()
    server = list(list_backends())
    assert server == ["tier2_numpy"], f"server selectable set changed: {server}"
    assert ui == server, (
        f"frontend PHYSICS_BACKENDS {ui} != server selectable_backends {server}; the UI must not offer a "
        f"backend a mission cannot select (a UI-selected backend must always resolve)")


def test_frontend_does_not_advertise_the_unregistered_chrono_id():  # [dispatch-audit R4]
    """The specific audit regression: neither the old UI id 'tier3_chrono' (not a real backend_id) nor the
    ledger's 'tier2_chrono' (not selectable until it conserves mass) may be advertised as a pickable backend."""
    ui = _frontend_physics_backends()
    assert "tier3_chrono" not in ui, "the unregistered 'tier3_chrono' id is back in the UI"
    assert "tier2_chrono" not in ui, "Chrono (tier2_chrono) is not selectable until it conserves mass"
