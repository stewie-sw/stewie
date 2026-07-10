"""[dispatch-audit R2 / F1] /executive/run BINDS an immutable released revision by content_hash and
executes the FROZEN signed plan -- it no longer rebuilds the executed mission from mutable browser orders.

The audit (design/STEWIE_DISPATCH_AGENT_AUDIT_2026-07-09.md, F1 CRITICAL) found /executive/run took
``orders: list[dict]`` and built the executed mission via ``mission_from_dict(orders)`` -- the RAW client
geometry -- while separately deriving the signed revision from those orders. So the executed plan was NOT
provably the signed one (the content_hash is over the compiled INTENT, whose geometry is mass-normalized;
the raw orders carry a different footprint/depth for the same mass).

R2 slice 1 (F1): a run may pass ``revision_hash`` (an R1 content_hash). When it does, the run FETCHES the
frozen revision from the durable store (R1), reconstructs the signed intent, and executes
``compile_intent(frozen_intent).mission`` -- the exact signed content -- reporting ``bound_revision`` = the
same hash. An unknown hash is refused. The legacy orders path still works (unbound: ``bound_revision`` null)
for backward compatibility until the cockpit posts a revision id (R7). Real store + app via TestClient.
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


def _plan_payload():
    return {
        "body": "moon", "mission_id": "M-r2-1",
        "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2},
            {"action": "wp1", "kind": "goto", "x": 0.0, "y": 0.0},
        ],
    }


def _release(c, key) -> str:
    r = c.post("/executive/release-plan", headers={"X-API-Key": key}, json=_plan_payload())
    assert r.status_code == 200, r.text
    return r.json()["signed_revision"]["content_hash"]


def test_run_binds_a_released_revision_by_hash_and_reports_it(client):  # [dispatch-audit R2]
    """A run driven by ``revision_hash`` executes the FROZEN revision and reports the SAME hash -- and needs
    NO orders in the request (the plan comes from the signed revision, not the browser)."""
    c, key = client
    ch = _release(c, key)
    r = c.post("/executive/run", headers={"X-API-Key": key}, json={"revision_hash": ch, "site": "haworth"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["bound_revision"] == ch                 # release + run report the SAME immutable hash
    assert body["final_state"] in ("completed", "safed")   # the frozen plan actually executed
    assert body["run_id"]


def test_bound_run_ignores_client_orders_and_executes_the_signed_plan(client):  # [dispatch-audit R2]
    """When a revision_hash is bound, the run executes the SIGNED content regardless of any orders the
    client also posts -- a tampered order queue cannot change what runs."""
    c, key = client
    ch = _release(c, key)
    tampered = [{"action": "evil", "kind": "cut", "x": 99.0, "y": 99.0, "footprint_m2": 400.0, "depth_m": 2.0}]
    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": ch, "orders": tampered, "site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.json()["bound_revision"] == ch             # bound to the signed revision, not the tampered orders


def test_run_rejects_an_unknown_revision_hash(client):  # [dispatch-audit R2]
    c, key = client
    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": "0" * 64, "site": "haworth"})
    assert r.status_code == 400, r.text
    assert r.json()["ok"] is False


def test_unbound_orders_run_still_works_and_reports_null_bound(client):  # [dispatch-audit R2]
    """Backward compatibility: the legacy orders path (no revision_hash) still runs, reporting bound_revision
    null so a consumer can see the run was NOT bound to a released revision (the R7 frontend will migrate)."""
    c, key = client
    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"orders": _plan_payload()["orders"], "site": "haworth"})
    assert r.status_code == 200, r.text
    assert r.json()["bound_revision"] is None
    assert r.json()["final_state"] in ("completed", "safed")
