"""#304 (AG-07): WRITING the shared planning-profile store is operator+.

A saved profile is a flat, name-keyed snapshot of the WHOLE planning config (body/soil/fleet/orders);
loading it restores that config. Like the #294 structures library, a guest/trainee (below operator on the
AG-01 ladder guest<trainee<operator<director) must NOT be able to POST one -- previously the route was
require_auth, so any authenticated identity could clobber a director's profile. Reads stay any-auth (S-06).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_profile_write_role.py -q
"""
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _app(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_API_KEY", "dir-key")              # the api-key identity == director
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as SRV
    importlib.reload(SRV)
    return SRV, OPS


def test_trainee_cannot_write_the_shared_profile_library(monkeypatch, tmp_path):
    SRV, OPS = _app(monkeypatch, tmp_path)
    from stewie.server import auth as AUTH
    OPS.create_active("t@x.com", "trainee-pw-1", role="trainee", by="test")
    tok = AUTH.issue_token("t@x.com")
    c = TestClient(SRV.app)
    body = {"name": "shared-pad", "profile": {"body": "moon", "orders": []}}
    try:
        r = c.post("/profile", headers={"Authorization": f"Bearer {tok}"}, json=body)
        assert r.status_code == 403, f"a trainee wrote the shared profile library (#304); got {r.status_code}"
        # a director (api-key) still saves -> the write path itself is intact, only the role floor is new
        r_dir = c.post("/profile", headers={"X-API-Key": "dir-key"}, json=body)
        assert r_dir.status_code == 200 and r_dir.json()["ok"], r_dir.text
        # the trainee can still READ the library (S-06: any-auth read is unchanged)
        assert c.get("/profiles", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    finally:
        importlib.reload(SRV)
