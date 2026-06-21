"""MO-WIRE [REQ:MO-02] POST /executive/advance: the director-gated plan->executive advance route. A real
MO-01 MissionIntent is posted; the route drives a fresh MO-02 MissionExecutive through the lifecycle
(via lode.mission_lifecycle) and returns the reached state + the signed immutable revision + REAL evidence
(plan_id, forward_compare). Director-gated: no key -> 401; an api-key (==director) advances to RELEASED.
Real store + the FastAPI app via a TestClient; nothing synthetic.

Run: <venv>/bin/python -m pytest stewie/server/test_executive_route.py -q
"""
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


def _intent_payload():
    return {
        "mission_id": "M-route-1", "revision": 0, "statement": "prepare the pad",
        "objectives": [{
            "objective_id": "O-001", "revision": 0, "statement": "flatten the landing pad",
            "rationale": "lander needs a level surface", "priority": "primary", "mandatory": True,
            "target_row": 100.0, "target_col": 120.0, "frame": "MOON_ME",
            "acceptance": [{"criterion_id": "acc1", "statement": "pad flat",
                            "measurable": "as-built RMSE <= 0.02 m", "sensor": "dem_overlay"}],
            "confidence_required": 0.9, "material_budget_kg": 50.0,
            "contingency": {"policy": "replan", "detail": "retry from charger"},
            "approver": "director", "evidence": "design memo 2026-06-20",
        }],
        "constraints": [], "task_graph_ref": "planir-001",
    }


def test_advance_requires_director_role(client):
    c, _key = client
    # no key configured-but-not-supplied -> require_auth fails closed (401), so the route is not director-open
    r = c.post("/executive/advance", json=_intent_payload())
    assert r.status_code == 401, r.text


def test_advance_reaches_released_with_signed_revision_and_evidence(client):
    c, key = client
    r = c.post("/executive/advance", headers={"X-API-Key": key}, json=_intent_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["state"] == "released"
    assert body["label"] == "sim"                     # MO-04: planned/rehearsed on the sim authority
    rev = body["signed_revision"]
    assert rev is not None and rev["signed_by"] == "director"
    assert len(rev["content_hash"]) == 64             # sha256 hex -> a real signed immutable revision
    # REAL evidence attached at the transitions
    assert body["evidence"]["plan_id"]
    fc = body["evidence"]["forward_compare"]
    assert fc["recommended"] in {f["algorithm"] for f in fc["futures"]}
    assert all(f["time_s"] > 0.0 for f in fc["futures"])
    # the transition log records the legal head with its authorizing roles
    assert [t["to"] for t in body["transitions"]] == ["analyzed", "rehearsed", "reviewed", "released"]
    assert [t["role"] for t in body["transitions"]] == ["planner", "operator", "reviewer", "director"]


def test_advance_rejects_uncompilable_intent_with_400(client):
    c, key = client
    payload = _intent_payload()
    # drop the work geometry -> the mandatory objective cannot be sized -> compile_intent raises -> 400
    del payload["objectives"][0]["material_budget_kg"]
    r = c.post("/executive/advance", headers={"X-API-Key": key}, json=payload)
    assert r.status_code == 400, r.text
    assert r.json()["ok"] is False


def test_advance_rejects_malformed_intent(client):
    c, key = client
    # a MissionIntent with no mission_id is rejected by the pydantic contract boundary; the app's global
    # RequestValidationError handler surfaces it in the {ok:false,error} envelope at 400 (not FastAPI's 422)
    r = c.post("/executive/advance", headers={"X-API-Key": key}, json={"revision": 0})
    assert r.status_code == 400, r.text
    assert r.json()["ok"] is False
