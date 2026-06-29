"""#245 route TDD: POST /executive/run executes a RELEASED build plan as a SIM run end-to-end
(intent_from_orders -> RELEASED -> run_closed_loop -> run_sim_execution), operator-gated and SIM-labeled.
Unauthenticated -> locked; a queue with no build orders -> 400. Uses the REAL planner + sim (no mocks)."""
from fastapi.testclient import TestClient

_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]


def _client(monkeypatch, tmp_path, *, dev_open):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    if dev_open:
        monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    else:
        monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_run_executes_released_plan_sim_labeled(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=True)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["label"] == "sim"               # the run output is SIM, never LIVE
    assert j["final_state"] in ("completed", "safed")            # the live chain reached a terminal state
    assert j["transitions"][:2] == ["armed", "executing"]        # ARMED -> EXECUTING actually happened


def test_run_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=False)           # no key, no dev-open -> locked
    assert c.post("/executive/run", json={"orders": _ORDERS}).status_code in (401, 403, 503)


def test_run_rejects_a_queue_with_no_build_orders(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=True)
    r = c.post("/executive/run", json={"orders": [{"kind": "goto", "x": 1.0, "y": 1.0, "action": "wp"}]})
    assert r.status_code == 400                                  # nothing to build -> rejected, no fabrication
