"""[dispatch-audit R3b] gated live writes: the live-write path (/rc/command GoTo for a mission) enforces the
EG-05 training-to-live token, bound to the immutable released revision.

The audit (R3, "close command authority") found a mission-bound GoTo reached the rover-command seam behind
only the AG-08 published-live check + the command-eligibility interlock -- it never required the
LiveExecutionToken that certifies the training-to-live sequence passed for the signed revision. R3b closes
that:
  - a PRESENTED live_token + revision_hash is ALWAYS verified fail-closed (unforged / unexpired / bound to a
    real released revision), so a forged/expired/retargeted token is refused (403);
  - when live execution is explicitly enabled ($STEWIE_ALLOW_LIVE_EXEC), a mission-bound GoTo MUST present a
    valid token (a real live rover write requires the gate to have passed);
  - by default (gate OFF, the SIM/MO-04 posture) a token-less mission-bound GoTo keeps working, so the
    existing SIM command flow is unchanged.

Real store + the SF-01 RC router via a TestClient. No physical rover is driven (the actuation seam is
container/hardware-gated); this asserts the authority DECISION at the HTTP boundary.
"""
from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as srv
    importlib.reload(srv)
    OBJ.save_mission("Live Pad", {"body": "moon", "orders": []}, owner="op@x.com", namespace="live")
    # fresh, armed watchdog so the command-eligibility interlock is not tripped/stale from a neighbour test.
    from stewie.bridge import rc_contract as C
    from stewie.server.routers import rc as RCR
    saved_wd = RCR._RC_WATCHDOG
    RCR._RC_WATCHDOG = C.SafingWatchdog(RCR._RC_BACKEND, deadline_s=5.0)
    RCR._RC_WATCHDOG.feed(now=time.monotonic())
    yield TestClient(srv.app), "test-key"
    saved_wd.feed(now=time.monotonic())
    RCR._RC_WATCHDOG = saved_wd
    monkeypatch.undo()
    importlib.reload(srv)


def _release_and_run(c, key):
    """Release a real plan (-> content_hash) and run it bound (-> a real, content_hash-bound live_token)."""
    rel = c.post("/executive/release-plan", headers={"X-API-Key": key}, json={
        "body": "moon", "mission_id": "M-r3b", "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert rel.status_code == 200, rel.text
    ch = rel.json()["signed_revision"]["content_hash"]
    run = c.post("/executive/run", headers={"X-API-Key": key},
                 json={"revision_hash": ch, "site": "haworth"})
    assert run.status_code == 200, run.text
    tok = run.json()["live_token"]
    assert tok["issued"] is True, tok
    return ch, tok


def _goto(mission="Live Pad", **extra):
    return {"kind": "goto", "goal_row": 5, "goal_col": 6, "mission": mission, **extra}


def _fresh_link():
    """Feed the SF-01 watchdog so the link is NON-stale at command time. The R3b token gate is orthogonal to
    the NV-12 stale-link interlock; slow setup (release+run, ~seconds) can age the link past its 5 s deadline
    on a slow CI runner -> a spurious `stale_link` 409 before the command is judged. Feeding right before the
    command isolates the R3b decision (an operator issuing a command has a live link)."""
    from stewie.server.routers import rc as RCR
    RCR._RC_WATCHDOG.feed(now=time.monotonic())


def test_valid_presented_token_is_accepted(client):  # [dispatch-audit R3b]
    c, key = client
    ch, tok = _release_and_run(c, key)
    _fresh_link()   # setup (release+run) aged the link; refresh it so this asserts the R3b gate, not NV-12
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=tok, revision_hash=ch))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "goto"


def test_forged_token_is_refused(client):  # [dispatch-audit R3b]
    c, key = client
    ch, tok = _release_and_run(c, key)
    forged = dict(tok, signature="deadbeef" * 8)
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=forged, revision_hash=ch))
    assert r.status_code == 403, r.text
    assert "token" in r.text.lower()


def test_expired_token_is_refused(client):  # [dispatch-audit R3b]
    c, key = client
    ch, _tok = _release_and_run(c, key)
    # mint a validly-signed token (same in-process secret) that is already expired.
    from stewie.contracts.live_gate import LivePreconditions, issue_live_token
    exp = issue_live_token("M-r3b", ch, LivePreconditions(True, True, True, True, True, True),
                           now=1.0, ttl_s=1.0)
    tok_d = {"mission_id": exp.mission_id, "revision_id": exp.revision_id,
             "issued_at": exp.issued_at, "ttl_s": exp.ttl_s, "signature": exp.signature}
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=tok_d, revision_hash=ch))
    assert r.status_code == 403, r.text
    assert "expired" in r.text.lower()


def test_token_bound_to_a_different_revision_is_refused(client):  # [dispatch-audit R3b]
    c, key = client
    ch, tok = _release_and_run(c, key)
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=tok, revision_hash="0" * 64))   # unknown released revision
    assert r.status_code == 403, r.text


def test_gate_on_requires_a_token_for_a_mission_bound_goto(client, monkeypatch):  # [dispatch-audit R3b]
    c, key = client
    monkeypatch.setenv("STEWIE_ALLOW_LIVE_EXEC", "1")
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())   # no token, gate ON
    assert r.status_code == 403, r.text
    assert "token" in r.text.lower()


def test_gate_off_default_token_less_goto_still_works(client):  # [dispatch-audit R3b]
    """Backward compatibility / MO-04 SIM posture: with the gate OFF (default) a token-less mission-bound
    GoTo keeps working -- it drives the SIM backend, not a real rover."""
    c, key = client
    _fresh_link()
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())   # no token, gate OFF (default)
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "goto"
