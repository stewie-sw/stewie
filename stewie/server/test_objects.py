"""S-4 (task #23): the object store -- named missions + custom structure templates, server CRUD.

Saved objects live under data_dir (the same volume W-1..W-3 journal/backup machinery covers);
missions save the FULL authoring state (orders, keep-outs, precedence, body); custom structures
become selectable templates. Review = list+load; delete is real; names are slugged (no traversal).
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _doc():
    return {"body": "moon", "orders": [{"action": "wp1", "kind": "goto", "x": 5, "y": 5},
                                       {"action": "cut", "kind": "cut", "x": 10, "y": 8,
                                        "footprint_m2": 16, "depth_m": 0.05}],
            "keepouts": [{"x": 20, "y": 10, "r": 6}], "precedence": []}


def test_mission_save_list_load_delete(client):
    r = client.post("/missions/pad alpha", json=_doc())
    assert r.status_code == 200 and r.json()["ok"]
    names = [m["name"] for m in client.get("/missions").json()["missions"]]
    assert "pad-alpha" in names                            # slugged
    loaded = client.get("/missions/pad-alpha").json()
    assert loaded["ok"] and loaded["doc"]["orders"][0]["action"] == "wp1"
    assert loaded["doc"]["body"] == "moon"
    assert client.delete("/missions/pad-alpha").json()["ok"]
    assert client.get("/missions/pad-alpha").status_code == 404


def test_mission_names_cannot_traverse(client, tmp_path):
    # the router refuses the encoded slash outright (404) -- even better than slugging
    r = client.post("/missions/..%2Fevil", json=_doc())
    assert r.status_code in (200, 404)
    r2 = client.post("/missions/.. evil dots", json=_doc())     # dots/spaces slug clean
    assert r2.status_code == 200 and r2.json()["name"] == "evil-dots"
    names = [m["name"] for m in client.get("/missions").json()["missions"]]
    assert all("/" not in n and ".." not in n for n in names)
    # nothing escaped the missions dir
    import os
    assert not os.path.exists(tmp_path.parent / "evil.json")


def test_custom_structure_template_roundtrip(client):
    t = {"kind_list": [{"kind": "cut", "dx": 0, "dy": 0, "footprint_m2": 25, "depth_m": 0.08},
                       {"kind": "fill", "dx": 12, "dy": 0, "footprint_m2": 25, "depth_m": 0.08}],
         "note": "test pad pair"}
    r = client.post("/structures/custom/pair pad", json=t)
    assert r.json()["ok"]
    listing = client.get("/structures/custom").json()["structures"]
    assert any(s["name"] == "pair-pad" for s in listing)
    # the template EXPANDS at a location into queue-ready orders
    ex = client.get("/structures/custom/pair-pad/expand?x=30&y=20").json()
    assert ex["ok"] and len(ex["orders"]) == 2
    assert ex["orders"][1]["x"] == 42 and ex["orders"][1]["kind"] == "fill"
    assert client.delete("/structures/custom/pair-pad").json()["ok"]
