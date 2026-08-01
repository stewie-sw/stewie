"""SR-08 [REQ:GW-07]: the public /world/points quota must be charged in POINTS, not requests.

`/world/points` is public by design (like /world/point) and rate-limited per client IP. But the limiter
was a REQUEST counter, and the route accepts a batch of up to 512 cells. Measured by the 2026-07-28
review on the real Haworth DEM: 29.9 ms per point, so ~15.3 s of CPU for one accepted request. The two
caps therefore multiplied -- 240 requests x 15.3 s = ~3,600 CPU-seconds demanded per 60 s window against
a single GIL-bound uvicorn worker, roughly 60x oversubscription. Because `client_ip` resolves to the
nginx container IP unless STEWIE_TRUST_PROXY is set, one anonymous client consumed the whole public
budget and stalled the authenticated cockpit with it.

The pre-existing limiter test proved the quota using a ONE-point batch -- 1/512 of the accepted cost --
so the entire multiplication lived outside what it measured. That is the register's recurring shape: a
gate that tests the artifact (the counter fires) rather than the requirement (the server cannot be
oversubscribed).

Run: <venv>/bin/python -m pytest stewie/server/test_world_point_budget.py -q
"""
from __future__ import annotations

from stewie.server.ratelimit import RateLimiter


def test_cost_defaults_to_one_and_preserves_the_old_semantics():
    """Back-compat: an unweighted limiter still admits exactly max_hits calls."""
    rl = RateLimiter(3, 60.0)
    assert [rl.allow("ip") for _ in range(4)] == [True, True, True, False]


def test_a_weighted_charge_consumes_the_window_proportionally():
    """The SR-08 core: one 512-point batch must cost 512 units, not 1."""
    rl = RateLimiter(512, 60.0)
    assert rl.allow("ip", cost=512) is True          # one full-size batch fits ...
    assert rl.allow("ip", cost=1) is False           # ... and then the window is spent


def test_many_small_batches_and_one_big_one_cost_the_same():
    """The property a request counter could not express: cost is the payload, not the call count."""
    a, b = RateLimiter(512, 60.0), RateLimiter(512, 60.0)
    for _ in range(512):
        assert a.allow("ip", cost=1) is True
    assert a.allow("ip", cost=1) is False
    assert b.allow("ip", cost=512) is True
    assert b.allow("ip", cost=1) is False


def test_an_oversized_single_charge_is_refused_not_admitted():
    """A request costing more than the whole window must be refused, not admitted then starve it."""
    rl = RateLimiter(100, 60.0)
    assert rl.allow("ip", cost=512) is False
    assert rl.allow("ip", cost=100) is True          # the window was NOT consumed by the refusal


def test_budget_is_per_key():
    rl = RateLimiter(512, 60.0)
    assert rl.allow("a", cost=512) is True
    assert rl.allow("b", cost=512) is True           # a different client keeps its own budget
    assert rl.allow("a", cost=1) is False


def test_window_reset_restores_the_budget():
    rl = RateLimiter(512, 60.0)
    assert rl.allow("ip", cost=512, now=1000.0) is True
    assert rl.allow("ip", cost=1, now=1030.0) is False        # same window
    assert rl.allow("ip", cost=512, now=1061.0) is True       # window elapsed


def test_points_route_charges_its_batch_size(monkeypatch, tmp_path):
    """End to end: a full-size batch exhausts the per-IP point budget for the window."""
    import importlib

    from fastapi.testclient import TestClient
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_WORLD_POINT_BUDGET", "8")
    import stewie.server.server as srv
    importlib.reload(srv)
    from stewie.server.routers import world as W
    importlib.reload(W)
    c = TestClient(srv.app)
    pts = [[0.0, 0.0]] * 9                                     # one batch over the lowered budget
    r = c.post("/world/points", json={"site": "haworth", "points": pts})
    assert r.status_code == 429, f"a 9-point batch was admitted against an 8-point budget: {r.status_code}"
    assert "budget" in r.text.lower()
