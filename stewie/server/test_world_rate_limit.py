"""F6: the public, unauth, compute-heavy /world read routes are rate-limited PER CLIENT IP, exactly like
the other public heavy routes (layers.globe_quota, dem._viz_quota). Without it, an anonymous client can
hammer the heavy terramechanics / suitability / keepout composites unbounded.
"""
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


def test_world_site_suitability_is_rate_limited_per_ip(monkeypatch, tmp_path):
    from stewie.server.routers import world as W
    c = _client(monkeypatch, tmp_path)
    W._world_ratelimiter.reset()
    old = W._world_ratelimiter.max_hits
    W._world_ratelimiter.max_hits = 3
    try:
        codes = [c.get("/world/site-suitability", params={"site": "haworth"}).status_code for _ in range(5)]
    finally:
        W._world_ratelimiter.max_hits = old
        W._world_ratelimiter.reset()
    # the first 3 (within cap) are served (200 with the real Haworth bundle, or 404 if absent) -- never 429;
    # the 4th/5th SURPLUS calls from the same IP are rejected 429 (parity with /layers/globe/dem.png).
    assert codes[0] != 429 and codes[1] != 429 and codes[2] != 429, codes
    assert codes[3] == 429 and codes[4] == 429, f"surplus calls must be rate-limited: {codes}"


def test_world_points_post_route_is_rate_limited_per_ip(monkeypatch, tmp_path):
    from stewie.server.routers import world as W
    c = _client(monkeypatch, tmp_path)
    W._world_ratelimiter.reset()
    old = W._world_ratelimiter.max_hits
    W._world_ratelimiter.max_hits = 3
    try:
        codes = [c.post("/world/points", json={"site": "haworth", "points": [[60.0, 60.0]]}).status_code
                 for _ in range(5)]
    finally:
        W._world_ratelimiter.max_hits = old
        W._world_ratelimiter.reset()
    assert codes[3] == 429 and codes[4] == 429, f"surplus POST /world/points must be rate-limited: {codes}"
