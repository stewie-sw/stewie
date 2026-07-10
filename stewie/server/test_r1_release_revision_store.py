"""[dispatch-audit R1] Freeze + persist a canonical IMMUTABLE release revision.

The dispatch audit (design/STEWIE_DISPATCH_AGENT_AUDIT_2026-07-09.md, finding R1) found that a released
mission ALREADY produces a signed immutable revision (MO-02 ``SignedRevision``: the frozen intent + a
deterministic content_hash + the director sign-off), but it was NEVER persisted durably -- the signed
revision lived only in the ``/executive/release-plan`` / ``/executive/advance`` HTTP response and was then
discarded with the in-process executive. So there was no store a later run / RC could BIND to (the R2
defect: ``/executive/run`` rebuilds a fresh release from mutable ``orders`` every time, never binding what
was signed).

R1 is the FOUNDATION: a durable release-revision store keyed by the content_hash (the PG-01 db.py pattern --
SQLite fallback in CI, Postgres in prod), persisted on release, fetchable by hash, and IMMUTABLE (first
write for a hash wins; the same intent always yields the same hash; a mutated order yields a different one).

Runs on the SQLite fallback (per-test STEWIE_DATA_DIR) -- the exact code path prod runs on Postgres via
STEWIE_DATABASE_URL, so no Postgres is needed in CI. Real store + the FastAPI app via a TestClient; nothing
synthetic.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import operators as OPS
    importlib.reload(OPS)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app), "test-key"
    monkeypatch.undo()
    importlib.reload(srv)


def _plan_payload(depth_m: float = 0.2):
    # a real cut + a smaller fill (feasible) + a goto waypoint (skipped, not an objective).
    return {
        "body": "moon", "mission_id": "M-r1-1",
        "orders": [
            {"action": "Pad cut", "kind": "cut", "x": 10.0, "y": 5.0, "footprint_m2": 9.0, "depth_m": depth_m},
            {"action": "Berm fill", "kind": "fill", "x": 4.0, "y": 5.0, "footprint_m2": 4.0, "depth_m": 0.1},
            {"action": "wp1", "kind": "goto", "x": 0.0, "y": 0.0},
        ],
    }


def test_release_persists_the_revision_and_it_is_fetchable_by_hash(client):  # [dispatch-audit R1]
    c, key = client
    r = c.post("/executive/release-plan", headers={"X-API-Key": key}, json=_plan_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "released"
    assert body["revision_persisted"] is True                     # R1: the signed revision was durably stored
    ch = body["signed_revision"]["content_hash"]
    assert len(ch) == 64

    # fetch the FROZEN artifact by its content hash -- byte-identical to what was signed.
    g = c.get(f"/executive/revision/{ch}", headers={"X-API-Key": key})
    assert g.status_code == 200, g.text
    art = g.json()["revision"]
    assert art["content_hash"] == ch
    assert art["signed_revision"] == body["signed_revision"]       # the whole frozen SignedRevision round-trips
    assert art["mission_id"] == "M-r1-1" and art["signed_by"] == "director"
    assert art["evidence"]["plan_id"] == body["evidence"]["plan_id"]   # the analyze plan_ir hash is frozen with it
    # the approval evidence (the ordered transition log) is frozen with the revision.
    assert [t["to"] for t in art["transitions"]] == ["analyzed", "rehearsed", "reviewed", "released"]


def test_advance_route_also_persists_its_signed_revision(client):  # [dispatch-audit R1]
    """The MO-01-intent advance surface persists on release too, not only the build-order surface."""
    c, key = client
    intent = {
        "mission_id": "M-adv-1", "revision": 0, "statement": "prepare the pad",
        "objectives": [{
            "objective_id": "O-1", "revision": 0, "statement": "flatten the pad", "rationale": "level",
            "priority": "primary", "mandatory": True, "target_row": 100.0, "target_col": 120.0,
            "frame": "MOON_ME",
            "acceptance": [{"criterion_id": "a1", "statement": "flat", "measurable": "RMSE <= 0.02 m",
                            "sensor": "dem_overlay"}],
            "confidence_required": 0.9, "material_budget_kg": 50.0,
            "contingency": {"policy": "replan", "detail": "retry"}, "approver": "director",
            "evidence": "memo",
        }],
        "constraints": [], "task_graph_ref": "planir-1",
    }
    r = c.post("/executive/advance", headers={"X-API-Key": key}, json=intent)
    assert r.status_code == 200, r.text
    assert r.json()["revision_persisted"] is True
    ch = r.json()["signed_revision"]["content_hash"]
    assert c.get(f"/executive/revision/{ch}", headers={"X-API-Key": key}).status_code == 200


def test_same_orders_same_hash_mutated_order_different_hash(client):  # [dispatch-audit R1]
    """Immutability by construction: the content_hash is a pure function of the released intent, so the SAME
    plan always freezes to the SAME hash (idempotent re-release), and any content change yields a NEW hash
    (a distinct immutable revision)."""
    c, key = client
    h1 = c.post("/executive/release-plan", headers={"X-API-Key": key},
                json=_plan_payload(depth_m=0.2)).json()["signed_revision"]["content_hash"]
    h1b = c.post("/executive/release-plan", headers={"X-API-Key": key},
                 json=_plan_payload(depth_m=0.2)).json()["signed_revision"]["content_hash"]
    h2 = c.post("/executive/release-plan", headers={"X-API-Key": key},
                json=_plan_payload(depth_m=0.5)).json()["signed_revision"]["content_hash"]
    assert h1 == h1b            # same orders -> same frozen revision (deterministic, no wall clock)
    assert h1 != h2             # a mutated order -> a different immutable revision

    # the store holds exactly the two distinct revisions, each fetchable and immutable.
    assert c.get(f"/executive/revision/{h1}", headers={"X-API-Key": key}).status_code == 200
    assert c.get(f"/executive/revision/{h2}", headers={"X-API-Key": key}).status_code == 200


def test_fetch_unknown_hash_is_404(client):  # [dispatch-audit R1]
    c, key = client
    r = c.get("/executive/revision/" + "0" * 64, headers={"X-API-Key": key})
    assert r.status_code == 404, r.text
    assert r.json()["ok"] is False


def test_fetch_route_is_gated(client):  # [dispatch-audit R1]
    """The revision store is read-gated (operator+), never anonymously egress-able."""
    c, _key = client
    r = c.get("/executive/revision/" + "0" * 64)   # no key
    assert r.status_code in (401, 403), r.text


def test_store_is_immutable_first_write_wins(monkeypatch, tmp_path):  # [dispatch-audit R1]
    """The durable store never overwrites an existing content_hash: the first persisted artifact for a hash
    is the frozen one, so a later (bugged/malicious) write under the same hash cannot mutate what was signed.
    Direct db-level check on the SQLite fallback (the same code path prod runs on Postgres)."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import db
    db.reset_store()
    art = {"content_hash": "a" * 64, "revision": 0, "mission_id": "M", "signed_by": "director",
           "signed_revision": {"content_hash": "a" * 64, "revision": 0, "signed_by": "director",
                               "intent": {"mission_id": "M"}},
           "evidence": {"plan_id": "p1"}, "transitions": [{"to": "released"}]}
    assert db.persist_release_revision(art) is True
    # a second write under the SAME hash with DIFFERENT content must NOT overwrite the frozen artifact.
    tampered = dict(art, mission_id="TAMPERED", evidence={"plan_id": "EVIL"})
    db.persist_release_revision(tampered)
    got = db.read_release_revision("a" * 64)
    assert got is not None
    assert got["mission_id"] == "M" and got["evidence"]["plan_id"] == "p1"   # the ORIGINAL, unmutated
    assert db.read_release_revision("f" * 64) is None                        # unknown hash -> None
    db.reset_store()
