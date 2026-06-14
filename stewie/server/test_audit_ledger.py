"""S-10 regression: the audit ledger must be a locked, durable append with rotation and VISIBLE
failure.

The audit found `services.log_event` appended without a lock, no fsync/durability, no rotation, and
SUPPRESSED every OSError -- so concurrent events could interleave/lose lines, a disk error erased the
security trail silently, and the file grew without bound.

This pins:
 - concurrent writers produce N intact, parseable JSON lines (no interleaving/loss),
 - a write failure is OBSERVABLE (a degraded flag / counter the health surface can read), not silently
   swallowed,
 - the ledger ROTATES when it grows past the size cap (the old segment is preserved).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_audit_ledger.py -q
"""
from __future__ import annotations

import importlib
import json
import os
import threading

import pytest


@pytest.fixture()
def svc(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import services as SVC
    importlib.reload(SVC)
    SVC.reset_audit_health()
    return SVC, tmp_path


def _events_path(tmp_path):
    return os.path.join(str(tmp_path), "events.jsonl")


def test_concurrent_appends_are_intact_and_parseable(svc):
    SVC, tmp_path = svc
    N = 200

    def writer(i):
        SVC.log_event(f"actor{i}", "auth.login", str(i))

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = open(_events_path(tmp_path)).read().splitlines()
    assert len(lines) == N, f"lost/duplicated audit lines under concurrency: {len(lines)} != {N}"
    # every line must be a complete, parseable JSON object (no interleaved partial writes)
    actors = set()
    for ln in lines:
        rec = json.loads(ln)        # raises if a line was interleaved/corrupt
        actors.add(rec["actor"])
    assert len(actors) == N, "audit records interleaved (duplicate/garbled actors)"


def test_write_failure_is_visible_not_swallowed(svc, monkeypatch):
    SVC, _tmp = svc
    # force the append to fail (the open/write path raises) and assert it is RECORDED as degraded
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(SVC, "_audit_append_raw", boom)
    SVC.log_event("actor", "auth.login", "x")          # must not raise (never breaks the request)
    h = SVC.audit_health()
    assert h["degraded"] is True and h["failures"] >= 1, (
        "an audit write failure was silently swallowed (S-10)")


def test_ledger_rotates_past_the_size_cap(svc, monkeypatch):
    SVC, tmp_path = svc
    monkeypatch.setenv("STEWIE_AUDIT_MAX_BYTES", "2048")   # tiny cap so a few events trigger rotation
    for i in range(200):
        SVC.log_event(f"actor{i}", "auth.login", "padding-padding-padding-padding-padding")
    d = os.path.dirname(_events_path(tmp_path))
    rotated = [n for n in os.listdir(d) if n.startswith("events.jsonl.") and n != "events.jsonl"]
    assert rotated, "the audit ledger never rotated past its size cap (S-10)"
    # the live file stays bounded (well under, say, 10x the cap)
    assert os.path.getsize(_events_path(tmp_path)) < 20480
