"""S-08 regression: compute-heavy routes must require auth and enforce per-identity quotas.

The audit found /plan/commands, /plan/math, and the layer raster route were PUBLIC, and authenticated
planning ran with no per-user budget -- so a remote user could monopolize the single uvicorn worker
with repeated routing / raster / PDF work.

This pins:
 - the heavy planner-helper routes (/plan/commands, /plan/math) and the raster layer route require
   auth (401/403/503 without a credential), and
 - the heavy /plan route enforces a per-identity quota (sustained planning bursts from ONE identity
   eventually return 429), while a single plan still succeeds.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_heavy_routes.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_HEAVY_QUOTA_MAX", "3")     # small quota so the burst trips fast
    monkeypatch.setenv("STEWIE_HEAVY_QUOTA_WINDOW_S", "60")
    import stewie.server.server as srv
    importlib.reload(srv)
    from stewie.server.routers import plan as planr
    importlib.reload(planr)
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


_ORDERS = [{"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
           {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]
_BODY = {"name": "h", "body": "moon", "charger": [0, 0], "orders": _ORDERS}


@pytest.mark.parametrize("route", ["/plan/commands", "/plan/math"])
def test_heavy_planner_helpers_require_auth(client, route):
    c, _key = client
    r = c.post(route, json=_BODY)
    assert r.status_code in (401, 403, 503), f"{route} is public (S-08): {r.status_code}"


def test_raster_layer_requires_auth(client):
    c, _key = client
    r = c.get("/layers/raster/slope.png")
    assert r.status_code in (401, 403, 503), f"raster layer is public (S-08): {r.status_code}"


def test_plan_enforces_per_identity_quota(client):
    c, key = client
    codes = []
    for _ in range(8):
        r = c.post("/plan", json=_BODY, headers={"X-API-Key": key})
        codes.append(r.status_code)
    assert 429 in codes, f"the heavy /plan route has no per-identity quota (S-08); saw {codes}"
    # the FIRST request must have succeeded (the quota does not block a single legitimate plan)
    assert codes[0] == 200, f"the first plan was rejected ({codes[0]})"


def test_a_single_authed_heavy_call_works(client):
    c, key = client
    r = c.post("/plan/math", json=_BODY, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text


# ---- ARCH-01/04: input-size + wall-clock caps so one heavy request cannot monopolize the worker ------

def _ko(n):
    return [{"x": float(i), "y": 0.0, "r": 5.0} for i in range(n)]


def test_plan_rejects_too_many_keepouts(client, monkeypatch):
    """ARCH-01/04 input-size cap: a mission with more keep-outs than the bound is rejected FAST (413)
    before the heavy compute, so an oversized input cannot drive an unbounded plan on the single worker.
    (orders + vehicles are already capped by the typed PlanRequest.)"""
    c, key = client
    monkeypatch.setenv("STEWIE_MAX_KEEPOUTS", "3")
    r = c.post("/plan", json={**_BODY, "keepouts": _ko(10)}, headers={"X-API-Key": key})
    assert r.status_code == 413, f"oversized keep-out list not rejected (ARCH-01/04): {r.status_code}"
    assert "keep-out" in r.json()["error"].lower()


def test_plan_within_caps_still_succeeds(client, monkeypatch):
    """The cap must not false-positive: a mission within the keep-out bound still plans (200)."""
    c, key = client
    monkeypatch.setenv("STEWIE_MAX_KEEPOUTS", "50")
    r = c.post("/plan", json={**_BODY, "keepouts": _ko(2)}, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text


def test_plan_wall_clock_deadline_returns_bounded_error_not_a_hang(client, monkeypatch):  # [REQ:PO-06]
    """ARCH-01/04 wall-clock cap: with a tiny per-request compute budget, a plan that exceeds it returns
    a bounded 503 rather than hanging the client. (The deadline bounds the client wait; the input cap
    bounds the actual compute -- Python cannot force-kill the worker thread.)"""
    c, key = client
    monkeypatch.setenv("STEWIE_PLAN_DEADLINE_S", "0.001")     # smaller than any real plan
    r = c.post("/plan", json=_BODY, headers={"X-API-Key": key})
    assert r.status_code == 503, f"deadline path did not return a bounded error: {r.status_code}"
    assert "budget" in r.json()["error"].lower()
