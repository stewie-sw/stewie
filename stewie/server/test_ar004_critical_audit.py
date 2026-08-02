"""[AR-004] A critical action must be durably recorded BEFORE it takes effect, or not happen at all.

The 2026-07-16 review: `services.log_event` fsyncs a JSONL line and records degraded health on OSError,
but its contract is explicitly "never raises into the request path" -- and release, command, re-arm,
authentication and administrative routes all called it AFTER the action. A disk-full, permission,
rotation or filesystem failure therefore PERMITTED the operation and merely flipped an in-process flag.
For a rover command that means the rover moved with no durable record that it was told to, and state
and audit disagree after a crash.

`critical_event` inverts both properties for the accountable class: the record is written first, and a
write failure raises `AuditWriteRefused` so the caller refuses (503) rather than proceeding.

WHAT THIS DOES NOT CLAIM. AR-004 also requires state+audit in ONE database transaction, an outbox
dispatcher with no duplicate actuation on retry, external alerting on backlog, and periodic signed
audit roots anchored off-host. None of that is built. This closes the fail-OPEN half only; the
atomicity and external-anchor halves remain open, and the module docstring of `critical_event` says so.

Run: <venv>/bin/python -m pytest stewie/server/test_ar004_critical_audit.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from stewie.server import services as SVC


def test_criticality_classification_covers_the_reviews_named_actions():
    """The review named command, release, approval, key/role admin and safety-state as accountable."""
    for action in ("rc.command", "rc.goto", "rc.estop", "rc.safe", "executive.release_plan",
                   "executive.advance", "operator.approve", "admin.role", "twin.publish"):
        assert SVC.is_critical_action(action), f"{action} should be accountable"


def test_ordinary_telemetry_is_not_classified_critical():
    """Fail-closed must stay narrow -- an ordinary request must never be refused for a telemetry line."""
    for action in ("plan.render", "mission.save", "rc.plan_ros", "world.points"):
        assert not SVC.is_critical_action(action), f"{action} must not be fail-closed"


def test_critical_event_raises_when_the_record_cannot_be_written(monkeypatch, tmp_path):
    """The core inversion: an unwritable audit makes the call fail, not degrade."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))

    def _boom(_line):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(SVC, "_audit_append_raw", _boom)
    with pytest.raises(SVC.AuditWriteRefused, match="could not be durably written"):
        SVC.critical_event("director:alice@x.com", "rc.command", "leg-1")


def test_log_event_stays_fail_open_for_ordinary_actions(monkeypatch, tmp_path):
    """Regression guard: making critical actions fail-closed must not break ordinary telemetry."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))

    def _boom(_line):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(SVC, "_audit_append_raw", _boom)
    SVC.log_event("op@x.com", "plan.render", "pad-a")        # must NOT raise


def test_a_failed_audit_records_degraded_health_too(monkeypatch, tmp_path):
    """Refusing is not enough -- the operator-visible degraded flag must still be set."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    SVC.reset_audit_health() if hasattr(SVC, "reset_audit_health") else None

    def _boom(_line):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(SVC, "_audit_append_raw", _boom)
    with pytest.raises(SVC.AuditWriteRefused):
        SVC.critical_event("director:alice@x.com", "executive.release_plan", "M-1")
    assert SVC.audit_health()["degraded"] is True


def test_a_rover_command_is_refused_when_its_audit_cannot_be_written(monkeypatch, tmp_path):
    """END TO END, at the actuation boundary: no durable record -> no command submitted.

    This is the AR-004 scenario that mattered most: previously the command was submitted first and
    logged after, so the rover moved and the record silently did not exist.
    """
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    from stewie.server import objects as OBJ
    OBJ.save_mission("Live Pad", {"body": "moon", "orders": []}, owner="op@x.com", namespace="live")

    import time as _t

    from stewie.bridge import rc_contract as C
    from stewie.server.routers import rc as RCR
    saved = RCR._RC_WATCHDOG
    RCR._RC_WATCHDOG = C.SafingWatchdog(RCR._RC_BACKEND, deadline_s=5.0)
    RCR._RC_WATCHDOG.feed(now=_t.monotonic())
    submitted: list = []
    real_submit = RCR._RC_WATCHDOG.submit
    RCR._RC_WATCHDOG.submit = lambda cmd, now=None: (submitted.append(cmd), real_submit(cmd, now=now))[1]

    def _boom(_line):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(SVC, "_audit_append_raw", _boom)
    try:
        c = TestClient(srv.app)
        r = c.post("/rc/command", headers={"X-API-Key": "test-key"},
                   json={"kind": "goto", "goal_row": 5, "goal_col": 6, "mission": "Live Pad"})
        assert r.status_code == 503, f"command was accepted despite an unwritable audit: {r.status_code}"
        assert submitted == [], "the rover command was SUBMITTED with no durable audit record"
    finally:
        RCR._RC_WATCHDOG = saved
        importlib.reload(srv)
