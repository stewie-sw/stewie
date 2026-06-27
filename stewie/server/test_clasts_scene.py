"""#147 tier-3: GET /clasts/scene serves the real Chrono-settled boulder scene
(scripts/chrono_clast_scene.py writes <data_dir>/clasts_scene.json via a ChSystemSMC solve) and reports
an honest empty scene when none has been produced. The producer itself is chrono-env-only (it imports
pychrono), so it is run-verified out of band; this pins the cockpit-facing endpoint contract.

Run: <venv>/bin/python -m pytest stewie/server/test_clasts_scene.py -q
"""
import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), tmp_path
    monkeypatch.undo()
    importlib.reload(srv)


def test_empty_when_no_scene_produced(client):
    c, _ = client
    r = c.get("/clasts/scene")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["present"] is False and b["n"] == 0 and b["clasts"] == []


def test_serves_the_produced_scene(client):
    c, tmp = client
    scene = {"frame": "order", "engine": "pychrono.ChSystemSMC", "window_m": 300.0, "n": 2,
             "clasts": [{"x": 150.0, "y": 146.0, "z": 0.97, "r": 1.0},
                        {"x": 173.0, "y": 188.0, "z": 1.53, "r": 1.6}]}
    (tmp / "clasts_scene.json").write_text(json.dumps(scene))
    r = c.get("/clasts/scene")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["present"] is True and b["n"] == 2
    assert b["engine"] == "pychrono.ChSystemSMC"
    assert b["clasts"][0]["x"] == 150.0 and b["clasts"][1]["r"] == 1.6


def test_corrupt_scene_degrades_to_empty(client):
    c, tmp = client
    (tmp / "clasts_scene.json").write_text("{ not valid json")
    r = c.get("/clasts/scene")
    assert r.status_code == 200 and r.json()["present"] is False   # never 500 on a bad file
