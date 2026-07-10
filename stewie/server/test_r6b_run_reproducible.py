"""[dispatch-audit R6b] a persisted SIM run carries its reproducibility provenance and an HONEST playback
label (finding #10).

The audit found a persisted run retained only terminal state + ordinal actions -- not the signed plan hash,
the physics backend, or any acknowledgement that the SSE/QWC2 rover animation is a plan-interpolated FORECAST
rather than executed per-vehicle pose telemetry. R6b enriches the run record with the immutable released
revision it executed (R2 content_hash -- re-fetchable + re-runnable), the reviewed physics backend (R4), and
``trajectory_kind: "forecast"`` (the honest label), surfaced on the SSE done event. The larger piece -- real
per-leg pose/provenance telemetry that makes playback an EXECUTED trajectory -- is deferred, not claimed.
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
        "body": "moon", "mission_id": "M-r6b", "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert r.status_code == 200, r.text
    return r.json()["signed_revision"]["content_hash"]


def test_persisted_run_carries_reproducibility_provenance_and_forecast_label(client):  # [dispatch-audit R6b]
    c, key = client
    ch = _release(c, key)
    run = c.post("/executive/run", headers={"X-API-Key": key},
                 json={"revision_hash": ch, "site": "haworth"}).json()
    run_id = run["run_id"]
    g = c.get(f"/executive/run/{run_id}", headers={"X-API-Key": key}).json()
    assert g["ok"] is True
    assert g["bound_revision"] == ch                 # the immutable signed revision this run executed (reproducible)
    assert g["physics_backend"] == "tier2_numpy"     # the reviewed physics backend (R4)
    assert g["trajectory_kind"] == "forecast"        # HONEST: playback is plan-interpolated, not executed pose telemetry


def test_sse_done_event_carries_the_forecast_label(client):  # [dispatch-audit R6b]
    c, key = client
    ch = _release(c, key)
    run_id = c.post("/executive/run", headers={"X-API-Key": key},
                    json={"revision_hash": ch, "site": "haworth"}).json()["run_id"]
    r = c.get(f"/executive/run/{run_id}/stream?interval_s=0", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    assert '"trajectory_kind": "forecast"' in r.text   # the terminal done event names the playback kind
