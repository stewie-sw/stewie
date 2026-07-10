"""[dispatch-audit R2 / F4-terrain] /executive/run executes on the SAME composed as-built surface the
plan/review used -- not the raw site DEM.

The audit (finding 3, "physics and terrain inputs diverge across plan, release, and run") found the plan
route applies the site's current COMPOSED surface (remembered/observed terrain via ``state.as_built_dem``,
plan.py:208), while the run route loaded the RAW site DEM and passed it straight to ``run_closed_loop``
(executive.py) -- so an as-built or observed hazard used during planning need not be present during SIM
execution. F4-terrain closes that: the run composes the as-built surface exactly as the plan does, so the
executed plan runs on the same terrain input that was reviewed.

Shape-agnostic wiring check with REAL data: spy on the real ``state.as_built_dem`` (called through) and on
the real ``run_closed_loop`` (called through) and assert the run composes the as-built surface for the site
and executes on THAT object. No mock data -- both spies delegate to the real functions on the real DEM.
"""
from __future__ import annotations

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


def _release(c, key) -> str:
    payload = {"body": "moon", "mission_id": "M-f4t", "orders": [
        {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": 0.2}]}
    r = c.post("/executive/release-plan", headers={"X-API-Key": key}, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["signed_revision"]["content_hash"]


def test_run_executes_on_the_as_built_surface_for_the_site(client, monkeypatch):  # [dispatch-audit R2]
    c, key = client
    ch = _release(c, key)

    from lode import autonomy as AUT
    from stewie.server import state

    composed = {}
    real_as_built = state.as_built_dem

    def ab_spy(site, dem, origin):
        r = real_as_built(site, dem, origin)          # the REAL composition on the REAL DEM
        composed["site"] = site
        composed["result"] = r
        return r

    captured = {}
    real_rcl = AUT.run_closed_loop

    def rcl_spy(mission, **kw):
        captured["dem"] = kw.get("dem")               # what the run actually executes on
        return real_rcl(mission, **kw)                # let the REAL closed-loop sim run

    monkeypatch.setattr(state, "as_built_dem", ab_spy)
    monkeypatch.setattr(AUT, "run_closed_loop", rcl_spy)

    r = c.post("/executive/run", headers={"X-API-Key": key},
               json={"revision_hash": ch, "site": "haworth"})
    assert r.status_code == 200, r.text

    # the run composed the as-built surface FOR the requested site ...
    assert composed.get("site") == "haworth", "the run did not compose the as-built surface (used the raw DEM)"
    # ... and executed the closed-loop sim on THAT composed surface (identity: the exact object it composed).
    assert captured.get("dem") is composed["result"], "the run executed on a different surface than it composed"
