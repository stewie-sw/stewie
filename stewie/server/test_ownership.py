"""AG-05 [REQ:AG-05] (PRD §7.12): missions/structures stamp created_by + created_at at save; the public listing
exposes the owner; pre-AG-05 (unowned) artifacts read as owner 'unknown' with NO silent backfill;
re-saving an existing artifact preserves the ORIGINAL creator (no ownership theft); a client cannot
forge the owner through the document body. Real on-disk store against a tmp data_dir.

Run: <venv>/bin/python -m pytest stewie/server/test_ownership.py -q
"""
import importlib
import json
import os

import pytest


@pytest.fixture()
def obj(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    return OBJ, str(tmp_path)


def test_save_stamps_owner_and_timestamp(obj):
    OBJ, _ = obj
    OBJ.save_mission("Pad A", {"body": "moon", "orders": []}, owner="alice@x.com")
    d = OBJ.load_mission("Pad A")
    assert d["created_by"] == "alice@x.com"
    assert isinstance(d["created_at"], (int, float)) and d["created_at"] > 0


def test_list_exposes_owner(obj):
    OBJ, _ = obj
    OBJ.save_mission("Pad A", {"body": "moon", "orders": []}, owner="alice@x.com")
    row = next(r for r in OBJ.list_missions() if r["name"] == "pad-a")
    assert row["owner"] == "alice@x.com"


def test_resave_preserves_the_original_creator(obj):
    OBJ, _ = obj
    OBJ.save_mission("Pad A", {"body": "moon", "orders": []}, owner="alice@x.com")
    OBJ.save_mission("Pad A", {"body": "moon", "orders": [{"x": 1}]}, owner="bob@x.com")
    d = OBJ.load_mission("Pad A")
    assert d["created_by"] == "alice@x.com"           # bob re-saved but did NOT steal ownership


def test_existing_unowned_reads_as_unknown(obj):
    OBJ, tmp = obj
    mdir = os.path.join(tmp, "missions")
    os.makedirs(mdir, exist_ok=True)
    with open(os.path.join(mdir, "legacy.json"), "w") as f:                 # pre-AG-05 artifact, no owner
        json.dump({"name": "legacy", "title": "Legacy", "body": "moon", "orders": []}, f)
    row = next(r for r in OBJ.list_missions() if r["name"] == "legacy")
    assert row["owner"] == "unknown"                  # surfaced as unknown, NOT silently backfilled


def test_client_cannot_forge_owner_via_doc(obj):
    OBJ, _ = obj
    with pytest.raises(ValueError):                   # created_by is not a client field -> rejected
        OBJ.save_mission("X", {"body": "moon", "created_by": "evil@x.com"}, owner="alice@x.com")


def test_structure_save_stamps_owner(obj):
    OBJ, _ = obj
    OBJ.save_structure("Tmpl", {"kind_list": [
        {"kind": "cut", "dx": 0, "dy": 0, "footprint_m2": 1.0, "depth_m": 0.1}]}, owner="carol@x.com")
    row = next(r for r in OBJ.list_structures() if r["name"] == "tmpl")
    assert row["owner"] == "carol@x.com"
