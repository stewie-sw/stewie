"""#245 route TDD: POST /executive/run executes a RELEASED build plan as a SIM run end-to-end
(intent_from_orders -> RELEASED -> run_closed_loop -> run_sim_execution), DIRECTOR-gated (#276: it drives
the plan to RELEASED, a director-authority MO-02 edge) and SIM-labeled. Unauthenticated -> locked; an
authenticated operator -> 403; a queue with no build orders -> 400. Uses the REAL planner + sim (no mocks)."""
import importlib

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


def test_run_malformed_order_field_is_400_not_500(monkeypatch, tmp_path):  # #300 (#275/#284 class)
    """An order field that is a list/object where a number is expected (e.g. x=[1,2]) must be a client
    error (400), not an uncaught TypeError -> 500 inside intent_from_orders."""
    c = _client(monkeypatch, tmp_path, dev_open=True)
    bad = [{"kind": "cut", "x": [1, 2], "y": 10.0, "action": "dig", "footprint_m2": 4.0, "depth_m": 0.3}]
    r = c.post("/executive/run", json={"orders": bad, "site": "haworth"})
    assert r.status_code == 400, r.text


def test_run_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=False)           # no key, no dev-open -> locked
    assert c.post("/executive/run", json={"orders": _ORDERS}).status_code in (401, 403, 503)


def test_run_is_director_gated_an_operator_is_refused(monkeypatch, tmp_path):
    """#276 (two-role): /executive/run drives the plan to RELEASED, a director-authority MO-02 signing edge,
    so an authenticated OPERATOR must be refused (403) -- the prior require_role('operator') let an operator
    forge a director-signed release. A director (api-key identity) still runs the SIM."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_API_KEY", "dir-key")              # the api-key identity == director
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as SRV
    importlib.reload(SRV)
    from stewie.server import auth as AUTH
    OPS.create_active("op@x.com", "operator-pw-1", role="operator", by="test")
    tok = AUTH.issue_token("op@x.com")
    c = TestClient(SRV.app)
    body = {"orders": _ORDERS, "site": "haworth"}
    r_op = c.post("/executive/run", headers={"Authorization": f"Bearer {tok}"}, json=body)
    assert r_op.status_code == 403, f"an operator must NOT drive a director release (#276); got {r_op.status_code}: {r_op.text}"
    r_dir = c.post("/executive/run", headers={"X-API-Key": "dir-key"}, json=body)
    assert r_dir.status_code == 200, r_dir.text
    importlib.reload(SRV)                                        # restore default app for other modules


def test_run_rejects_a_queue_with_no_build_orders(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=True)
    r = c.post("/executive/run", json={"orders": [{"kind": "goto", "x": 1.0, "y": 1.0, "action": "wp"}]})
    assert r.status_code == 400                                  # nothing to build -> rejected, no fabrication


def test_run_persists_and_is_retrievable(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=True)
    r = c.post("/executive/run", json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    g = c.get(f"/executive/run/{run_id}")
    assert g.status_code == 200 and g.json()["run_id"] == run_id            # round-trips the recorded run
    assert g.json()["final_state"] == r.json()["final_state"]
    assert c.get("/executive/run/nope").status_code == 404                  # unknown run -> 404


def test_save_run_is_per_owner_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    OBJ.save_run("r1", {"final_state": "completed"}, owner="alice@x")
    assert OBJ.load_run("r1", owner="alice@x")["final_state"] == "completed"
    assert OBJ.load_run("r1", owner="bob@x") is None                        # per-owner isolation


def test_run_store_is_capped_per_owner_oldest_pruned(monkeypatch, tmp_path):  # #307
    """The per-owner SIM-run store is FIFO-capped: writing more than _RUN_MAX runs prunes the oldest, so a
    long operator session cannot grow the run dir without bound. The newest stay retrievable; the oldest 404."""
    import os
    import time
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    monkeypatch.setattr(OBJ, "_RUN_MAX", 3)
    for i in range(6):
        OBJ.save_run(f"run{i}", {"final_state": "completed", "i": i}, owner="op@x")
        time.sleep(0.01)                                          # distinct mtimes -> well-defined FIFO order
    d = OBJ._ns_dir("runs", "sandbox", "op@x")
    assert len([f for f in os.listdir(d) if f.endswith(".json")]) == 3      # capped at _RUN_MAX
    assert OBJ.load_run("run5", owner="op@x") is not None                   # newest retained
    assert OBJ.load_run("run0", owner="op@x") is None                       # oldest pruned -> 404s on retrieval
