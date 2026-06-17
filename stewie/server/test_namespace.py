"""AG-07 [REQ:AG-07] (PRD §7.12): sandbox vs live workspace separation. Artifacts save into a per-owner
sandbox/<owner>/ namespace; a role-gated publish promotes a COPY into the shared live namespace (the
existing flat store -- back-compat). Sandbox names are per-owner isolated; the live listing never
shows sandbox drafts; sandbox soft-delete/restore stay within the namespace. Real tmp store.

Run: <venv>/bin/python -m pytest stewie/server/test_namespace.py -q
"""
import importlib

import pytest

_M = {"body": "moon", "orders": []}


@pytest.fixture()
def obj(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    return OBJ


def test_live_is_the_default_and_flat(obj):
    obj.save_mission("Pad A", _M, owner="op@x.com")                 # no namespace -> live (back-compat)
    assert any(r["name"] == "pad-a" for r in obj.list_missions())   # default list == live
    assert obj.load_mission("Pad A") is not None


def test_sandbox_is_per_owner_isolated(obj):
    obj.save_mission("Draft", _M, owner="alice@x.com", namespace="sandbox")
    obj.save_mission("Draft", {"body": "moon", "orders": [{"x": 1}]},
                     owner="bob@x.com", namespace="sandbox")
    a = obj.load_mission("Draft", namespace="sandbox", owner="alice@x.com")
    b = obj.load_mission("Draft", namespace="sandbox", owner="bob@x.com")
    assert a["orders"] == [] and b["orders"] == [{"x": 1}]           # same name, isolated per owner


def test_sandbox_draft_is_not_in_the_live_listing(obj):
    obj.save_mission("Secret", _M, owner="alice@x.com", namespace="sandbox")
    assert not any(r["name"] == "secret" for r in obj.list_missions())                       # live hides it
    assert any(r["name"] == "secret"
               for r in obj.list_missions(namespace="sandbox", owner="alice@x.com"))         # sandbox shows it


def test_publish_promotes_sandbox_to_live(obj):
    obj.save_mission("Pad B", _M, owner="alice@x.com", namespace="sandbox")
    assert obj.publish("missions", "Pad B", owner="alice@x.com") is True
    assert any(r["name"] == "pad-b" for r in obj.list_missions())   # now live
    live = obj.load_mission("Pad B")
    assert live is not None and live["created_by"] == "alice@x.com"  # original creator preserved


def test_publish_missing_sandbox_is_false(obj):
    assert obj.publish("missions", "ghost", owner="alice@x.com") is False


def test_sandbox_soft_delete_is_isolated_and_recoverable(obj):
    obj.save_mission("D", _M, owner="alice@x.com", namespace="sandbox")
    assert obj.soft_delete("missions", "D", namespace="sandbox", owner="alice@x.com") is True
    assert obj.load_mission("D", namespace="sandbox", owner="alice@x.com") is None
    assert obj.restore("missions", "D", namespace="sandbox", owner="alice@x.com") is True
    assert obj.load_mission("D", namespace="sandbox", owner="alice@x.com") is not None


def test_owner_of_respects_namespace(obj):
    obj.save_mission("Pad C", _M, owner="alice@x.com", namespace="sandbox")
    assert obj.owner_of("missions", "Pad C", namespace="sandbox", owner="alice@x.com") == "alice@x.com"
    assert obj.owner_of("missions", "Pad C") is None                 # not in live until published
