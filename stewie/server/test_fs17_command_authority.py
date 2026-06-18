"""FS-17 [REQ:FS-17] (PRD 7.x): one cockpit holds command authority; a second window/tab is read-only.

The live cross-tab behavior (tab 1 = command authority, tab 2 = read-only, banner + disabled command
controls) is exercised in a real browser by scripts -- the two-tab Playwright check confirms tab 2 goes
read-only and #qcmds is disabled. This is the fast static guard that the FS-17 wiring exists and that the
command-emit path is gated, so a regression that drops the guard or the leader election is caught in CI.
"""
from __future__ import annotations

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_COCKPIT = os.path.join(_ROOT, "stewie", "server", "web", "assets", "cockpit.js")


def _read(p: str) -> str:
    with open(p) as f:
        return f.read()


def test_leader_election_module_is_wired():
    js = _read(_COCKPIT)
    # the single-authority election: a BroadcastChannel + a localStorage claim key + a start() on boot
    assert "BroadcastChannel(\"stewie_cmd_authority\")" in js
    assert "stewie_cmd_authority" in js
    assert "const CMD_AUTH = (function ()" in js
    assert "CMD_AUTH.start()" in js                      # the election runs on boot
    assert "body.dataset.cmdrole" in js or "dataset.cmdrole" in js


def test_command_emit_is_gated_by_command_authority():
    js = _read(_COCKPIT)
    # guardCommand refuses a read-only window, and the command-tape emit (#qcmds) calls it FIRST
    assert "function guardCommand(" in js
    qcmds = js.split('qel("qcmds").onclick', 1)
    assert len(qcmds) == 2, "the #qcmds command handler is missing"
    body_after = qcmds[1].split("await fetch(\"/plan/commands\"", 1)[0]
    assert "guardCommand(" in body_after, "guardCommand must gate /plan/commands BEFORE the request"


def test_readonly_banner_and_command_control_marked():
    html = _read(_INDEX)
    assert 'id="cmd-readonly-banner"' in html              # the read-only banner element exists
    assert 'id="cmd-takeover"' in html                     # explicit take-over control (no silent promotion)
    # the command-tape button is tagged so the read-only window disables it
    qcmds = html.split('id="qcmds"', 1)
    assert len(qcmds) == 2 and "data-cmd-authority" in qcmds[1].split(">", 1)[0]
