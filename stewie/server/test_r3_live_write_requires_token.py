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


def _release_and_run(c, key, mission_id="Live Pad", depth_m=0.2):
    """Release a real plan for ``mission_id`` (-> content_hash) and run it bound (-> a real,
    content_hash-bound live_token).

    SR-02: the released mission is now the SAME identity the command targets. Previously this released
    ``M-r3b``, ran without a ``mission_id`` (so the token was minted for the ``"cockpit-run"`` default),
    and then commanded ``"Live Pad"`` -- three different mission identities, asserted to succeed. The
    token is only meaningful when the released, minted and commanded mission are one identity.
    """
    rel = c.post("/executive/release-plan", headers={"X-API-Key": key}, json={
        "body": "moon", "mission_id": mission_id, "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0,
             "depth_m": depth_m}]})
    assert rel.status_code == 200, rel.text
    ch = rel.json()["signed_revision"]["content_hash"]
    run = c.post("/executive/run", headers={"X-API-Key": key},
                 json={"revision_hash": ch, "site": "haworth", "mission_id": mission_id})
    assert run.status_code == 200, run.text
    tok = run.json()["live_token"]
    assert tok["issued"] is True, tok
    assert tok["mission_id"] == mission_id, f"token minted for {tok['mission_id']!r}, not the released mission"
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


def test_bound_run_derives_mission_from_signed_revision(client):
    """The request default is not an identity: a bound run must inherit the frozen signed mission."""
    c, key = client
    rel = c.post("/executive/release-plan", headers={"X-API-Key": key}, json={
        "body": "moon", "mission_id": "Live Pad", "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0,
             "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert rel.status_code == 200, rel.text
    ch = rel.json()["signed_revision"]["content_hash"]

    run = c.post("/executive/run", headers={"X-API-Key": key},
                 json={"revision_hash": ch, "site": "haworth"})
    assert run.status_code == 200, run.text
    assert run.json()["mission_id"] == "Live Pad"
    assert run.json()["live_token"]["mission_id"] == "Live Pad"


@pytest.mark.parametrize("retarget", ["Other Pad", "cockpit-run"])
def test_bound_run_rejects_request_mission_retarget_before_execution(client, monkeypatch, retarget):
    """A caller cannot label Mission A's frozen plan/run/token as Mission B."""
    c, key = client
    rel = c.post("/executive/release-plan", headers={"X-API-Key": key}, json={
        "body": "moon", "mission_id": "Live Pad", "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0,
             "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert rel.status_code == 200, rel.text
    ch = rel.json()["signed_revision"]["content_hash"]

    from lode import autonomy as AUT

    def unexpected_execution(*_args, **_kwargs):
        raise AssertionError("retargeted bound run reached simulation")

    monkeypatch.setattr(AUT, "run_closed_loop", unexpected_execution)
    run = c.post("/executive/run", headers={"X-API-Key": key}, json={
        "revision_hash": ch, "site": "haworth", "mission_id": retarget})
    assert run.status_code == 409, run.text
    assert "released for mission" in run.text


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
    exp = issue_live_token("Live Pad", ch, LivePreconditions(True, True, True, True, True, True),
                           now=1.0, ttl_s=1.0)
    tok_d = {"mission_id": exp.mission_id, "revision_id": exp.revision_id,
             "issued_at": exp.issued_at, "ttl_s": exp.ttl_s, "signature": exp.signature}
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=tok_d, revision_hash=ch))
    assert r.status_code == 403, r.text
    assert "expired" in r.text.lower()


def test_unknown_revision_hash_is_refused(client):  # [dispatch-audit R3b]
    """A hash that was never released is refused by the existence guard, before any token comparison."""
    c, key = client
    _ch, tok = _release_and_run(c, key)
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=tok, revision_hash="0" * 64))   # unknown released revision
    assert r.status_code == 403, r.text


def test_token_bound_to_a_different_revision_is_refused(client):  # [dispatch-audit R3b]
    """SR-02: this previously passed ``"0"*64`` -- an UNKNOWN hash, refused by the released-revision
    existence guard at rc.py before the token's revision binding was ever compared. It therefore proved
    only that an unknown hash 403s, never that revision binding works. Bind against a genuinely released
    SECOND revision so the revision comparison itself is what refuses."""
    c, key = client
    ch1, tok1 = _release_and_run(c, key, depth_m=0.2)
    ch2, _tok2 = _release_and_run(c, key, depth_m=0.4)      # a real, DIFFERENT released revision
    assert ch2 != ch1, "the two releases must differ for this to exercise revision binding"
    _fresh_link()
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(live_token=tok1, revision_hash=ch2))
    assert r.status_code == 403, r.text


def test_a_token_for_another_mission_is_refused(client):  # [dispatch-audit R3b]
    """SR-02 / AR-001, the core: the redemption check compared the token's mission against the TOKEN'S
    OWN ``mission_id`` (``require_live_token(token, token.mission_id, ...)``), a value compared with
    itself -- so it could never fail. A token attesting one released mission must not authorize a
    command against a DIFFERENT live mission."""
    c, key = client
    from stewie.server import objects as OBJ
    OBJ.save_mission("Other Pad", {"body": "moon", "orders": []}, owner="op@x.com", namespace="live")
    ch, tok = _release_and_run(c, key, mission_id="Live Pad")
    _fresh_link()
    r = c.post("/rc/command", headers={"X-API-Key": key},
               json=_goto(mission="Other Pad", live_token=tok, revision_hash=ch))
    assert r.status_code == 403, r.text
    assert "mission" in r.text.lower()


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
