"""AG-08 (PRD §7.12, END GOAL): real rover instructions are emitted only for a LIVE-namespace mission,
by an operator+, under the SF-01 watchdog. A command that CITES a mission is rejected unless that
mission is published (live); a sandbox draft can be simulated but is structurally barred from the real
rover-command path. Low-level teleop (no mission ref) is unaffected. Real store + the SF-01 RC backend
via a TestClient (api-key identity == director == operator+; require_role("operator") already passes).

Run: <venv>/bin/python -m pytest stewie/server/test_command_gate.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    import stewie.server.server as srv
    importlib.reload(srv)
    OBJ.save_mission("Live Pad", {"body": "moon", "orders": []}, owner="op@x.com", namespace="live")
    OBJ.save_mission("Draft", {"body": "moon", "orders": []}, owner="alice@x.com", namespace="sandbox")
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def _cmd(mission=None):
    b = {"kind": "safe"}                      # Safe needs no extra args and still goes through the watchdog
    if mission is not None:
        b["mission"] = mission
    return b


def test_command_for_a_live_mission_is_accepted(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd("Live Pad"))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "safe"


def test_command_for_a_sandbox_draft_is_rejected(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd("Draft"))
    assert r.status_code == 403, r.text
    assert "live" in r.text.lower()                  # message shape is handler-dependent; check the text


def test_command_for_a_missing_mission_is_rejected(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd("ghost"))
    assert r.status_code == 403, r.text


def test_low_level_teleop_without_a_mission_is_unaffected(client):
    c, key = client
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_cmd())   # no mission ref
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "safe"
