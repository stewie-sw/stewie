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
    # plumbing fixture: this twin is never patched/read by these tests (only its version/hash identity
    # is linked), so a zero base is the cleanest opaque vessel -- no fabricated heights at all.
    return vt.TwinStore(np.zeros((32, 32), dtype=float), cell_m=0.5)


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


def test_execution_events_marks_a_nonnominal_leg_blocked():  # gap G5
    """A held/replanned leg (pause/relocalize/replan/reverse) is surfaced as outcome='blocked', not
    hidden as 'ok' -- so a reader can tell a clean run from one that recovered."""
    from lode.sim_execution import execution_events
    run = {"label": "sim", "final_state": "completed", "safed": False, "n_legs_total": 2,
           "executed_legs": [{"leg": 0, "action": "continue"}, {"leg": 1, "action": "replan_local"}]}
    evs = execution_events(run)
    assert evs[0].outcome == "ok" and evs[1].outcome == "blocked"


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
    # plan(1) + one per executed leg + terminal + as-built terrain record + final belief (the
    # execute->REMEMBER loop, gap N1/N2): a completed terrain-changing run remembers what it built.
    assert after["count"] == len(body["executed_legs"]) + 4
    assert "SIM" in after["transaction"]["provenance"]

    # the run REMEMBERED its terrain: the site's TerrainMemory now holds the mission, so the NEXT /plan
    # reads the remembered surface via CurrentTerrainView. This is the loop-close.
    tm = client.get("/twin/terrain/haworth", headers=H).json()
    assert tm["recorded"] is True and tm["version"] >= 1
    # and a world transaction advanced the conserved authority off genesis (the SIM as-built)
    txns = client.get("/world/transactions?limit=20", headers=H).json()["transactions"]
    asbuilt = [t for t in txns if "SIM as-built" in t["provenance"]]
    assert asbuilt and asbuilt[-1]["authority_sha"] != "genesis" and len(asbuilt[-1]["authority_sha"]) == 64
    assert any("SIM run belief" in t["provenance"] for t in txns)   # final belief committed (was dead code)     # the run's transactions are SIM-labeled


def test_executive_run_rolls_back_on_a_world_log_failure(client, monkeypatch):  # gap G1 / DT-03
    """DT-03: the SIM run's world-state commit is atomic with persisting the run. If the world-state commit
    fails (here the accessor raises, as a corrupt world journal would), /executive/run surfaces 500 and does
    NOT persist the run ahead of the failed world log -- nothing runs ahead of /world/transaction (replaces
    the old best-effort 200 that left the run record ahead)."""
    from stewie.server import state as S
    monkeypatch.setattr(S, "world_state_service", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/executive/run", headers=H, json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 500 and r.json()["ok"] is False
