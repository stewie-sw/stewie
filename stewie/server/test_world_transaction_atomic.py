"""[REQ:DT-03] Atomic world-state transaction (review finding 1).

A world-state mutation (``twin.resync``, a terrain record, a SIM-execute remember) and its
``WorldTransaction`` commit must succeed or FAIL TOGETHER. The prior code applied the store mutation and
then SWALLOWED a world-log commit failure best-effort (``try/except Exception: pass`` at twin.py:80,169 /
executive.py:190), so ``TwinStore`` / ``TerrainMemory`` / run records could run AHEAD of
``/world/transaction`` on a corrupt world journal (DT-01 surfaces a bad journal by RAISING).

These fault-injection tests monkeypatch the REAL ``WorldStateService`` commit method (``record_resync`` /
``record_terrain``) to raise AFTER the store mutation is applied, then re-READ the real post-state to
prove the store was rolled back (compensated) and stays consistent with ``/world/transaction``, and that
the DT-01 chain still verifies. Real ``TwinStore`` + real ``TerrainMemory`` + the real planner/sim -- no
stubs, no synthetic stand-ins.
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.server.world_state import WorldStateService

H = {"X-API-Key": "test-key"}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A keyed server in an isolated data dir with the lazy twin + world-state singletons reset, so both
    rebuild against THIS test's data dir (they are process-globals not reset by conftest). DEV_OPEN so the
    director-gated /executive/run is reachable in-test."""
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


def _raise(*_a, **_k):
    """A REAL failure injected into the actual world-log commit path (not a stub) -- mirrors DT-01
    surfacing a corrupt world journal by raising."""
    raise RuntimeError("world journal corrupt")


_TERRAIN_MISSION = {"name": "pad-A", "body": "moon", "charger": [0, 0],
                    "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                                "footprint_m2": 36.0, "depth_m": 0.3}]}
_ORDERS = [{"kind": "cut", "x": 10.0, "y": 10.0, "action": "dig pad", "footprint_m2": 4.0, "depth_m": 0.3}]


def test_resync_rolls_back_the_twin_on_a_world_log_failure(client, monkeypatch):
    """[REQ:DT-03] A resync mutates the observed twin, then commits ``record_resync``. If that commit
    raises, the twin MUST be compensated (undone) so it can never run ahead of ``/world/transaction``; the
    route surfaces the failure (500) instead of the old best-effort 200, and the world log stays empty +
    chain-valid. The mutation + commit are atomic."""
    from stewie.server import state as S
    # pre-state: no world transaction yet; the region we will patch is un-measured
    assert client.get("/world/transaction", headers=H).json()["count"] == 0
    pre = S.twin().current()[:2, :2].copy()
    assert not S.twin().observed_mask()[:2, :2].any()
    # inject a REAL failure into the actual world-log commit method (after the twin mutation is applied)
    monkeypatch.setattr(WorldStateService, "record_resync", _raise)
    r = client.post("/twin/resync", headers=H,
                    json={"heights_m": [[9.9, 9.9], [9.9, 9.9]], "origin_rc": [0, 0], "provenance": "p"})
    assert r.status_code == 500 and r.json()["ok"] is False           # surfaced, not a silent 200
    # the twin mutation was COMPENSATED: the region reverted to its pre-resync heights + coverage
    assert np.array_equal(S.twin().current()[:2, :2], pre)
    assert not S.twin().observed_mask()[:2, :2].any()
    # and no orphan world transaction -- the store did not run ahead of /world/transaction
    after = client.get("/world/transaction", headers=H).json()
    assert after["committed"] is False and after["count"] == 0
    assert S.world_state_service().verify_chain()


def test_terrain_record_rolls_back_the_memory_on_a_world_log_failure(client, monkeypatch):
    """[REQ:DT-03] A terrain record saves the site's TerrainMemory, then commits ``record_terrain``. If
    that commit raises, the persisted TerrainMemory MUST be compensated (restored to its prior state) so
    it never runs ahead of ``/world/transaction``; the route surfaces 500 and the world log stays empty +
    chain-valid."""
    from stewie.server import state as S
    assert client.get("/twin/terrain/haworth", headers=H).json()["recorded"] is False
    assert client.get("/world/transaction", headers=H).json()["count"] == 0
    monkeypatch.setattr(WorldStateService, "record_terrain", _raise)
    r = client.post("/twin/terrain/haworth", headers=H, json={"mission": _TERRAIN_MISSION})
    assert r.status_code == 500                                       # surfaced, not a silent 200
    # the TerrainMemory save was COMPENSATED: the site is back to no-memory (nothing ran ahead)
    assert client.get("/twin/terrain/haworth", headers=H).json()["recorded"] is False
    assert client.get("/world/transaction", headers=H).json()["count"] == 0
    assert S.world_state_service().verify_chain()


def test_sim_run_rolls_back_the_remembered_terrain_on_a_world_log_failure(client, monkeypatch):
    """[REQ:DT-03] A completed SIM run folds its conserved delta into TerrainMemory (the execute->remember
    loop) and records the as-built into the world log. If ``record_terrain`` raises, the remembered
    terrain MUST be compensated so TerrainMemory never runs ahead of ``/world/transaction``;
    /executive/run surfaces 500 (the run is NOT persisted ahead of the failed log), and the DT-01 chain
    still verifies."""
    from stewie.server import state as S
    assert client.get("/twin/terrain/haworth", headers=H).json()["recorded"] is False
    monkeypatch.setattr(WorldStateService, "record_terrain", _raise)
    r = client.post("/executive/run", headers=H, json={"orders": _ORDERS, "site": "haworth"})
    assert r.status_code == 500 and r.json()["ok"] is False           # world-log failure surfaced, not swallowed
    # the SIM as-built fold was COMPENSATED: no terrain ran ahead despite the run computing a build
    assert client.get("/twin/terrain/haworth", headers=H).json()["recorded"] is False
    assert S.world_state_service().verify_chain()
