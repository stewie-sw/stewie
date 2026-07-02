"""[REQ:FS-28] the command-authority EVIDENCE the Execute pane shows before a command: GET /rc/eligibility
returns the full pre-emission verdict as the RS-01 CommandEligibility contract -- every named gate's
pass/fail + the overall eligible + the legible reason -- so an operator sees exactly what authority a
GoTo has, not only a refusal after the fact. These tests pin the per-gate report and the route."""
import importlib
import time

import pytest
from fastapi.testclient import TestClient

from stewie.bridge.command_eligibility import CommandContext, eligibility_report

H = {"X-API-Key": "test-key"}


def test_eligibility_report_gives_every_gate_not_just_the_first_failure():
    # unauthorized guest on a sandbox mission with a stale link: command_eligible stops at the first gate,
    # but the evidence report must expose ALL of them so the card can name everything that is wrong.
    rep = eligibility_report(CommandContext(role="guest", mission_namespace="sandbox",
                                            target_namespace="sandbox", safed=True,
                                            ack_age_s=99.0, ack_deadline_s=2.0))
    assert rep["eligible"] is False
    assert rep["authorized"] is False   # guest < operator
    assert rep["live"] is False         # sandbox, not a published live mission
    assert rep["safe"] is False         # SAFE latched
    assert rep["fresh"] is False        # link stalled past the deadline
    assert rep["namespaced"] is True    # target matches mission namespace


def test_eligibility_report_all_pass_for_a_live_fresh_operator_command():
    rep = eligibility_report(CommandContext(role="operator", mission_namespace="live",
                                            target_namespace="live", safed=False,
                                            ack_age_s=0.1, ack_deadline_s=2.0))
    assert rep == {"eligible": True, "reason": "eligible", "authorized": True, "live": True,
                   "safe": True, "fresh": True, "namespaced": True}


def test_eligibility_report_fail_closed_on_none_context():
    rep = eligibility_report(None)
    assert rep["eligible"] is False and rep["reason"] == "no_context"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")             # dev-open resolves to the operator identity
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    import stewie.server.server as srv
    importlib.reload(srv)
    OBJ.save_mission("Live Pad", {"body": "moon", "orders": []}, owner="op@x.com", namespace="live")
    # a fresh, armed watchdog so the link-ack gate is fresh (not NV-12-stale from an earlier suite test).
    from stewie.bridge import rc_contract as C
    from stewie.server.routers import rc as RCR
    saved = RCR._RC_WATCHDOG
    RCR._RC_WATCHDOG = C.SafingWatchdog(RCR._RC_BACKEND, deadline_s=5.0)
    RCR._RC_WATCHDOG.feed(now=time.monotonic())
    yield TestClient(srv.app)
    RCR._RC_WATCHDOG.feed(now=time.monotonic())
    RCR._RC_WATCHDOG = saved
    monkeypatch.undo()
    importlib.reload(srv)


def test_rc_eligibility_route_returns_the_full_contract_for_a_live_mission(client):
    r = client.get("/rc/eligibility?mission=Live Pad", headers=H)
    assert r.status_code == 200
    d = r.json()
    # the RS-01 CommandEligibility contract shape, all command-authority gates met on a live+fresh path.
    assert d["eligible"] is True and d["reason"] == "eligible"
    assert d["released"] is True and d["safe_inactive"] is True and d["link_ack"] is True
    assert d["watchdog_alive"] is True and d["mode_ok"] is True
    assert d["schema_version"]                     # it is the versioned contract, not an ad-hoc dict
    for k in ("sensor_fresh", "map_fresh", "covariance_ok"):
        assert k in d                              # perception fields present (contract defaults; FS-27/PM-17)


def test_rc_eligibility_refuses_and_names_the_reason_without_a_live_mission(client):
    # no mission -> not released -> ineligible, with the legible reason the Execute card surfaces.
    d = client.get("/rc/eligibility", headers=H).json()
    assert d["eligible"] is False
    assert d["released"] is False
    assert d["reason"] == "unauthorized_sandbox"


def test_rc_eligibility_reflects_a_stale_link(client, monkeypatch):
    # let the shared watchdog go stale past its deadline: the fresh/link_ack gate must flip and the
    # verdict become ineligible with the stale_link reason (the NV-12 gate surfaced proactively).
    from stewie.server.routers import rc as RCR
    RCR._RC_WATCHDOG.feed(now=time.monotonic() - 1000.0)
    d = client.get("/rc/eligibility?mission=Live Pad", headers=H).json()
    assert d["link_ack"] is False
    assert d["eligible"] is False and d["reason"] == "stale_link"
