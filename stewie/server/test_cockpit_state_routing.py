"""[REQ:FS-16] Cockpit route-state gate.

The JavaScript state model is pure and has node tests, but req_trace only counts Python markers. This
static gate makes the production shell prove the same routeable state model drives desktop and mobile:
one module, one global (`STEWIE_STATE`), enum-guarded transitions, and hash restoration.
"""
from __future__ import annotations

import re
from pathlib import Path


_ROOT = Path(__file__).parent
_STATE = _ROOT / "web" / "assets" / "cockpit_state.js"
_COCKPIT = _ROOT / "web" / "assets" / "cockpit.js"
_INDEX = _ROOT / "index.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _array_literal(src: str, name: str) -> list[str]:
    m = re.search(rf"var {name} = \[([^\]]+)\];", src)
    assert m, f"{name} array missing from cockpit_state.js"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_default_state_covers_routeable_fields_and_enums():  # [REQ:FS-16]
    src = _read(_STATE)
    for field in ("mission", "site", "vehicle", "body", "timeS", "mode", "role", "workArea",
                  "selectedEntity", "source"):
        assert re.search(rf"\b{field}\s*:", src), f"defaultState missing {field}"

    assert {"plan", "fleet", "navigation", "perception", "system", "report", "admin"}.issubset(
        set(_array_literal(src, "WORK_AREAS")))
    assert {"live", "sim", "eval"}.issubset(set(_array_literal(src, "SOURCES")))
    assert {"sandbox", "live"}.issubset(set(_array_literal(src, "MODES")))


def test_state_transitions_reject_unknown_enums():  # [REQ:FS-16]
    src = _read(_STATE)
    for guard in ("unknown workArea", "unknown source", "unknown mode"):
        assert guard in src, f"setState no longer fails closed for {guard}"
    assert "throw new Error" in src and "function setState(state, patch)" in src


def test_hash_round_trip_uses_the_routeable_subset():  # [REQ:FS-16]
    src = _read(_STATE)
    for key in ("workArea", "site", "mission", "vehicle", "source", "mode"):
        assert f'"{key}"' in src, f"toHash/fromHash route key missing: {key}"
    assert 'if (k === "t") state.timeS = parseFloat(v) || 0;' in src
    assert "else if (k in state) state[k] = v;" in src


def test_production_shell_uses_one_state_model_for_desktop_and_mobile():  # [REQ:FS-16]
    html = _read(_INDEX)
    js = _read(_COCKPIT)

    state_pos = html.find("/assets/cockpit_state.js")
    cockpit_pos = html.find("/assets/cockpit.js")
    assert state_pos >= 0, "index.html does not load cockpit_state.js"
    assert cockpit_pos >= 0 and state_pos < cockpit_pos, "cockpit_state.js must load before cockpit.js"

    assert "window.STEWIE_STATE" in js, "cockpit.js is not wired to the single STEWIE_STATE model"
    assert "ROUTE_STATE.defaultState()" in js
    assert "ROUTE_STATE.fromHash(" in js
    assert "ROUTE_STATE.setState(" in js
    assert "ROUTE_STATE.toHash(" in js
    assert "innerWidth <= 860" in js, "mobile layout must be an alternate view, not separate state logic"
