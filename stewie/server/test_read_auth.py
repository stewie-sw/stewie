"""S-06 regression: operational READS must require authentication.

The audit found mission list/load, profile list/load, custom structures, /reports/{name},
/config + /config/full were PUBLIC -- any network client could enumerate operational plans, vehicle/
site config, generated reports, and paths. This pins that each such GET now returns 401/403/503 (NOT
200) without a credential, and works WITH one.

It also pins the OPAQUE report-id fix: a report URL is an unguessable token, not the deterministic
name-slug + content hash a network user could derive and fetch.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_read_auth.py -q
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


# the operational-read routes the audit named (S-06). Each must be auth-gated.
READ_ROUTES = [
    "/missions",
    "/missions/nonexistent",
    "/structures/custom",
    "/profiles",
    "/profile/nonexistent",
    "/config",
    "/config/full",
    "/sites",
]


@pytest.mark.parametrize("route", READ_ROUTES)
def test_operational_read_requires_auth(client, route):
    c, _key = client
    r = c.get(route)
    assert r.status_code in (401, 403, 503), (
        f"{route} is still PUBLIC (got {r.status_code}); S-06 requires auth on operational reads")


@pytest.mark.parametrize("route", READ_ROUTES)
def test_operational_read_works_with_auth(client, route):
    c, key = client
    r = c.get(route, headers={"X-API-Key": key})
    # 200 (served) or 404 (auth passed, the specific item is just absent) -- NOT an auth rejection
    assert r.status_code in (200, 404), f"{route} rejected a valid credential ({r.status_code})"


def test_report_route_requires_auth(client):
    c, _key = client
    r = c.get("/reports/anything.pdf")
    assert r.status_code in (401, 403, 503), "the report route is still public (S-06)"


def test_report_id_is_opaque_not_a_derivable_name_hash(client):
    """S-06: a report URL must be an UNGUESSABLE token. The old stem was slug(name)+sha1(payload)[:8]
    -- a network user who knew the mission name/body could derive the filename and fetch the report.
    The returned report path must not be that derivable stem."""
    import hashlib
    import json
    import os
    import re
    c, key = client
    orders = [{"action": "cut", "kind": "cut", "x": 40, "y": 30, "footprint_m2": 36, "depth_m": 0.04},
              {"action": "fill", "kind": "fill", "x": 44, "y": 44, "footprint_m2": 14, "depth_m": 0.10}]
    payload = {"name": "secret-base", "body": "moon", "charger": [0, 0], "orders": orders}
    r = c.post("/plan", json=payload, headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    pdf_url = r.json()["pdf"]
    report_id = os.path.splitext(os.path.basename(pdf_url))[0]
    # reconstruct the OLD derivable stem from public knowledge of the mission
    full = {"name": "secret-base", "body": "moon", "charger": [0, 0], "orders": orders,
            "algorithm": "nearest", "objective": "time", "lat": None, "lon": None,
            "vehicles": 1, "site": "haworth"}
    slug = re.sub(r"[^a-z0-9]+", "-", "secret-base").strip("-")
    derivable = f"{slug}-{hashlib.sha1(json.dumps(full, sort_keys=True).encode()).hexdigest()[:8]}"
    assert report_id != derivable, "report id is still the derivable name+hash stem (S-06)"
    assert "secret-base" not in report_id, "report id leaks the mission name (S-06)"
    # and the opaque id is itself fetchable by an authed client
    got = c.get(pdf_url, headers={"X-API-Key": key})
    assert got.status_code == 200
