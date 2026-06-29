"""#241 TDD: per-owner draft autosave. The cockpit's live authoring draft persists to the operator's
PER-OWNER sandbox (durable + cross-device), and NEVER to live/command-eligible state. Asserts the council
must-haves: per-owner isolation, sandbox-only (not command-eligible), owner-stamp, unknown-field rejection,
auth-required (no anonymous fallback). Real store under a tmp data_dir; no synthetic platform state."""
import pytest
from fastapi.testclient import TestClient


def test_save_load_draft_roundtrip_and_per_owner_isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    doc = {"body": "moon", "orders": [{"x": 1, "y": 2, "kind": "cut"}], "keepouts": [], "wiz_step": "orders"}
    OBJ.save_draft(doc, owner="alice@x.com")
    got = OBJ.load_draft(owner="alice@x.com")
    assert got and got["body"] == "moon" and got["orders"] == doc["orders"]
    # per-owner isolation: a different owner cannot see alice's draft
    assert OBJ.load_draft(owner="bob@x.com") is None
    # sandbox-only: the draft must NOT land in the live (command-eligible) tier
    assert not (tmp_path / "draft" / "current.json").exists(), "draft must NOT be written to live"
    sb = tmp_path / "draft" / "sandbox"
    assert sb.exists() and any(sb.iterdir()), "draft must live in the per-owner sandbox"


def test_save_draft_rejects_unknown_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    with pytest.raises(ValueError):
        OBJ.save_draft({"body": "moon", "evil_field": 1}, owner="a@x.com")


def test_save_draft_owner_stamp_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    assert OBJ.save_draft({"body": "moon"}, owner="alice@x.com")["created_by"] == "alice@x.com"
    assert OBJ.save_draft({"body": "mars"}, owner="alice@x.com")["created_by"] == "alice@x.com"   # no theft on re-save


def test_draft_route_roundtrip_and_400(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.setenv("STEWIE_DEV_OPEN", "1")            # loopback TestClient -> require_auth = dev-open identity
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    assert c.put("/draft", json={"body": "moon", "orders": [{"x": 3, "y": 4, "kind": "fill"}]}).status_code == 200
    g = c.get("/draft")
    assert g.status_code == 200 and g.json()["doc"]["orders"] == [{"x": 3, "y": 4, "kind": "fill"}]
    assert c.put("/draft", json={"body": "moon", "nope": 1}).status_code == 400   # unknown field


def test_draft_route_requires_auth_no_anonymous(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STEWIE_API_KEY", raising=False)
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)  # no key + no dev-open -> fail closed, no 'unknown' owner
    import stewie.server.server as SRV
    c = TestClient(SRV.app)
    assert c.get("/draft").status_code == 503
    assert c.put("/draft", json={"body": "moon"}).status_code == 503
