"""AG-06 [REQ:AG-06] (PRD §7.12): delete is a recoverable soft-delete (move to per-kind .trash, recoverable),
with OWNERSHIP escalation -- self-service for your OWN artifact; another operator's (or an unowned)
artifact needs a director; permanent purge is director-only. Store mechanism + the pure escalation
policy against a real tmp store. (The live-namespace half of the rule lands with AG-07.)

Run: <venv>/bin/python -m pytest stewie/server/test_soft_delete.py -q
"""
import importlib

import pytest


@pytest.fixture()
def obj(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    return OBJ


def test_soft_delete_is_recoverable(obj):
    obj.save_mission("Pad A", {"body": "moon", "orders": []}, owner="alice@x.com")
    assert obj.delete_mission("Pad A") is True
    assert not any(r["name"] == "pad-a" for r in obj.list_missions())   # gone from the live listing
    assert obj.load_mission("Pad A") is None
    assert obj.restore("missions", "Pad A") is True                     # recoverable from trash
    d = obj.load_mission("Pad A")
    assert d is not None and d["created_by"] == "alice@x.com"           # owner preserved through trash


def test_delete_missing_is_a_noop(obj):
    assert obj.delete_mission("nope") is False


def test_deletion_allowed_policy(obj):
    allow = obj.deletion_allowed
    # BP-05: a LIVE (operational/shared) artifact is director-only to delete -- even for the owner.
    assert allow("alice@x.com", "alice@x.com", False, namespace="live") is False    # own live -> needs director
    assert allow("alice@x.com", "alice@x.com", True, namespace="live") is True       # director escalation
    assert allow("alice@x.com", "bob@x.com", False, namespace="live") is False       # other operator -> director
    # SANDBOX keeps self-service (your own, or a director).
    assert allow("alice@x.com", "alice@x.com", False, namespace="sandbox") is True   # own sandbox -> self-service
    assert allow("alice@x.com", "bob@x.com", False, namespace="sandbox") is False    # other operator -> director
    assert allow("alice@x.com", "bob@x.com", True, namespace="sandbox") is True       # director escalation
    # unowned -> director only; missing artifact -> harmless no-op (either namespace).
    assert allow("unknown", "bob@x.com", False, namespace="sandbox") is False
    assert allow("unknown", "bob@x.com", True, namespace="live") is True
    assert allow(None, "bob@x.com", False) is True


def test_owner_of(obj):
    obj.save_mission("Pad A", {"body": "moon", "orders": []}, owner="alice@x.com")
    assert obj.owner_of("missions", "Pad A") == "alice@x.com"
    assert obj.owner_of("missions", "ghost") is None


def test_purge_is_permanent(obj):
    obj.save_mission("Pad A", {"body": "moon", "orders": []}, owner="alice@x.com")
    obj.delete_mission("Pad A")
    trash = obj.list_trash("missions")
    assert len(trash) == 1
    assert obj.purge_trash("missions", trash[0]) is True
    assert obj.list_trash("missions") == []
    assert obj.restore("missions", "Pad A") is False                    # purged -> not recoverable


def test_structure_soft_delete_recoverable(obj):
    obj.save_structure("Tmpl", {"kind_list": [
        {"kind": "cut", "dx": 0, "dy": 0, "footprint_m2": 1.0, "depth_m": 0.1}]}, owner="carol@x.com")
    assert obj.delete_structure("Tmpl") is True
    assert not any(r["name"] == "tmpl" for r in obj.list_structures())
    assert obj.restore("structures", "Tmpl") is True
    assert any(r["name"] == "tmpl" for r in obj.list_structures())
