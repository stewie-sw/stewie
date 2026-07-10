"""[dispatch-audit R6a] a failed SIM run leaves NO orphan world-journal records.

The audit (finding #6) found /executive/run committed the released-plan + per-leg records to the append-only
world journal via commit_sim_run BEFORE the terrain fold (_remember_sim_terrain); if the fold then failed the
route returned 500 but those plan/leg records REMAINED -- durable orphans a retry would duplicate. The world
journal is append-only + hash-chained (a tamper-evident invariant), so records cannot be truncated; the fix is
a PREPARE/COMMIT reorder: fold the fallible terrain FIRST (no journal write), then journal plan+legs+terrain.
A fold failure therefore leaves the journal untouched.

Real store + the FastAPI app via a TestClient; the terrain-fold failure is injected at mission_terrain_delta.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def _release(c, key) -> str:
    r = c.post("/executive/release-plan", headers={"X-API-Key": key}, json={
        "body": "moon", "mission_id": "M-r6", "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert r.status_code == 200, r.text
    return r.json()["signed_revision"]["content_hash"]


def test_a_failing_terrain_fold_writes_no_orphan_journal_records(client, monkeypatch):  # [dispatch-audit R6a]
    c, key = client
    ch = _release(c, key)
    from stewie.server import state
    wss = state.world_state_service()
    before = wss.transaction_count()

    # inject a failure in the FALLIBLE terrain fold (the prepare step). Before R6a, commit_sim_run had already
    # journaled the plan + legs by the time this raised -> durable orphans.
    import lode.planner_acceptance as PA

    def _boom(_mission):
        raise RuntimeError("terrain fold failed (injected)")

    monkeypatch.setattr(PA, "mission_terrain_delta", _boom)

    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": ch, "site": "haworth"})
    assert r.status_code == 500, r.text                       # the fold failure surfaces (not swallowed)
    # R6a: the append-only world journal is UNTOUCHED -- the fold ran BEFORE any commit_sim_run journal write.
    assert wss.transaction_count() == before, "orphan plan/leg journal records were committed before the failed fold"


def test_a_successful_run_still_advances_the_journal_and_remembers_terrain(client):  # [dispatch-audit R6a]
    """The reorder preserves the happy path: a completed terrain-changing run journals the plan + legs + the
    as-built terrain record (the count advances), and the fold is remembered."""
    c, key = client
    ch = _release(c, key)
    from stewie.server import state
    wss = state.world_state_service()
    before = wss.transaction_count()
    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": ch, "site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.json()["final_state"] in ("completed", "safed")
    # plan + >=1 leg + (if not safed) the as-built terrain record were journaled.
    assert wss.transaction_count() > before
