"""P2.2: the versioned, event-sourced OBSERVED-terrain twin (world-model production correctness).

Doctrine (matches world_model L0-L5: "store history, not terrain"): the twin holds a base map plus
an EDIT LOG; the current map is derived by replay. Every edit carries provenance (refused without),
bumps the monotonic version, and is hash-chained so the history is tamper-evident. Undo is event
removal + replay. The CONSERVED physics authority is never mutated through this channel -- the twin
is the perception/ops view (resync patches arrive from reconstruction, not from digging).
"""
import numpy as np
import pytest

from stewie.twin import versioned as vt


def _base():
    rng = np.random.default_rng(7)
    return rng.normal(0.0, 0.05, (64, 64))


def test_version_increments_and_provenance_required():
    tw = vt.TwinStore(_base(), cell_m=0.5)
    assert tw.version == 0
    patch = np.full((8, 8), 0.25)
    v = tw.apply_patch(patch, origin_rc=(10, 12), provenance="resync: COLMAP patch site A")
    assert v == tw.version == 1
    with pytest.raises(ValueError):
        tw.apply_patch(patch, origin_rc=(0, 0), provenance="")


def test_derived_map_is_replay_of_events():
    tw = vt.TwinStore(_base(), cell_m=0.5)
    p1 = np.full((4, 4), 0.1); p2 = np.full((6, 6), -0.2)
    tw.apply_patch(p1, origin_rc=(5, 5), provenance="patch 1")
    tw.apply_patch(p2, origin_rc=(20, 30), provenance="patch 2")
    rebuilt = vt.TwinStore(_base(), cell_m=0.5)
    for ev in tw.events:
        rebuilt.apply_event(ev)
    assert np.array_equal(rebuilt.current(), tw.current())
    assert rebuilt.version == tw.version


def test_undo_restores_previous_bytes():
    tw = vt.TwinStore(_base(), cell_m=0.5)
    tw.apply_patch(np.full((4, 4), 0.1), origin_rc=(5, 5), provenance="keep")
    before = tw.current().tobytes()
    tw.apply_patch(np.full((4, 4), 9.9), origin_rc=(8, 8), provenance="mistake")
    tw.undo()
    assert tw.current().tobytes() == before
    assert tw.version == 3                                # undo is ITSELF a versioned event
    assert tw.events[-1]["kind"] == "undo"


def test_history_is_hash_chained_and_tamper_evident():
    tw = vt.TwinStore(_base(), cell_m=0.5)
    tw.apply_patch(np.full((4, 4), 0.1), origin_rc=(5, 5), provenance="a")
    tw.apply_patch(np.full((4, 4), 0.2), origin_rc=(9, 9), provenance="b")
    assert tw.verify_chain()
    tw.events[0]["provenance"] = "FORGED"
    assert not tw.verify_chain()


def test_out_of_bounds_and_nonfinite_patches_refused():
    tw = vt.TwinStore(_base(), cell_m=0.5)
    with pytest.raises(ValueError):
        tw.apply_patch(np.full((8, 8), 0.1), origin_rc=(60, 60), provenance="oob")
    bad = np.full((4, 4), np.nan)
    with pytest.raises(ValueError):
        tw.apply_patch(bad, origin_rc=(1, 1), provenance="nan patch")


def test_resync_endpoint_roundtrip():
    import importlib
    from fastapi.testclient import TestClient
    import stewie.server.server as srv
    importlib.reload(srv)
    c = TestClient(srv.app)
    patch = np.full((4, 4), 0.3)
    r = c.post("/twin/resync", json={"heights_m": patch.tolist(), "origin_rc": [4, 4],
                                     "provenance": "test reconstruction patch"})
    assert r.status_code == 200 and r.json()["twin_version"] >= 1
    v = c.get("/twin/version").json()
    assert v["twin_version"] == r.json()["twin_version"]
    assert v["events"][-1]["provenance"] == "test reconstruction patch"


def test_w1_durable_journal_survives_process_loss(tmp_path):
    """PRD 6.2 W-1/W-4: every edit appends durably (fsync) to a journal; a COLD restart -- no
    checkpoint, no in-process state -- rebuilds the twin bit-exact from base + journal alone."""
    j = str(tmp_path / "twin.journal")
    tw = vt.TwinStore(_base(), cell_m=0.5, journal_path=j)
    tw.apply_patch(np.full((4, 4), 0.1), origin_rc=(5, 5), provenance="sol-1 resync")
    tw.apply_patch(np.full((6, 6), -0.2), origin_rc=(20, 30), provenance="sol-2 resync")
    tw.undo()
    want = tw.current().tobytes(); want_v = tw.version
    del tw                                                # the process "dies"
    cold = vt.TwinStore.from_journal(_base(), cell_m=0.5, journal_path=j)
    assert cold.current().tobytes() == want               # bit-exact world after cold restore
    assert cold.version == want_v and cold.verify_chain()
    cold.apply_patch(np.full((2, 2), 9.0), origin_rc=(0, 0), provenance="post-recovery edit")
    cold2 = vt.TwinStore.from_journal(_base(), cell_m=0.5, journal_path=j)
    assert cold2.version == cold.version                  # recovery is repeatable after new edits


def test_concurrent_patches_keep_the_chain_consistent(tmp_path):
    """RC-01 [REQ:CT-03]: parallel apply_patch must not corrupt seq/hash/version."""
    import threading

    import numpy as np
    from stewie.twin.versioned import TwinStore
    tw = TwinStore(np.zeros((40, 40)), cell_m=5.0, journal_path=str(tmp_path / "j.jsonl"))
    def worker(i):
        tw.apply_patch(np.full((4, 4), float(i)), origin_rc=(i % 30, i % 30), provenance=f"w{i}")
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(24)]
    for t in ths: t.start()
    for t in ths: t.join()
    seqs = [e["seq"] for e in tw.events]
    assert seqs == list(range(24)) and tw.version == 24      # no lost/duplicate version
    tw.verify_chain()                                        # the hash chain is intact


def test_from_journal_recovers_all_complete_lines_past_a_torn_tail(tmp_path):
    """Twin-gap-1 [REQ:CT-03]: a crash mid-fsync leaves a torn FINAL line; cold restore must
    recover every COMPLETE prior event, not abort the whole replay."""
    import numpy as np
    from stewie.twin.versioned import TwinStore
    jp = str(tmp_path / "j.jsonl")
    tw = TwinStore(np.zeros((20, 20)), cell_m=5.0, journal_path=jp)
    tw.apply_patch(np.ones((3, 3)), origin_rc=(0, 0), provenance="a")
    tw.apply_patch(np.full((3, 3), 2.0), origin_rc=(5, 5), provenance="b")
    with open(jp, "a") as f:
        f.write('{"kind": "patch", "origin_rc": [1, 1], "sha')      # a torn final line
    rebuilt = TwinStore.from_journal(np.zeros((20, 20)), cell_m=5.0, journal_path=jp)
    assert rebuilt.version == 2                                # both complete events recovered
