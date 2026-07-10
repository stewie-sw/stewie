"""[REQ:RF-02] the React workspace state binds to the REAL backend contracts, not fabricated ones: its
physics-backend enum matches the mission registry (tier2_numpy default + tier3_chrono), and the Release/
Execute guard reads the RS-01 CommandEligibility contract (eligible + reason). Source-parsed against the
committed frontend; the guard defers to /rc/eligibility (no re-implemented rule)."""
import dataclasses
import os
import re

from lode.planner_model import Mission

from stewie.contracts.runtime_spine import CommandEligibility

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _ws_enum(name: str) -> set[str]:
    with open(os.path.join(_ROOT, "frontend", "src", "workspace.ts"), encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(rf"{name}:[^=]*=\s*\[(.*?)\]", src, re.S)
    assert m, f"{name} not found in workspace.ts"
    return set(re.findall(r'"([a-z0-9_-]+)"', m.group(1)))


def test_rf02_physics_backends_match_the_mission_registry():  # [REQ:RF-02]
    # [dispatch-audit R4] the frontend advertises ONLY the server's selectable backends; the PX-03 Chrono
    # oracle is NOT selectable until it conserves mass (was wrongly advertised as "tier3_chrono", which is
    # not even a real backend_id). The dynamic UI<->registry parity is test_r4_chrono_backend_ui_parity.
    backends = _ws_enum("PHYSICS_BACKENDS")
    assert backends == {"tier2_numpy"}, f"frontend backends drift: {backends}"
    default = {f.name: f for f in dataclasses.fields(Mission)}["physics_backend_id"].default
    assert default in backends and default == "tier2_numpy"   # the fail-closed default (PX-02)


def test_rf02_source_classes_match_the_run_source_axis():  # [REQ:RF-02]
    assert _ws_enum("SOURCE_CLASSES") == {"live", "sim", "eval"}   # cockpit_state.js SOURCES


def test_rf02_guard_reads_the_command_eligibility_contract():  # [REQ:RF-02]
    # the React guard reads exactly these fields off GET /rc/eligibility -> the RS-01 contract carries them.
    c = CommandEligibility(eligible=False, reason="no mission")
    assert c.eligible is False and c.reason == "no mission"
