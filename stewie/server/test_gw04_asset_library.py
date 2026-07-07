"""[REQ:GW-04] Asset Library -- browse / search / inspect / export / recover the DURABLE assets, separate
from the visible map layers, every durable object tracing to provenance.

The registry (GET /library) is a PUBLIC map-data read (like /world/layer-catalog) so the keyless public
/ide/ can browse it; it exposes the durable-asset MANIFEST (type/id/created/provenance/size), NOT the
sensitive payload (the mission ORDER list + report BYTES stay auth-gated at /missions/{name} + /reports/
{name}). Recover is an operator-gated MUTATION reusing the existing recoverable soft-delete. This test
drives all five verbs over REAL persisted files in a tmp data_dir (missions/structures via the real
server.objects API, real report files under reports_dir) -- no fabricated assets.

Run: <venv>/bin/python -m pytest stewie/server/test_gw04_asset_library.py -q
"""
import importlib
import os

import pytest
from fastapi.testclient import TestClient

KEY = {"X-API-Key": "test-key"}
_MISSION = {"body": "moon", "orders": [
    {"action": "src", "kind": "cut", "x": 5.0, "y": 5.0, "footprint_m2": 36.0, "depth_m": 0.3}]}
_STRUCT = {"kind_list": [{"kind": "cut", "dx": 0, "dy": 0, "footprint_m2": 1.0, "depth_m": 0.1}]}


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")           # a key is configured -> auth routes 401 keyless
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))       # isolate all durable stores to tmp
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")                 # dev-open/api-key identity == director
    from stewie.server import asset_library as AL
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    importlib.reload(AL)
    # REAL durable assets, written through the real persistence:
    OBJ.save_mission("Landing Pad A", _MISSION, owner="alice@x.com", namespace="live")
    OBJ.save_structure("Berm Template", _STRUCT, owner="bob@x.com", namespace="live")
    # a real (minimal) mission-control report file pair under reports_dir (the library reads size/mtime/format)
    rdir = os.path.join(str(tmp_path), "reports")
    os.makedirs(rdir, exist_ok=True)
    with open(os.path.join(rdir, "haworth_plan.md"), "w", encoding="utf-8") as fh:
        fh.write("# Haworth mission-control report\n\nreal minimal report fixture (md source).\n")
    with open(os.path.join(rdir, "haworth_plan.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4\n% minimal real report fixture\n")
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def test_library_is_public_but_payload_is_auth_gated(client):  # [REQ:GW-04]
    # PUBLIC map-data read: the keyless public /ide/ must be able to BROWSE the library...
    r = client.get("/library")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # ...while the SENSITIVE payload (the mission ORDER list) stays auth-gated (S-06 boundary preserved).
    assert client.get("/missions").status_code == 401
    assert client.get("/missions/landing-pad-a").status_code == 401


def test_browse_lists_the_durable_assets_with_provenance(client):  # [REQ:GW-04]
    d = client.get("/library").json()
    assets = d["assets"]
    by_type = {a["type"] for a in assets}
    # the live mission + shared structure + the report are all durable, browsable assets
    assert {"mission", "structure", "report"} <= by_type
    ids = {(a["type"], a["id"]) for a in assets}
    assert ("mission", "landing-pad-a") in ids
    assert ("structure", "berm-template") in ids
    assert ("report", "haworth_plan") in ids
    # ACCEPTANCE: every durable object traces to provenance (a non-empty provenance string) + a size
    for a in assets:
        assert a.get("provenance"), f"{a['type']}:{a['id']} has no provenance"
        assert isinstance(a.get("size_bytes"), int) and a["size_bytes"] >= 0
    # counts + total are consistent
    assert d["total"] == len(assets)
    assert d["counts"]["mission"] >= 1 and d["counts"]["report"] >= 1
    # the manifest must NOT leak the sensitive order payload
    mission = next(a for a in assets if a["type"] == "mission" and a["id"] == "landing-pad-a")
    assert "orders" not in mission["detail"] and mission["detail"]["n_orders"] == 1


def test_search_and_type_filter(client):  # [REQ:GW-04]
    # SEARCH: a query narrows the manifest (case-insensitive over type/id/title/provenance)
    hits = client.get("/library", params={"q": "berm"}).json()["assets"]
    assert hits and all("berm" in (a["id"] + a["title"]).lower() for a in hits)
    assert any(a["type"] == "structure" for a in hits)
    # TYPE filter returns only that type
    reps = client.get("/library", params={"type": "report"}).json()["assets"]
    assert reps and all(a["type"] == "report" for a in reps)


def test_inspect_one(client):  # [REQ:GW-04]
    r = client.get("/library/mission/landing-pad-a")
    assert r.status_code == 200, r.text
    a = r.json()["asset"]
    assert a["type"] == "mission" and a["id"] == "landing-pad-a"
    assert a["provenance"] and a["detail"]["owner"] == "alice@x.com"
    assert "orders" not in a["detail"]                        # inspect stays manifest-level, not the payload
    assert client.get("/library/mission/does-not-exist").status_code == 404


def test_export_descriptor(client):  # [REQ:GW-04]
    r = client.get("/library/structure/berm-template/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"].startswith("attachment")
    body = r.json()
    assert body["schema"] == "stewie.asset_library.v1"
    assert body["type"] == "structure" and body["id"] == "berm-template" and body["provenance"]
    assert "exported_at" in body
    assert client.get("/library/mission/ghost/export").status_code == 404


def test_recover_restores_a_soft_deleted_asset(client):  # [REQ:GW-04]
    from stewie.server import objects as OBJ
    # a live mission is a durable, recoverable asset: soft-delete it (recoverable trash, not unlink)
    assert OBJ.delete_mission("Landing Pad A", namespace="live") is True
    assert not any(a["id"] == "landing-pad-a" and a["type"] == "mission"
                   for a in client.get("/library").json()["assets"])          # gone from the live manifest
    # it surfaces as recoverable in the trash view
    trash = client.get("/library", params={"include_trash": "1"}).json()["trash"]
    assert any(t["type"] == "mission" and t["id"] == "landing-pad-a" and t["recoverable"] for t in trash)
    # RECOVER is an auth-gated mutation (the keyless public path cannot restore shared/live state)
    assert client.post("/library/mission/landing-pad-a/recover").status_code == 401
    # with operator+ credentials it restores in place, reusing the recoverable soft-delete
    out = client.post("/library/mission/landing-pad-a/recover", headers=KEY).json()
    assert out["ok"] is True and out["restored"] is True
    assert any(a["id"] == "landing-pad-a" and a["type"] == "mission"
               for a in client.get("/library").json()["assets"])              # back in the manifest
    # a type that is not trash-recoverable reports honestly (no pretend restore)
    rep = client.post("/library/report/haworth_plan/recover", headers=KEY).json()
    assert rep["ok"] is False and rep["restored"] is False and rep["reason"]
