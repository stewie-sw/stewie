"""Step 3 (gap W1): the SIM execute path produces WORLD TRANSACTIONS.

/executive/run already drives a RELEASED plan through run_closed_loop -> run_sim_execution (SIM-labeled,
persisted) -- but it committed NO WorldTransaction, so a SIM mission left no record in the canonical
DT-01 log. Step 3 wires it through the WorldStateService (step 1): the released plan, one transaction
per ExecutionEvent (FS-04: a leg event per executed leg + a terminal completed/safed event), all
SIM-labeled. ``execution_events`` is the pure run -> typed-event converter; ``commit_sim_run`` is the
server commit loop the live path (step 4) reuses.

Real run_sim_execution output + real planner/sim via /executive/run -- no mocks.
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.contracts import ExecutionEvent
from stewie.server.world_state import WorldStateService, commit_sim_run
from stewie.twin import versioned as vt


def _twin() -> vt.TwinStore:
    rng = np.random.default_rng(11)
    return vt.TwinStore(rng.normal(0.0, 0.05, (32, 32)), cell_m=0.5)


# ---- (1) execution_events: run -> typed ExecutionEvent timeline ---------------------------------

def test_execution_events_one_leg_event_each_plus_completed_terminal():
    from lode.sim_execution import execution_events
    run = {"label": "sim", "final_state": "completed", "safed": False, "n_legs_total": 3,
           "executed_legs": [{"leg": 0, "action": "continue"}, {"leg": 1, "action": "persist"},
                             {"leg": 2, "action": "continue"}]}
    evs = execution_events(run, vehicle_id="ipex")
    assert all(isinstance(e, ExecutionEvent) for e in evs)
    assert len(evs) == 4                                  # 3 leg events + 1 terminal
    assert [e.kind for e in evs[:3]] == ["leg", "leg", "leg"]
    assert all(e.outcome == "ok" for e in evs[:3])        # continue/persist -> ok
    assert evs[-1].kind == "acceptance" and evs[-1].outcome == "ok"   # completed terminal


def test_execution_events_safed_run_terminates_with_a_safe_event():
    from lode.sim_execution import execution_events
    run = {"label": "sim", "final_state": "safed", "safed": True, "n_legs_total": 5,
           "executed_legs": [{"leg": 0, "action": "continue"}]}
    evs = execution_events(run)
    assert evs[-1].kind == "safe" and evs[-1].outcome == "safed"


# ---- (2) commit_sim_run: the run becomes world transactions through the service ------------------

def test_commit_sim_run_commits_plan_then_one_per_event():
    run = {"label": "sim", "final_state": "completed", "safed": False, "n_legs_total": 2,
           "executed_legs": [{"leg": 0, "action": "continue"}, {"leg": 1, "action": "continue"}]}
    wss = WorldStateService(twin=_twin())
    n = commit_sim_run(wss, run, mission="LSP-1", site="haworth", body="moon", plan_id="pad-1")
    assert n == wss.transaction_count()
    assert n == 1 + 3                                     # plan + (2 leg events + 1 terminal)
    last = wss.latest()
    assert last.plan_id == "pad-1" and last.mission == "LSP-1"
    assert "SIM" in last.provenance                       # SIM-labeled
    assert wss.verify_chain()


# ---- (3) /executive/run now produces transactions end-to-end ------------------------------------

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


_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]
H = {"X-API-Key": "test-key"}


def test_executive_run_records_world_transactions(client):
    before = client.get("/world/transaction", headers=H).json()
    assert before["committed"] is False

    r = client.post("/executive/run", headers=H, json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["label"] == "sim"   # SIM-labeled run

    after = client.get("/world/transaction", headers=H).json()
    assert after["committed"] is True
    assert after["count"] >= 1                             # at least the released-plan transaction
    assert "SIM" in after["transaction"]["provenance"]     # the run's transactions are SIM-labeled
