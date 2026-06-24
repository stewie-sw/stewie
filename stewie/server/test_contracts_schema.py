"""FS-08 / §25 Phase 1: GET /contracts/schema exposes the JSON Schema of every spine contract -- the
typed fixture the cockpit + browser tests load to build against the shapes, including the contracts
whose live routes are gated on their systems. TestClient.

Run: <venv>/bin/python -m pytest stewie/server/test_contracts_schema.py -q
"""
import importlib

import pytest
from fastapi.testclient import TestClient

from stewie import contracts as C


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_schema_endpoint_exposes_every_spine_contract(client):  # [REQ:FS-02]
    r = client.get("/contracts/schema")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["spine_version"] == C.SPINE_VERSION
    for name in ("EphemerisObservation", "VehicleState", "FleetState", "ResourceReservation",
                 "WorldState", "BeliefState", "PlanResult", "ExecutionEvent", "NavFactor",
                 "ModelArtifact", "ConstructionSkill"):
        assert name in j["schemas"], name
        assert j["schemas"][name]["type"] == "object"          # a valid JSON Schema object


def test_schema_payload_documents_the_required_azimuth_convention(client):
    # FS-06/§25.3: the ephemeris schema must show azimuth_convention as required (no default)
    eph = client.get("/contracts/schema").json()["schemas"]["EphemerisObservation"]
    assert "azimuth_convention" in eph["required"]
