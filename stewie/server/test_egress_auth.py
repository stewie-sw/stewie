"""#246 TDD: operational data-egress routes require auth on the invitation-only deploy.

Graphify-grounded: these routes egress world-owned authoritative state (LunarSite / TerrainMesh /
RegolithState / Ephemeris) or operational artifacts; on an invitation-only deploy they must not be
anonymously downloadable. Contract: unauthenticated (no API key, no dev-open) -> the route is LOCKED
(deps.require_auth raises 503 "auth not configured"); with a dev-open loopback session -> reachable.
The PUBLIC allowlist (liveness, auth bootstrap, the rate-limited globe base map, published galleries)
stays open by design. This locks the council route table so the surface cannot silently re-open.
"""
import pytest
from fastapi.testclient import TestClient

_FC = {"featurecollection": {"type": "FeatureCollection", "features": []}}

# (method, path, json-body-or-None) -- MUST require auth
GATED = [
    ("GET", "/world", None),
    ("GET", "/dem/heightfield", None),
    ("GET", "/dem/terrain_grid", None),
    ("GET", "/dem/georef", None),
    ("GET", "/dem/sources", None),
    ("GET", "/dem/workarea.png", None),
    ("GET", "/clasts/scene", None),
    ("GET", "/dem/site_xy?lat=-89&lon=0", None),
    ("GET", "/dem/site_lonlat?x=0&y=0", None),
    ("GET", "/dem/haworth_dem", None),                 # /dem/{name}
    ("GET", "/export/geojson", None),
    ("GET", "/gis/mission-package", None),
    ("POST", "/gis/import", _FC),
    ("POST", "/gis/query", _FC),
    ("GET", "/tiles/x/y.json", None),
    ("GET", "/figures", None),
    ("GET", "/figure/x.png", None),
    ("GET", "/metrics", None),
]
# DEFERRED to a follow-up (Aaron's open "debatable" decision + boot-fetch caution): /ephemeris (low-
# sensitivity sun geometry, may be fetched pre-login) and /twin/cg (a stateless CG calculator).
# stay PUBLIC (do not gate)
PUBLIC = ["/healthz", "/auth/config", "/layers/legend", "/export/cog/available", "/contracts/schema"]


def _client(monkeypatch, tmp_path, *, dev_open):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    if dev_open:
        monkeypatch.setenv("STEWIE_DEV_OPEN", "1")
    else:
        monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    import stewie.server.server as SRV
    return TestClient(SRV.app)


@pytest.mark.parametrize("method,path,body", GATED)
def test_egress_route_locked_unauthenticated(monkeypatch, tmp_path, method, path, body):
    c = _client(monkeypatch, tmp_path, dev_open=False)
    r = c.request(method, path, json=body)
    assert r.status_code in (401, 403, 503), f"{method} {path} must require auth, got {r.status_code}"


def test_public_routes_stay_open(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, dev_open=False)
    for path in PUBLIC:
        assert c.get(path).status_code == 200, f"{path} must stay public"


@pytest.mark.parametrize("method,path,body", GATED)
def test_egress_route_reachable_with_session(monkeypatch, tmp_path, method, path, body):
    # with a dev-open loopback session the auth dep passes -> the route is no longer LOCKED (503).
    c = _client(monkeypatch, tmp_path, dev_open=True)
    r = c.request(method, path, json=body)
    assert r.status_code != 503, f"{method} {path} should be reachable when authenticated, got 503"
