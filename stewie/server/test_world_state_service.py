"""Step 1 (gap A1): the WorldStateService spine.

DT-01 gave a tested transaction ENVELOPE (``stewie.twin.envelope``), but ``TransactionLog.commit`` was
called NOWHERE outside its own tests -- the log was a library, never a live runtime path. So a route
could plan, resync, or record terrain without producing one canonical linked world-state record.

WorldStateService closes that: it is the server-owned facade that holds the latest-known identity of
each world-state source (conserved authority sha, observed twin, latest plan id, belief) and commits a
``WorldTransaction`` on every meaningful transition. It commits from already-extracted source
IDENTITIES (``TransactionLog.commit_snapshot``) because a world-mutating route -- a resync, a terrain
record -- holds the twin but not a live ColumnState/PlanResult object.

Real TwinStore, real PlanResult/BeliefState/ColumnState contracts -- no synthetic stand-ins; the same
fixture style as test_envelope.py.
"""
from __future__ import annotations

import importlib
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from stewie.contracts import BeliefState, PlanResult
from stewie.physics.column_state import ColumnState
from stewie.server.world_state import WorldStateService
from stewie.twin import envelope as E
from stewie.twin import versioned as vt


def _twin() -> vt.TwinStore:
    """A real observed TwinStore with one applied patch (version 1), as in test_envelope.py."""
    rng = np.random.default_rng(11)
    tw = vt.TwinStore(rng.normal(0.0, 0.05, (32, 32)), cell_m=0.5)
    tw.apply_patch(np.full((4, 4), 0.2), origin_rc=(3, 3), provenance="resync: COLMAP site A")
    return tw


# ---- (1) the facade makes the transaction log a LIVE runtime path -------------------------------

def test_record_plan_commits_one_linked_transaction():
    tw = _twin()
    wss = WorldStateService(twin=tw)
    assert wss.transaction_count() == 0
    txn = wss.record_plan(plan_id="pad-001", provenance="plan accepted",
                          mission="LSP-1", site="haworth", body="moon")
    assert wss.transaction_count() == 1
    assert txn.plan_id == "pad-001"
    assert txn.twin_version == 1 and txn.twin_hash != "genesis"   # the live twin's identity is linked
    assert txn.mission == "LSP-1" and txn.site == "haworth" and txn.body == "moon"
    assert wss.latest() is txn and wss.latest().seq == 0


def test_record_terrain_then_resync_carry_forward_the_other_sources():
    """A terrain record updates the conserved-authority identity; a later resync advances the twin but
    CARRIES FORWARD the last plan + authority -- the transaction is one consistent linked snapshot, not
    four independent reads. (The DT-01 guarantee, now produced at runtime.)"""
    tw = _twin()
    wss = WorldStateService(twin=tw, site="haworth", body="moon")
    wss.record_plan(plan_id="pad-007", provenance="plan", mission="m")
    t_terrain = wss.record_terrain(authority_sha="a" * 64, provenance="terrain.record:m", mission="m")
    assert t_terrain.authority_sha == "a" * 64 and t_terrain.plan_id == "pad-007"  # plan carried forward
    # a NEW twin version (a perception/operator resync), then record it
    tw.apply_patch(np.full((2, 2), 0.4), origin_rc=(0, 0), provenance="resync 2")
    t_resync = wss.record_resync(provenance="twin.resync")
    assert t_resync.twin_version == 2                       # the advanced twin is captured
    assert t_resync.authority_sha == "a" * 64              # authority carried forward
    assert t_resync.plan_id == "pad-007"                  # plan carried forward
    assert wss.transaction_count() == 3
    assert wss.verify_chain()


def test_record_belief_updates_the_belief_snapshot():
    wss = WorldStateService(twin=_twin())
    bel = BeliefState(vehicle_id="ipex", row=4.0, col=5.0, yaw_rad=0.1, pos_sigma_m=0.3)
    txn = wss.record_belief(belief=bel, provenance="belief update")
    assert txn.belief["vehicle_id"] == "ipex" and txn.belief["pos_sigma_m"] == 0.3


def test_chain_is_tamper_evident():
    wss = WorldStateService(twin=_twin())
    wss.record_plan(plan_id="p", provenance="a", mission="m")
    wss.record_resync(provenance="b")
    assert wss.verify_chain()
    wss._log.transactions[0].provenance = "FORGED"
    assert not wss.verify_chain()


def test_provenance_is_mandatory():
    wss = WorldStateService(twin=_twin())
    with pytest.raises(ValueError):
        wss.record_resync(provenance="")


def test_latest_raises_before_any_commit():
    wss = WorldStateService(twin=_twin())
    with pytest.raises(ValueError):
        wss.latest()


# ---- (2) commit_snapshot is equivalent to object-taking commit ----------------------------------

def test_commit_snapshot_matches_object_commit_world_sha():
    """commit_snapshot (identities) and commit (live objects) produce the IDENTICAL world_sha for the
    same linked state -- so the facade's identity-based commits are interchangeable with DT-01's
    object commits. (This is the contract that lets a route without a live ColumnState still commit.)"""
    authority = ColumnState(width=16, height=16, cell_m=0.5)
    tw = _twin()
    plan = PlanResult(plan_id="pad-001", feasible=True, n_orders=3, vehicles=1,
                      makespan_s=420.0, energy_j=1.2e6)
    bel = BeliefState(vehicle_id="ipex", row=4.0, col=5.0, yaw_rad=0.1, pos_sigma_m=0.3)
    by_object = E.TransactionLog().commit(authority=authority, twin=tw, plan=plan, belief=bel,
                                          mission="m", site="haworth", body="moon",
                                          mission_t_s=7.0, provenance="p")
    by_snapshot = E.TransactionLog().commit_snapshot(
        authority_sha=E.authority_sha(authority), twin_version=tw.version,
        twin_hash=tw.events[-1]["hash"], plan_id="pad-001", belief=bel,
        mission="m", site="haworth", body="moon", mission_t_s=7.0, provenance="p")
    assert by_object.world_sha == by_snapshot.world_sha


def test_commit_snapshot_requires_provenance():
    with pytest.raises(ValueError):
        E.TransactionLog().commit_snapshot(authority_sha="x", twin_version=0, twin_hash="genesis",
                                           plan_id="p", belief={}, mission="m", site="s", body="moon",
                                           mission_t_s=0.0, provenance="   ")


# ---- (3) durability: cold restore re-seeds the latest-known source identities --------------------

def test_cold_restore_reseeds_latest_identities(tmp_path):
    """The service journals each commit (W-1). A new service built from the SAME journal cold-restores
    the log AND re-seeds the latest-known identities -- so after a restart the next commit carries
    forward the prior authority/plan/belief, not genesis defaults."""
    jp = str(tmp_path / "world.journal")
    tw = _twin()
    wss = WorldStateService(twin=tw, journal_path=jp, site="haworth", body="moon")
    wss.record_plan(plan_id="pad-099", provenance="plan", mission="restart-mission")
    wss.record_terrain(authority_sha="b" * 64, provenance="terrain")
    del wss

    cold = WorldStateService(twin=tw, journal_path=jp)   # cold restart
    assert cold.transaction_count() == 2
    # a resync after restart carries forward the restored identities (no genesis reset)
    tw.apply_patch(np.full((2, 2), 0.9), origin_rc=(5, 5), provenance="post-restart resync")
    t = cold.record_resync(provenance="resync after restart")
    assert t.authority_sha == "b" * 64           # restored conserved-authority identity
    assert t.plan_id == "pad-099"                # restored plan id
    assert t.mission == "restart-mission"        # restored mission stamp
    assert cold.verify_chain()


# ---- (4) the read route + the world-mutating routes now produce transactions --------------------

@pytest.fixture()
def client(monkeypatch, tmp_path):
    """A keyed server in an isolated data dir, with the lazy twin + world-state singletons reset so
    both rebuild against THIS test's data dir (they are process-globals not reset by conftest)."""
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state as S
    monkeypatch.setattr(S, "_TWIN", None)
    monkeypatch.setattr(S, "_WSS", None)
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


H = {"X-API-Key": "test-key"}


def test_world_transaction_route_empty_then_after_resync(client):
    empty = client.get("/world/transaction", headers=H)
    assert empty.status_code == 200
    assert empty.json() == {"ok": True, "committed": False, "count": 0}

    # a resync MUTATES the observed twin -> it must now produce a linked world transaction
    r = client.post("/twin/resync", headers=H,
                    json={"heights_m": [[0.1, 0.1], [0.1, 0.1]], "origin_rc": [0, 0],
                          "provenance": "operator resync"})
    assert r.status_code == 200, r.text

    after = client.get("/world/transaction", headers=H)
    assert after.status_code == 200
    d = after.json()
    assert d["ok"] is True and d["committed"] is True and d["count"] == 1
    txn = d["transaction"]
    assert txn["provenance"] and txn["twin_version"] >= 1
    assert len(txn["world_sha"]) == 64 and len(txn["chain_hash"]) == 64


def test_world_transaction_route_requires_auth(client, monkeypatch):
    """Fail-closed: with dev-open off and no key, the latest-transaction read is denied."""
    monkeypatch.delenv("STEWIE_DEV_OPEN", raising=False)
    anon = client.get("/world/transaction")
    assert anon.status_code in (401, 403)


_TERRAIN_MISSION = {"name": "pad-A", "body": "moon", "charger": [0, 0],
                    "orders": [{"action": "src", "kind": "cut", "x": 5.0, "y": 5.0,
                                "footprint_m2": 36.0, "depth_m": 0.3}]}


def test_twin_terrain_record_commits_a_world_transaction(client):  # gap G2
    """POST /twin/terrain commits a linked world transaction whose authority_sha is the content hash of
    the recorded as-built surface (not the genesis default), labeled terrain.record."""
    assert client.get("/world/transaction", headers=H).json()["committed"] is False
    r = client.post("/twin/terrain/haworth", headers=H, json={"mission": _TERRAIN_MISSION})
    assert r.status_code == 200, r.text
    txn = client.get("/world/transaction", headers=H).json()["transaction"]
    assert txn["authority_sha"] != "genesis" and len(txn["authority_sha"]) == 64
    assert "terrain.record" in txn["provenance"] and txn["mission"] == "pad-A"


def test_twin_resync_rolls_back_on_a_world_log_failure(client, monkeypatch):  # gap G1 sibling / finding C1 / DT-03
    """DT-03: if the world-state commit fails (here the service accessor raises, as a corrupt world journal
    would), POST /twin/resync must NOT leave the observed twin ahead of /world/transaction -- it
    COMPENSATES (undoes the just-applied patch) and surfaces 500, rather than the old best-effort 200 that
    left the store ahead."""
    from stewie.server import state as S
    pre = S.twin().current()[:2, :2].copy()
    monkeypatch.setattr(S, "world_state_service", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/twin/resync", headers=H,
                    json={"heights_m": [[0.1, 0.1], [0.1, 0.1]], "origin_rc": [0, 0], "provenance": "p"})
    assert r.status_code == 500                                     # surfaced, not swallowed
    assert np.array_equal(S.twin().current()[:2, :2], pre)         # the mutation was compensated (rolled back)


def test_twin_terrain_rolls_back_on_a_world_log_failure(client, monkeypatch):  # finding C1 / DT-03
    """DT-03: if the world-state commit fails, POST /twin/terrain must NOT leave the persisted TerrainMemory
    ahead of /world/transaction -- it COMPENSATES (restores the prior memory) and surfaces 500. (The GET
    reads TerrainMemory directly, not the patched world-state accessor, so it can confirm the rollback.)"""
    from stewie.server import state as S
    monkeypatch.setattr(S, "world_state_service", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.post("/twin/terrain/haworth", headers=H, json={"mission": _TERRAIN_MISSION})
    assert r.status_code == 500                                     # surfaced, not swallowed
    assert client.get("/twin/terrain/haworth", headers=H).json()["recorded"] is False  # rolled back to no-memory


def test_recent_returns_the_window_chronologically():
    """recent(limit) returns the most recent transactions oldest-first within the window -- the
    execution/world timeline the cockpit renders."""
    wss = WorldStateService(twin=_twin())
    for i in range(5):
        wss.record_plan(plan_id=f"p{i}", provenance=f"step {i}", mission="m")
    win = wss.recent(3)
    assert [t["seq"] for t in win] == [2, 3, 4]            # last 3, chronological
    assert win[-1]["plan_id"] == "p4" and "step 4" in win[-1]["provenance"]
    assert all({"seq", "provenance", "world_sha", "twin_version", "plan_id",
                "authority_sha", "mission", "mission_t_s"} <= set(t) for t in win)
    assert wss.recent(0) == []                             # zero window is empty, not an error


def test_world_transactions_route_lists_the_timeline(client):
    empty = client.get("/world/transactions", headers=H).json()
    assert empty["ok"] is True and empty["count"] == 0 and empty["transactions"] == []
    client.post("/twin/resync", headers=H,
                json={"heights_m": [[0.1, 0.1], [0.1, 0.1]], "origin_rc": [0, 0], "provenance": "r1"})
    d = client.get("/world/transactions?limit=10", headers=H).json()
    assert d["count"] == 1 and len(d["transactions"]) == 1
    assert "twin.resync" in d["transactions"][0]["provenance"]


def test_concurrent_records_serialize_and_keep_the_chain_valid():  # gap G4
    """The lock claim, exercised: N threads each commit a transition; all N land, the chain stays valid,
    and seqs are a contiguous 0..N-1 (no lost or interleaved-corrupt record)."""
    wss = WorldStateService(twin=_twin())
    n = 64

    def worker(i: int) -> None:
        wss.record_plan(plan_id=f"p{i}", provenance=f"t{i}", mission="m")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert wss.transaction_count() == n
    assert wss.verify_chain()
    assert sorted(t.seq for t in wss._log.transactions) == list(range(n))
