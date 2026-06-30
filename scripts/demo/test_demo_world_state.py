"""Loop #1: the end-to-end world-state demo runs the REAL pipeline in-process and evolves the linked
DT-01 world state (plan -> terrain record -> SIM execute -> read-back), on the real lunar DEM.

No live server, no mocks: a FastAPI TestClient drives the same orchestration the CLI runs against a live
server. Skipped only if the real Haworth DEM bundle is absent (the demo plans on real terrain).
"""
from __future__ import annotations

import importlib
import os

import pytest

_BUNDLE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "samples", "lunar_dem", "haworth_10km_5m")

from demo_world_state import format_walkthrough, run_world_state_demo  # noqa: E402  (scripts/ sibling import)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    from fastapi.testclient import TestClient
    with TestClient(srv.app) as c:
        yield c
    monkeypatch.undo()
    importlib.reload(srv)


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth DEM bundle absent")
def test_demo_evolves_the_linked_world_state_end_to_end(client):
    r = run_world_state_demo(client)
    # each real step ran
    assert "feasible" in r["plan"]                                   # planner produced a result
    assert r["terrain"]["recorded"] is True                         # conserved terrain delta recorded
    assert r["run"]["ok"] is True and r["run"]["label"] == "sim"    # SIM execution, SIM-labeled
    assert r["world"]["committed"] is True

    provs = [t["provenance"] for t in r["timeline"]["transactions"]]
    assert any("terrain.record" in p for p in provs)               # terrain record committed
    assert any("SIM leg" in p for p in provs)                      # per-leg execution events
    assert any(("SIM acceptance" in p) or ("SIM safe" in p) for p in provs)   # terminal event

    # the terrain record MOVED the conserved authority identity off genesis (the demo's headline)
    assert r["world"]["transaction"]["authority_sha"] != "genesis"
    assert len(r["world"]["transaction"]["authority_sha"]) == 64


@pytest.mark.skipif(not os.path.isdir(_BUNDLE), reason="Haworth DEM bundle absent")
def test_walkthrough_narration_is_well_formed(client):
    text = format_walkthrough(run_world_state_demo(client))
    assert "LINKED WORLD STATE (DT-01)" in text
    assert "EXECUTION/WORLD TIMELINE" in text and "terrain.record" in text
