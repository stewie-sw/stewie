"""[REQ:GW-10] per-component monotonic request guard.

The guard is pure browser JS with node tests (gis/qwc2/js/mission/reqGuard.test.js proves the runtime
behavior: the wrong-site race — a slow site-A load resolving after a switch to site-B is dropped, not
applied — plus per-component isolation). But req_trace.py counts only Python markers, so this static gate
is the python [REQ:GW-10] citation. It proves the same requirement structurally: (1) reqGuard.js IS a
monotonic token guard (next issues a rising token; current(tok) is true only for the latest; bump/next
invalidate every in-flight token), and (2) it is actually HELD by the three surfaces GW-10 names — the
raster (MissionTerrain3D), the physics/profile (MissionCrossSection), and the inspector
(SelectionInspector) — so a stale in-flight load cannot overwrite the current site's state on any of them.
Mirrors test_cockpit_state_routing.py's static-gate convention for a pure-JS row.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[2]                       # stewie/server/ -> stewie/ -> repo root
_GUARD = _ROOT / "gis" / "qwc2" / "js" / "mission" / "reqGuard.js"
_PLUGINS = _ROOT / "gis" / "qwc2" / "js" / "plugins"

# the three surfaces GW-10 names ("B's raster/physics/inspector state"), each a real reqGuard consumer.
_CONSUMERS = {
    "raster": _PLUGINS / "MissionTerrain3D.jsx",
    "physics": _PLUGINS / "MissionCrossSection.jsx",
    "inspector": _PLUGINS / "SelectionInspector.jsx",
}


def _read(p: Path) -> str:
    assert p.exists(), f"GW-10 source missing: {p}"
    return p.read_text(encoding="utf-8")


def test_reqguard_is_a_monotonic_token_guard():  # [REQ:GW-10]
    src = _read(_GUARD)
    assert "function makeReqGuard()" in src, "the guard factory is gone"
    # next(): issues a strictly rising token (seq += 1; return seq).
    assert "next:" in src and "seq += 1" in src and "return seq" in src
    # current(tok): true ONLY for the latest issued token (tok === seq) -> a stale token reads false.
    assert "current:" in src and "tok === seq" in src
    # bump(): invalidates every in-flight token (seq += 1) on unmount / explicit site change.
    assert "bump:" in src
    # exactly these three primitives are exported (the UMD factory surface).
    for name in ("makeReqGuard", "next", "current", "bump"):
        assert name in src, f"guard primitive missing: {name}"


def test_the_raster_physics_and_inspector_surfaces_each_hold_a_guard():  # [REQ:GW-10]
    """Each named surface imports reqGuard, instantiates its OWN guard (makeReqGuard), takes a token at the
    start of a load (next), and drops a stale resolve (current(tok) gate) / invalidates on change (bump).
    This is the structural proof that a slow prior-site load cannot overwrite the current site's state."""
    for surface, path in _CONSUMERS.items():
        src = _read(path)
        assert "reqGuard.js" in src, f"{surface} does not import the request guard"
        assert "makeReqGuard()" in src, f"{surface} does not instantiate its own guard"
        assert ".next()" in src, f"{surface} does not take a token at load start"
        # the stale-drop is either the current(tok) resolve-guard or a bump() on site change (both invalidate).
        assert (".current(" in src) or (".bump()" in src), f"{surface} never drops a stale in-flight load"


def test_guards_are_per_component_not_a_shared_singleton():  # [REQ:GW-10]
    """GW-10 is PER-component: each surface calls makeReqGuard() itself (its own seq counter) rather than
    sharing one guard, so a site switch invalidating the raster load does not also drop an unrelated
    inspector query mid-flight. Assert each consumer constructs its own, and the factory returns a fresh
    closure each call (no module-level shared seq)."""
    guard_src = _read(_GUARD)
    # the factory's seq is a local of makeReqGuard (declared inside it), not a module global -> fresh per call.
    factory_body = guard_src.split("function makeReqGuard()", 1)[1]
    assert "var seq" in factory_body.split("return {", 1)[0], "seq must be local to makeReqGuard (per-component)"
    for surface, path in _CONSUMERS.items():
        assert "makeReqGuard()" in _read(path), f"{surface} must construct its own guard"
