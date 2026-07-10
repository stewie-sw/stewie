"""Loop #2: live SSE playback of a SIM run. GET /executive/run/{run_id}/stream replays the persisted
run's FS-04 ExecutionEvent timeline as Server-Sent-Events (one event per leg + a terminal `done`), so
the cockpit Execute pane can play the run back as it happened. Owner-scoped + operator-gated, mirroring
GET /executive/run/{run_id}. Real run via the planner/sim -- no mocks; interval_s=0 streams instantly
for the test."""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]
H = {"X-API-Key": "test-key"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _sse_events(text: str) -> list[dict]:
    return [json.loads(ln[6:]) for ln in text.splitlines() if ln.startswith("data: ")]


def test_run_stream_replays_events_then_done(client):
    run_id = client.post("/executive/run", headers=H,
                         json={"orders": _ORDERS, "site": "haworth"}).json()["run_id"]
    body = client.get(f"/executive/run/{run_id}/stream?interval_s=0", headers=H).text
    events = _sse_events(body)
    kinds = [e.get("kind") for e in events if "kind" in e]
    assert "leg" in kinds                                   # at least one per-leg execution event
    assert events[-1].get("done") is True                  # terminal done event last
    assert events[-1].get("final_state") in ("completed", "safed")
    # every non-terminal event is a typed FS-04 event with an outcome
    for e in events[:-1]:
        assert e["kind"] in ("command", "leg", "safe", "acceptance") and "outcome" in e


def test_run_stream_unknown_id_is_404(client):
    assert client.get("/executive/run/deadbeef/stream?interval_s=0", headers=H).status_code == 404


def test_run_stream_requires_auth(client, monkeypatch):
    run_id = client.post("/executive/run", headers=H,
                         json={"orders": _ORDERS, "site": "haworth"}).json()["run_id"]
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    assert client.get(f"/executive/run/{run_id}/stream?interval_s=0").status_code in (401, 403)


def test_run_stream_resumes_from_last_event_id(client):
    """[REQ:FS-31] Execute-and-watch SSE stream + resume: GET /executive/run/{id}/stream emits
    text/event-stream legs each carrying `id: <leg>`, so a reconnecting EventSource sending Last-Event-ID
    replays ONLY the legs AFTER that id -- a transient blip no longer re-plays the whole run from leg 0."""
    run_id = client.post("/executive/run", headers=H,
                         json={"orders": _ORDERS, "site": "haworth"}).json()["run_id"]
    full = client.get(f"/executive/run/{run_id}/stream?interval_s=0", headers=H).text
    ids = [ln[4:] for ln in full.splitlines() if ln.startswith("id: ")]
    assert ids[0] == "0"                                     # legs are id'd from 0
    assert len(ids) >= 2                                     # >=1 leg + the terminal done
    resumed = client.get(f"/executive/run/{run_id}/stream?interval_s=0",
                         headers={**H, "Last-Event-ID": "0"}).text
    resumed_ids = [ln[4:] for ln in resumed.splitlines() if ln.startswith("id: ")]
    assert "0" not in resumed_ids                            # the already-seen leg is skipped
    assert len(resumed_ids) == len(ids) - 1                  # exactly one fewer event (leg 0 dropped)
