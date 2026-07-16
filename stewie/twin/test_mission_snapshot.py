"""[REQ:BR-02] Mission-snapshot versioning as the branchable replay/ML lineage unit.

A COMPLETED mission (MO-02 MissionExecutive in COMPLETED, carrying a signed released revision) writes an
IMMUTABLE MissionSnapshot into a per-body MissionLineage (Moon -> mission 000 -> 001 -> ... -> N). The
three acceptance claims, each on the REAL data path (a real Haworth DEM window + the RS-04 run_replay
keystone + the MO-02 executive), never on synthetic data:

  1. a completed mission writes an immutable snapshot to a lineage (a non-COMPLETED mission is refused;
     the snapshot_id is content-addressed and re-derives bit-exact; a duplicate write is refused);
  2. a snapshot replays deterministically (re-running the recorded ReplayKey reproduces the run_sha
     bit-exact; a DIFFERENT DEM window is refused -- you cannot replay a mission against another world);
  3. a snapshot is selectable as a branch parent for what-if/retrain (branch_from(snap) forks a child
     whose parent_id is that snapshot, so the lineage is a DAG: one parent fans out to many children).

A durable journal + cold reload reproduces every snapshot_id bit-exact (the lineage is deterministic).
"""
from __future__ import annotations

import importlib

import numpy as np
import pytest

from stewie.contracts.executive import ExecutiveState, MissionExecutive
from stewie.contracts.mission_ops import MissionIntent
from stewie.runtime.replay_loop import run_replay
from stewie.twin.mission_snapshot import (
    MissionLineage,
    MissionSnapshot,
    ReplayKey,
    dem_window_sha,
)

_START = (5 * 5.0, 5 * 5.0)      # window cell (5,5) at 5 m/cell  (matches the RS-04 keystone test)
_GOAL = (50 * 5.0, 50 * 5.0)     # window cell (50,50)


@pytest.fixture(scope="module")
def window():
    from stewie.server import state as S
    dem, _ = S.moon_dem("haworth")
    z, cell = np.asarray(dem[0]), float(dem[1])
    return z[500:560, 1700:1760].copy(), cell     # the real, traversable replay frame


@pytest.fixture()
def wss(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_WSS", None)
    return S.world_state_service()


def _completed_executive(mission_id: str, revision: int = 0) -> MissionExecutive:
    """Drive a real MO-02 executive DRAFT -> ... -> COMPLETED so it carries a signed released revision."""
    intent = MissionIntent(mission_id=mission_id, revision=revision, statement="dig a pad")
    ex = MissionExecutive.start(intent)
    ex = ex.transition(ExecutiveState.ANALYZED, role="planner", evidence="plan analyzed")
    ex = ex.transition(ExecutiveState.REHEARSED, role="operator", evidence="rehearsed in sim")
    ex = ex.transition(ExecutiveState.REVIEWED, role="reviewer", evidence="safety reviewed")
    ex = ex.transition(ExecutiveState.RELEASED, role="director", evidence="director sign-off")
    ex = ex.transition(ExecutiveState.ARMED, role="operator", evidence="armed")
    ex = ex.transition(ExecutiveState.EXECUTING, role="operator", evidence="executing")
    ex = ex.transition(ExecutiveState.COMPLETED, role="operator", evidence="objectives met")
    assert ex.state is ExecutiveState.COMPLETED and ex.released_revision is not None
    return ex


def _run_and_key(z, cell, *, wss, **seeds) -> tuple:
    """Run the RS-04 keystone over the real DEM window and build the ReplayKey + world transaction."""
    b = run_replay(z, cell, _START, _GOAL, wss=wss, **seeds)
    key = ReplayKey(dem_window_sha=dem_window_sha(z), cell_m=cell, start_xy=_START, goal_xy=_GOAL,
                    expected_run_sha=b.run_sha,
                    seed_hazard_rc=seeds.get("seed_hazard_rc"),
                    seed_rock_rc=seeds.get("seed_rock_rc"),
                    seed_uncertainty_rc=seeds.get("seed_uncertainty_rc"),
                    eligible=seeds.get("eligible", True))
    return b, key


# --- 1. a completed mission writes an immutable snapshot to a lineage --------------------------------

def test_completed_mission_writes_an_immutable_snapshot_to_the_lineage(window, wss):
    z, cell = window
    b, key = _run_and_key(z, cell, wss=wss)
    lin = MissionLineage(body="moon")
    snap = lin.write_completed_mission(executive=_completed_executive("m0"),
                                       world_txn=b.world_transaction, replay=key,
                                       provenance="keystone completed mission")

    assert isinstance(snap, MissionSnapshot)
    assert lin.snapshots == [snap] and lin.latest() is snap
    assert snap.mission_number == 0 and snap.mission_name == "mission_000"
    assert snap.parent_id is None                              # the root mission of the lineage
    assert snap.body == "moon"
    # the snapshot binds the mission's immutable identities: the DT-01 world_sha + the MO-02 plan hash.
    assert snap.world_sha == b.world_transaction["world_sha"] and len(snap.world_sha) == 64
    assert len(snap.plan_content_hash) == 64
    # content-addressed + immutable: the id re-derives bit-exact from the snapshot's own content,
    # and the frozen record cannot be mutated in place.
    assert len(snap.snapshot_id) == 64 and snap.recomputed_id() == snap.snapshot_id
    import dataclasses
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.world_sha = "0" * 64                             # type: ignore[misc]


def test_a_non_completed_mission_is_refused(window, wss):
    z, cell = window
    b, key = _run_and_key(z, cell, wss=wss)
    lin = MissionLineage(body="moon")
    intent = MissionIntent(mission_id="m0", revision=0, statement="dig a pad")
    executing = (MissionExecutive.start(intent)
                 .transition(ExecutiveState.ANALYZED, role="planner", evidence="e")
                 .transition(ExecutiveState.REHEARSED, role="operator", evidence="e")
                 .transition(ExecutiveState.REVIEWED, role="reviewer", evidence="e")
                 .transition(ExecutiveState.RELEASED, role="director", evidence="e")
                 .transition(ExecutiveState.ARMED, role="operator", evidence="e")
                 .transition(ExecutiveState.EXECUTING, role="operator", evidence="e"))
    with pytest.raises(ValueError, match="COMPLETED"):
        lin.write_completed_mission(executive=executing, world_txn=b.world_transaction, replay=key,
                                    provenance="not done yet")
    assert lin.snapshots == []                                 # nothing was written


def test_duplicate_immutable_snapshot_is_refused(window, wss):
    z, cell = window
    b, key = _run_and_key(z, cell, wss=wss)
    lin = MissionLineage(body="moon")
    ex = _completed_executive("m0")
    lin.write_completed_mission(executive=ex, world_txn=b.world_transaction, replay=key, provenance="p")
    # same completed mission, same world state, same parent -> same content -> same id: refuse the rewrite.
    with pytest.raises(ValueError, match="duplicate"):
        lin.write_completed_mission(executive=ex, world_txn=b.world_transaction, replay=key,
                                    provenance="p", parent_id=None)


# --- 2. a snapshot replays deterministically --------------------------------------------------------

def test_snapshot_replays_deterministically(window, wss, monkeypatch, tmp_path):
    z, cell = window
    b, key = _run_and_key(z, cell, wss=wss, seed_hazard_rc=(25, 25))
    lin = MissionLineage(body="moon")
    snap = lin.write_completed_mission(executive=_completed_executive("m0"),
                                       world_txn=b.world_transaction, replay=key, provenance="p")

    # replay over the SAME real DEM window on a FRESH world-state service reproduces the run_sha bit-exact.
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path / "replay"))
    from stewie.server import state as S
    importlib.reload(S)
    monkeypatch.setattr(S, "_WSS", None)
    replayed = snap.replay.replay(z, wss=S.world_state_service())
    assert replayed.run_sha == snap.replay.expected_run_sha == b.run_sha


def test_replay_against_a_different_world_is_refused(window, wss):
    z, cell = window
    b, key = _run_and_key(z, cell, wss=wss)
    other = z.copy()
    other[0, 0] += 1.0                                         # a different DEM window (world)
    with pytest.raises(ValueError, match="frame"):
        key.replay(other, wss=wss)


# --- 3. a snapshot is selectable as a branch parent for what-if/retrain ------------------------------

def test_snapshot_is_selectable_as_a_branch_parent(window, wss):
    z, cell = window
    lin = MissionLineage(body="moon")

    b0, k0 = _run_and_key(z, cell, wss=wss)
    m000 = lin.write_completed_mission(executive=_completed_executive("m0"),
                                       world_txn=b0.world_transaction, replay=k0, provenance="p")
    # a linear continuation: the next mission's parent defaults to the latest snapshot.
    b1, k1 = _run_and_key(z, cell, wss=wss, seed_hazard_rc=(25, 25))
    m001 = lin.write_completed_mission(executive=_completed_executive("m1"),
                                       world_txn=b1.world_transaction, replay=k1, provenance="p")
    assert m001.parent_id == m000.snapshot_id and m001.mission_number == 1

    # a WHAT-IF branch: select m000 as the branch parent and fork a retrain child off it (not off m001).
    parent = lin.branch_from(m000)
    assert parent == m000.snapshot_id
    b2, k2 = _run_and_key(z, cell, wss=wss, seed_rock_rc=(25, 25))
    whatif = lin.write_completed_mission(executive=_completed_executive("m2"),
                                         world_txn=b2.world_transaction, replay=k2, provenance="what-if",
                                         parent_id=parent)
    assert whatif.parent_id == m000.snapshot_id and whatif.mission_number == 2

    # the lineage is a DAG: m000 now fans out to BOTH the linear child and the what-if child.
    kids = {s.snapshot_id for s in lin.children_of(m000.snapshot_id)}
    assert kids == {m001.snapshot_id, whatif.snapshot_id}
    assert [s.snapshot_id for s in lin.root_missions()] == [m000.snapshot_id]
    # branching from a stranger id (not in this lineage) is refused.
    with pytest.raises(ValueError, match="lineage"):
        lin.branch_from("f" * 64)


# --- durability: cold reload reproduces every snapshot_id bit-exact ---------------------------------

def test_lineage_cold_reload_reproduces_every_snapshot_id(window, wss, tmp_path):
    z, cell = window
    jp = str(tmp_path / "moon_lineage.jsonl")
    lin = MissionLineage(body="moon", journal_path=jp)
    b0, k0 = _run_and_key(z, cell, wss=wss)
    s0 = lin.write_completed_mission(executive=_completed_executive("m0"),
                                     world_txn=b0.world_transaction, replay=k0, provenance="p")
    b1, k1 = _run_and_key(z, cell, wss=wss, seed_hazard_rc=(25, 25))
    s1 = lin.write_completed_mission(executive=_completed_executive("m1"),
                                     world_txn=b1.world_transaction, replay=k1, provenance="p")

    cold = MissionLineage.from_journal("moon", jp)
    assert [s.snapshot_id for s in cold.snapshots] == [s0.snapshot_id, s1.snapshot_id]
    assert all(s.recomputed_id() == s.snapshot_id for s in cold.snapshots)
    assert cold.snapshots[1].parent_id == cold.snapshots[0].snapshot_id
