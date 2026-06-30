"""#294 (AG-07): WRITING the shared live custom-structure template library is operator+.

A saved custom structure goes into the shared LIVE pool (objects.save_structure namespace="live") and
expands into ANY operator's plan, so a guest/trainee (below operator on the AG-01 ladder guest<trainee<
operator<director) must NOT be able to POST one -- previously the route was require_auth, so any
authenticated identity could pollute the shared library. Reads stay any-auth (S-06, unchanged).

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_structures_write_role.py -q
"""
from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

_DOC = {"kind_list": [{"kind": "cut", "dx": 0, "dy": 0, "footprint_m2": 25, "depth_m": 0.08}],
        "note": "council4 #294 gate"}


def _app(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_API_KEY", "dir-key")              # the api-key identity == director
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as SRV
    importlib.reload(SRV)
    return SRV, OPS


def test_trainee_cannot_write_the_shared_structure_library(monkeypatch, tmp_path):
    SRV, OPS = _app(monkeypatch, tmp_path)
    from stewie.server import auth as AUTH
    OPS.create_active("t@x.com", "trainee-pw-1", role="trainee", by="test")
    tok = AUTH.issue_token("t@x.com")
    c = TestClient(SRV.app)
    try:
        r = c.post("/structures/custom/mypad", headers={"Authorization": f"Bearer {tok}"}, json=_DOC)
        assert r.status_code == 403, f"a trainee wrote the shared structure library (#294); got {r.status_code}"
        # a director (api-key) still saves -> the write path itself is intact, only the role floor is new
        r_dir = c.post("/structures/custom/mypad", headers={"X-API-Key": "dir-key"}, json=_DOC)
        assert r_dir.status_code == 200 and r_dir.json()["ok"], r_dir.text
        # the trainee can still READ the library (S-06: any-auth read is unchanged)
        rd = c.get("/structures/custom", headers={"Authorization": f"Bearer {tok}"})
        assert rd.status_code == 200, rd.text
    finally:
        importlib.reload(SRV)
