"""FS-19: the end-to-end observability ledger. Every mutating contract call lands in the audit ledger
with a correlation id, latency, status, and error code; correlation ids thread through the semantic
events logged inside the same request; secrets / tokens / passwords are NEVER written; payloads are
recorded as content hashes, not contents.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_observability_ledger.py -q
"""
from __future__ import annotations

import importlib
import json
import os

import pytest


@pytest.fixture()
def svc(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import services as SVC
    importlib.reload(SVC)
    SVC.reset_audit_health()
    yield SVC, tmp_path
    SVC.set_correlation_id(None)


def _events(tmp_path):
    p = os.path.join(str(tmp_path), "events.jsonl")
    return [json.loads(ln) for ln in open(p).read().splitlines()] if os.path.exists(p) else []


def test_correlation_id_is_distinct_and_round_trips(svc):
    SVC, _ = svc
    a, b = SVC.new_correlation_id(), SVC.new_correlation_id()
    assert a != b and len(a) >= 8
    SVC.set_correlation_id(a)
    assert SVC.get_correlation_id() == a


def test_log_event_auto_attaches_the_active_correlation_id(svc):
    SVC, tmp = svc
    SVC.set_correlation_id("cid-123")
    SVC.log_event("alice", "mission.save", "pad1")
    rec = _events(tmp)[-1]
    assert rec["correlation_id"] == "cid-123", "the semantic event did not inherit the request correlation id"


def test_log_event_writes_structured_fields(svc):
    SVC, tmp = svc
    SVC.log_event("svc", "http.post", "/missions", status=200, latency_ms=12.5, error_code=None)
    rec = _events(tmp)[-1]
    assert rec["status"] == 200 and rec["latency_ms"] == 12.5 and rec["action"] == "http.post"


def test_secrets_are_redacted_never_written(svc):
    SVC, tmp = svc
    SVC.log_event("alice", "auth.login", "x", password="hunter2", api_key="sk-secret", note="ok")
    line = open(os.path.join(str(tmp), "events.jsonl")).read()
    assert "hunter2" not in line and "sk-secret" not in line, "a secret leaked into the audit ledger"
    rec = _events(tmp)[-1]
    assert rec["password"] == "[redacted]" and rec["api_key"] == "[redacted]"
    assert rec["note"] == "ok", "redaction clobbered a non-secret field"


def test_redact_is_recursive(svc):
    SVC, _ = svc
    out = SVC.redact({"a": 1, "token": "t", "nested": {"secret": "s", "ok": 2}, "list": [{"csrf": "z"}]})
    assert out["a"] == 1 and out["token"] == "[redacted]"
    assert out["nested"]["secret"] == "[redacted]" and out["nested"]["ok"] == 2
    assert out["list"][0]["csrf"] == "[redacted]"


def test_hash_payload_hides_content_and_is_stable(svc):
    SVC, _ = svc
    h1 = SVC.hash_payload({"lat": -89.0, "lon": 0.0})
    h2 = SVC.hash_payload({"lat": -89.0, "lon": 0.0})
    h3 = SVC.hash_payload({"lat": -88.0, "lon": 0.0})
    assert h1 == h2 and h1 != h3, "hash is not a stable content fingerprint"
    assert "89" not in h1 and len(h1) >= 12, "the hash carries raw content (must be a digest)"


def test_mutating_request_is_logged_with_latency_and_correlation(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")           # loopback dev-open: the POST is not key-gated
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    r = c.post("/sense", json={"true_mass_kg": 20.0, "noise_frac": 0.0})
    cid = r.headers.get("X-Correlation-Id")
    assert cid, "the response carries no correlation id header"
    evs = _events(tmp_path)
    http = [e for e in evs if str(e.get("action", "")).startswith("http.")]
    assert http, "the mutating request was not recorded in the observability ledger"
    e = http[-1]
    assert e["correlation_id"] == cid, "the ledger event and the response header disagree on the correlation id"
    assert isinstance(e.get("latency_ms"), (int, float)) and e["latency_ms"] >= 0
    assert "status" in e, "the ledger event has no result status"


def test_get_healthz_is_not_logged_as_an_event(monkeypatch, tmp_path):
    # the ledger records contract calls + decisions, not every GET -- health/metrics polling must not flood it
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from fastapi.testclient import TestClient
    import stewie.server.server as SRV
    importlib.reload(SRV)
    c = TestClient(SRV.app)
    c.get("/healthz")
    evs = _events(tmp_path)
    assert not [e for e in evs if e.get("target") == "/healthz"], "healthz polling flooded the ledger"
