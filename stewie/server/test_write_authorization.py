"""[REQ:AG-05][REQ:AG-06] SR-01: a LIVE artifact may not be overwritten by a non-owner.

The 2026-07-28 review found `POST /missions/{name}` gated on `require_auth` only. `namespace_for`
returns ("live", None) for any operator+, and `save_mission` wrote with no ownership check at all -- so
any operator could replace another operator's live mission wholesale. Worse, `_owner_meta` PRESERVES the
existing `created_by`, so the overwritten document kept the original owner's name on the attacker's
orders, and `save_mission` is a bare atomic write: no prior version, no .trash, unrecoverable.

The asymmetry that proved it was unintended: DELETE on the same artifact is director-only (BP-05,
`deletion_allowed`), while overwrite -- strictly more destructive, since it also launders provenance --
was open to every operator. `POST /structures/custom/{name}` had the identical hole on the SHARED
template library.

This closes it with the mirror of the AG-06 delete policy: `write_allowed`. Live artifacts are
updatable by their OWNER (ordinary authoring) or a DIRECTOR (escalation); a non-owner is refused.

Run: <venv>/bin/python -m pytest stewie/server/test_write_authorization.py -q
"""
from __future__ import annotations

import importlib
import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def obj(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import objects as OBJ
    importlib.reload(OBJ)
    return OBJ


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_REGISTRATION", "1")
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


def _operator(client, email, role="operator"):
    """Register + director-approve + log in a real operator; returns its Bearer auth header."""
    pw = "a-strong-passphrase"
    assert client.post("/auth/register", json={"email": email, "password": pw}).status_code == 200
    assert client.post("/admin/operators/approve", headers={"X-API-Key": "test-key"},
                       json={"email": email, "role": role}).status_code == 200
    r = client.post("/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---- the policy (mirrors test_soft_delete.test_deletion_allowed_policy) -----------------------

def test_write_allowed_policy(obj):
    allow = obj.write_allowed
    # LIVE: the owner keeps ordinary authoring; a non-owner needs director escalation.
    assert allow("alice@x.com", "alice@x.com", False, namespace="live") is True    # own live -> update
    assert allow("alice@x.com", "bob@x.com", False, namespace="live") is False     # SR-01: refused
    assert allow("alice@x.com", "bob@x.com", True, namespace="live") is True       # director escalation
    # SANDBOX: your own, or a director.
    assert allow("alice@x.com", "alice@x.com", False, namespace="sandbox") is True
    assert allow("alice@x.com", "bob@x.com", False, namespace="sandbox") is False
    # a NEW name (no stored artifact) is always creatable; a legacy unowned live file needs a director.
    assert allow(None, "bob@x.com", False) is True
    assert allow("unknown", "bob@x.com", False, namespace="live") is False
    assert allow("unknown", "bob@x.com", True, namespace="live") is True


# ---- the route (two REAL operators, not the director api-key) ---------------------------------

def test_non_owner_cannot_overwrite_a_live_mission(client):
    """The SR-01 exploit, end to end: Bob replaces Alice's published live mission with his own orders."""
    alice, bob = _operator(client, "alice@x.com"), _operator(client, "bob@x.com")
    assert client.post("/missions/Pad A", headers=alice,
                       json={"body": "moon", "orders": []}).status_code == 200
    r = client.post("/missions/Pad A", headers=bob, json={
        "body": "moon", "orders": [{"action": "dig", "kind": "cut", "x": 1.0, "y": 1.0,
                                    "footprint_m2": 400.0, "depth_m": 9.0}]})
    assert r.status_code == 403, f"a non-owner overwrote a live mission: {r.text}"
    stored = client.get("/missions/Pad A", headers=alice).json()["doc"]
    assert stored["orders"] == [], "Alice's live mission was mutated by another operator"
    assert stored["created_by"] == "alice@x.com"


def test_owner_can_still_update_their_own_live_mission(client):
    """The fix must not break ordinary authoring -- the owner edits their own live mission freely."""
    alice = _operator(client, "alice@x.com")
    assert client.post("/missions/Pad A", headers=alice,
                       json={"body": "moon", "orders": []}).status_code == 200
    r = client.post("/missions/Pad A", headers=alice, json={
        "body": "moon", "orders": [{"action": "dig", "kind": "cut", "x": 1.0, "y": 1.0,
                                    "footprint_m2": 9.0, "depth_m": 0.2}]})
    assert r.status_code == 200, r.text


def test_director_can_escalate_over_another_owner(client):
    """AG-06 escalation stays available: a director may override, as they may for delete."""
    alice = _operator(client, "alice@x.com")
    assert client.post("/missions/Pad A", headers=alice,
                       json={"body": "moon", "orders": []}).status_code == 200
    r = client.post("/missions/Pad A", headers={"X-API-Key": "test-key"},   # api-key == director
                    json={"body": "moon", "orders": []})
    assert r.status_code == 200, r.text


def test_a_new_name_is_creatable_by_anyone(client):
    """Only an EXISTING artifact is protected; creating a fresh name stays open to any operator."""
    bob = _operator(client, "bob@x.com")
    assert client.post("/missions/Fresh Name", headers=bob,
                       json={"body": "moon", "orders": []}).status_code == 200


def test_publish_cannot_overwrite_another_owners_live_mission(client):
    """The second door onto the same overwrite: publish WRITES the live namespace.

    Guarding `POST /missions/{name}` alone was not enough -- the publish route validated only whose
    SANDBOX draft was being promoted, never who owned the LIVE destination. Bob drafts his own "Pad A"
    in his sandbox (entirely legitimate) and publishes it over Alice's live "Pad A".
    """
    alice, bob = _operator(client, "alice@x.com"), _operator(client, "bob@x.com")
    assert client.post("/missions/Pad A", headers=alice,
                       json={"body": "moon", "orders": []}).status_code == 200
    assert client.post("/missions/Pad A?ns=sandbox", headers=bob, json={
        "body": "moon", "orders": [{"action": "dig", "kind": "cut", "x": 1.0, "y": 1.0,
                                    "footprint_m2": 400.0, "depth_m": 9.0}]}).status_code == 200
    r = client.post("/missions/Pad A/publish", headers=bob)
    assert r.status_code == 403, f"publish overwrote another owner's live mission: {r.text}"
    stored = client.get("/missions/Pad A", headers=alice).json()["doc"]
    assert stored["orders"] == [], "Alice's live mission was replaced via the publish path"


def test_owner_can_still_publish_over_their_own_live_mission(client):
    """The owner's own draft->live promotion loop must keep working."""
    alice = _operator(client, "alice@x.com")
    assert client.post("/missions/Pad A", headers=alice,
                       json={"body": "moon", "orders": []}).status_code == 200
    assert client.post("/missions/Pad A?ns=sandbox", headers=alice, json={
        "body": "moon", "orders": [{"action": "dig", "kind": "cut", "x": 1.0, "y": 1.0,
                                    "footprint_m2": 9.0, "depth_m": 0.2}]}).status_code == 200
    r = client.post("/missions/Pad A/publish", headers=alice)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text


def test_non_owner_cannot_overwrite_a_shared_structure_template(client):
    """The same hole on the SHARED structure library, which expands into ANY operator's plan."""
    alice, bob = _operator(client, "alice@x.com"), _operator(client, "bob@x.com")
    doc = {"kind_list": [{"kind": "cut", "dx": 0.0, "dy": 0.0, "footprint_m2": 9.0, "depth_m": 0.2}]}
    assert client.post("/structures/custom/Berm", headers=alice, json=doc).status_code == 200
    evil = {"kind_list": [{"kind": "cut", "dx": 0.0, "dy": 0.0, "footprint_m2": 400.0, "depth_m": 9.0}]}
    r = client.post("/structures/custom/Berm", headers=bob, json=evil)
    assert r.status_code == 403, f"a non-owner overwrote a shared structure template: {r.text}"


def test_authorize_and_create_is_atomic_under_concurrent_writers(obj):
    """Two workers racing for an unused slug cannot both authorize against ``owner=None``."""
    barrier = threading.Barrier(2)
    successes: list[str] = []
    refusals: list[str] = []

    def writer(actor):
        barrier.wait()
        try:
            out = obj.save_mission_authorized(
                "Contended", {"body": "moon", "orders": []},
                actor=actor, is_director=False)
            successes.append(out["created_by"])
        except PermissionError:
            refusals.append(actor)

    threads = [
        threading.Thread(target=writer, args=("alice@x.com",)),
        threading.Thread(target=writer, args=("bob@x.com",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert len(successes) == 1 and len(refusals) == 1
    stored = obj.load_mission("Contended")
    assert stored is not None and stored["created_by"] == successes[0]


def test_restore_cannot_replace_a_new_owners_live_mission(client):
    """Alice's trashed bytes must not overwrite Bob after Bob legitimately reclaims the free slug."""
    alice, bob = _operator(client, "alice@x.com"), _operator(client, "bob@x.com")
    assert client.post("/missions/Pad A", headers=alice,
                       json={"body": "moon", "orders": [{"action": "alice"}]}).status_code == 200
    assert client.delete("/missions/Pad A", headers={"X-API-Key": "test-key"}).status_code == 200
    assert client.post("/missions/Pad A", headers=bob,
                       json={"body": "moon", "orders": [{"action": "bob"}]}).status_code == 200

    refused = client.post("/missions/Pad A/restore", headers=bob)
    assert refused.status_code == 403, refused.text
    library_refused = client.post("/library/mission/pad-a/recover", headers=bob)
    assert library_refused.status_code == 403, library_refused.text
    conflict = client.post("/missions/Pad A/restore", headers={"X-API-Key": "test-key"})
    assert conflict.status_code == 409, conflict.text
    library_conflict = client.post(
        "/library/mission/pad-a/recover", headers={"X-API-Key": "test-key"})
    assert library_conflict.status_code == 409, library_conflict.text
    stored = client.get("/missions/Pad A", headers=bob).json()["doc"]
    assert stored["created_by"] == "bob@x.com"
    assert stored["orders"] == [{"action": "bob"}]
