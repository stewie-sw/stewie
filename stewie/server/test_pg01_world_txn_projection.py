"""[REQ:PG-01] PostgreSQL/PostGIS as a durable persistence/PROJECTION layer, NOT authority: each committed
world-state transaction (DT-01) mirrors to a queryable projection while the conserved TransactionLog stays
the source of truth. Runs against the SQLite fallback (STEWIE_DATA_DIR) -- the exact same code path prod
runs on Postgres/PostGIS via STEWIE_DATABASE_URL, so no Postgres is needed in CI (db.py: URL unset ->
per-data-dir SQLite). The mirror is best-effort: a projection failure NEVER breaks the authoritative commit.
"""
from __future__ import annotations

import numpy as np

from stewie.server import db, world_state
from stewie.twin import versioned as vt


def _twin() -> vt.TwinStore:
    rng = np.random.default_rng(0)
    return vt.TwinStore(rng.normal(0.0, 0.05, (32, 32)), cell_m=0.5)


def test_world_txn_mirrors_to_the_durable_projection_authority_unaffected(monkeypatch, tmp_path):  # [REQ:PG-01]
    """Every committed transition is mirrored to the durable projection (queryable by seq + world_sha),
    while the in-process TransactionLog remains the authority holding the same transactions."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))     # URL unset -> the SQLite fallback (no Postgres)
    db.reset_store()
    wss = world_state.WorldStateService(twin=_twin(), site="haworth", body="moon",
                                        projection_sink=db.mirror_world_txn)
    t1 = wss.record_plan(plan_id="pad-001", provenance="plan accepted", mission="berm")
    t2 = wss.record_resync(provenance="twin.resync", site="haworth")

    # AUTHORITY: the conserved TransactionLog holds both, in order -- the source of truth is untouched.
    assert wss.transaction_count() == 2
    assert wss.latest().seq == t2.seq

    # PROJECTION: the durable read-model mirrors both, keyed by the monotonic seq + the linked world_sha.
    proj = db.read_world_txns()
    assert len(proj) == 2
    assert {p["seq"] for p in proj} == {t1.seq, t2.seq}
    assert {p["world_sha"] for p in proj} == {t1.world_sha, t2.world_sha}
    # the projection carries the DT-01 provenance chain (mission/site/plan + the full linked stamp).
    p1 = next(p for p in proj if p["seq"] == t1.seq)
    assert p1["plan_id"] == "pad-001" and p1["mission"] == "berm" and p1["provenance"] == "plan accepted"
    assert p1["chain_hash"] == t1.chain_hash and p1["linked"]["world_sha"] == t1.world_sha
    db.reset_store()


def test_projection_failure_never_breaks_the_authoritative_commit(monkeypatch, tmp_path):  # [REQ:PG-01]
    """The projection is NON-AUTHORITATIVE: a sink that raises must NOT break the commit -- the transaction
    is still recorded in the authoritative log, and the caller gets its WorldTransaction back."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))

    def _boom(_linked):
        raise RuntimeError("projection store down")

    wss = world_state.WorldStateService(twin=_twin(), projection_sink=_boom)
    txn = wss.record_plan(plan_id="p1", provenance="plan", mission="m")   # must NOT raise
    assert txn.seq >= 0 and wss.transaction_count() == 1                              # the authoritative commit succeeded


def test_no_sink_means_no_projection_write(monkeypatch, tmp_path):  # [REQ:PG-01]
    """Default (no sink): the service commits with zero DB writes -- the projection is opt-in, so the hot
    path is unchanged unless a durable store is wired."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    db.reset_store()
    wss = world_state.WorldStateService(twin=_twin())                     # no projection_sink
    wss.record_plan(plan_id="p", provenance="a", mission="m")
    assert wss.transaction_count() == 1
    assert db.read_world_txns() == []                                    # nothing mirrored
    db.reset_store()


def test_projection_sink_is_wired_only_when_a_durable_store_is_configured(monkeypatch):  # [REQ:PG-01]
    """The app wires the projection into world_state_service ONLY when STEWIE_DATABASE_URL is set (a durable
    Postgres/PostGIS store), so prod persists the chain while CI/dev adds no per-transaction DB write."""
    from stewie.server import db, state
    monkeypatch.delenv("STEWIE_DATABASE_URL", raising=False)
    assert state._world_txn_projection_sink() is None                # no durable store -> no mirroring
    monkeypatch.setenv("STEWIE_DATABASE_URL", "postgresql+asyncpg://u:p@postgres:5432/stewie")
    assert state._world_txn_projection_sink() is db.mirror_world_txn  # durable store -> mirror to the projection
