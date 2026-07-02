"""[REQ:SF-02] bounded command authority for mission-LESS low-level rover commands (review finding 3).

Every low-level rover command -- including a mission-LESS ``/rc/command`` GoTo (teleop) -- is bounded by
an explicit command-authority context: a released (live) mission OR an explicitly-labelled dev/bench
teleop grant that is REFUSED on a LIVE/OPERATE runnable profile and AUDITED. Before this gate a
mission-less GoTo skipped the AG-08 published-mission check entirely (rc.py only enforced it when a
``mission`` field was present), so low-level teleop had no release-authority binding.

This test asserts the authority DECISION at the HTTP boundary (403 refuse vs 200 accept) plus the audit
record (rc.teleop_refused / rc.teleop_grant). It does NOT drive a physical rover -- the actuation seam is
container/hardware-gated and out of scope for the authority decision, which is fully exercisable in-process
via TestClient.

Run: <venv>/bin/python -m pytest stewie/server/test_rc_command_authority.py -q
"""
import importlib
import json
import time

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
    # Isolate from the process-shared module watchdog: SF-02 authority is the system under test, so each
    # case starts with a fresh, armed link (not tripped, not NV-12-stale from an earlier suite test) and
    # the module state is restored afterwards -- the AS-12/SF-01 gates have their own file.
    from stewie.bridge import rc_contract as C
    from stewie.server.routers import rc as RCR
    saved_wd = RCR._RC_WATCHDOG
    RCR._RC_WATCHDOG = C.SafingWatchdog(RCR._RC_BACKEND, deadline_s=5.0)
    RCR._RC_WATCHDOG.feed(now=time.monotonic())
    yield TestClient(srv.app), "test-key", tmp_path
    # Restore the process-shared watchdog, but leave it FED (not stale): we swapped in our own armed
    # watchdog above, so `saved_wd`'s last feed is now far in the past (wall-clock advanced through the
    # suite). Handing a later suite test (e.g. test_admin's watchdog case) a stale watchdog would trip the
    # NV-12 stale-link gate on an unrelated command. Feeding on restore keeps this file neighborly.
    saved_wd.feed(now=time.monotonic())
    RCR._RC_WATCHDOG = saved_wd
    monkeypatch.undo()
    importlib.reload(srv)


def _audit_actions(data_dir):
    """The audit actions recorded in this test's isolated ledger (events.jsonl under data_dir)."""
    p = data_dir / "events.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln)["action"] for ln in p.read_text().splitlines() if ln.strip()]


def _goto(mission=None):
    b = {"kind": "goto", "goal_row": 5, "goal_col": 6}
    if mission is not None:
        b["mission"] = mission
    return b


def test_mission_less_goto_on_operate_profile_is_refused_and_audited(client, monkeypatch):
    """SF-02 acceptance: a mission-less GoTo on a LIVE/OPERATE runnable profile is REJECTED (403) and the
    refusal is written to the audit ledger -- no low-level teleop reaches a real rover outside a released
    mission or an explicit dev/bench grant."""
    c, key, data_dir = client
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "operate")
    monkeypatch.delenv("STEWIE_ALLOW_TELEOP", raising=False)
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())
    assert r.status_code == 403, r.text
    assert "teleop" in r.text.lower()
    assert "rc.teleop_refused" in _audit_actions(data_dir)


def test_live_profile_teleop_refused_even_with_grant(client, monkeypatch):
    """SF-02: the grant is NOT a bypass -- a LIVE/OPERATE profile refuses mission-less teleop even when
    the explicit teleop grant is present (a production profile can never be teleop-driven)."""
    c, key, data_dir = client
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "live")
    monkeypatch.setenv("STEWIE_ALLOW_TELEOP", "1")
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())
    assert r.status_code == 403, r.text
    assert "rc.teleop_refused" in _audit_actions(data_dir)


def test_unconfigured_profile_fails_safe_to_refused(client, monkeypatch):
    """SF-02 fail-safe: with NO runnable-profile configured (an unprovisioned real deploy) a mission-less
    GoTo is refused by default -- the absence of an explicit dev/bench profile is treated as production."""
    c, key, data_dir = client
    monkeypatch.delenv("STEWIE_RUNNABLE_PROFILE", raising=False)
    monkeypatch.setenv("STEWIE_ALLOW_TELEOP", "1")
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())
    assert r.status_code == 403, r.text
    assert "rc.teleop_refused" in _audit_actions(data_dir)


def test_bench_profile_teleop_requires_the_explicit_grant(client, monkeypatch):
    """SF-02: a dev/bench profile is NOT sufficient on its own -- without the explicit teleop grant the
    mission-less GoTo is still refused (default-deny)."""
    c, key, data_dir = client
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "bench")
    monkeypatch.delenv("STEWIE_ALLOW_TELEOP", raising=False)
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())
    assert r.status_code == 403, r.text
    assert "rc.teleop_refused" in _audit_actions(data_dir)


def test_bench_profile_teleop_with_grant_is_allowed_and_audited(client, monkeypatch):
    """SF-02 acceptance: on a dev/bench profile WITH the explicit teleop grant, the mission-less GoTo is
    accepted (200) and the grant is audit-logged."""
    c, key, data_dir = client
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "bench")
    monkeypatch.setenv("STEWIE_ALLOW_TELEOP", "1")
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto())
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "goto"
    assert "rc.teleop_grant" in _audit_actions(data_dir)


def test_mission_bound_goto_is_unchanged_by_sf02(client, monkeypatch):
    """AG-08 regression: a GoTo that CITES a published (live) mission is NOT mission-less teleop, so the
    SF-02 gate does not apply -- it is accepted (200) even on a LIVE/OPERATE profile with no teleop grant,
    and neither SF-02 audit action fires."""
    c, key, data_dir = client
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "operate")
    monkeypatch.delenv("STEWIE_ALLOW_TELEOP", raising=False)
    r = c.post("/rc/command", headers={"X-API-Key": key}, json=_goto("Live Pad"))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == "goto"
    actions = _audit_actions(data_dir)
    assert "rc.teleop_refused" not in actions and "rc.teleop_grant" not in actions
