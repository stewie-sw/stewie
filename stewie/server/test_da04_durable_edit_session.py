"""[REQ:DA-04] Durable edit sessions (GW-08 -> persistent store).

DA-04 is the §7.B P1 promotion of the GW-08 Phase-0 persistence work: the mission-feature edit session
moved off the process-memory registry into the durable store (``server.db`` -- Postgres/PostGIS in prod via
``$STEWIE_DATABASE_URL``, a per-``$STEWIE_DATA_DIR`` SQLite file in CI/dev), so an in-progress edit session
plus its versioned before/after audit and undo state SURVIVE a backend restart.

The DA-04 acceptance sentence, verbatim: *a session created, mutated, then reloaded after a simulated
restart replays identically.* These tests assert exactly that -- and the distinct DA-04 property beyond a
static snapshot: after the reload the session is a LIVE object again (its version/fid counters resume, and
a fresh edit + undo append onto the reconstructed audit trail), so the restart is transparent to the
ongoing edit session, not merely a recoverable dump.

``drop_in_memory_cache()`` simulates the restart: it forgets every cached EditSession instance AND drops
the DB engine + connection pool, so ``get_session`` MUST reload from the durable rows. Uses no data at all
(the store holds only operator-drawn geometry), matching ``test_edit_session_persistence.py``.
"""
import pytest

from stewie.server import edit_session as ES


@pytest.fixture(autouse=True)
def _reset_sessions():
    """The session registry + durable store are process-global; reset (truncate) around each test."""
    ES.reset()
    yield
    ES.reset()


def _author_a_mutated_session() -> ES.EditSession:
    """Create a session and MUTATE it through the full public surface: two keep-outs, a marker, a modify,
    a delete, and an undo. Leaves a non-trivial live set + a versioned before/after audit + live undo state
    -- the 'created, mutated' half of the DA-04 acceptance sentence."""
    sess = ES.new_session()
    ko1 = sess.create("circle", {"cx": 10.0, "cy": 5.0, "r": 3.0})          # v1
    ko2 = sess.create("polygon", {"ring": [[0, 0], [10, 0], [10, 10]]})     # v2
    sess.create_marker({"x": 12.0, "y": -4.0, "otype": "beacon", "label": "Nav beacon"})  # v3
    sess.modify(ko1["fid"], "circle", {"cx": 99.0, "cy": 99.0, "r": 7.0})   # v4
    sess.delete(ko2["fid"])                                                  # v5
    sess.undo()                                                             # v6: revert the delete -> ko2 back
    return sess


def test_da04_created_mutated_session_replays_identically_after_restart():
    """The DA-04 acceptance, verbatim: created + mutated, then reloaded after a simulated restart, the
    session replays IDENTICALLY -- version, live keep-outs, live markers, and the whole before/after audit
    trail round-trip byte-for-byte, on a freshly reconstructed instance (not the surviving object)."""
    sess = _author_a_mutated_session()
    sid = sess.id

    before_version = sess.version
    before_features = sess.current_features()
    before_markers = sess.current_markers()
    before_audit = sess.audit()
    # the undo restored ko2 (the delete's inverse) and left ko1 at its modified geometry
    assert before_version == 6
    assert [f["fid"] for f in before_features] == ["ko1", "ko2"]
    assert before_features[0]["cx"] == 99.0            # ko1 keeps its modify; only the delete was undone
    assert len(before_markers) == 1

    # --- SIMULATE A RESTART: cache + DB engine/pool gone; only the durable rows remain ---
    ES.drop_in_memory_cache()

    reloaded = ES.get_session(sid)
    assert reloaded is not None, "the created+mutated session was LOST across the restart (DA-04 defect)"
    assert reloaded is not sess, "a fresh instance was reconstructed from the store, not the surviving object"

    # replays IDENTICALLY: every observable facet equals the pre-restart snapshot
    assert reloaded.version == before_version
    assert reloaded.current_features() == before_features
    assert reloaded.current_markers() == before_markers
    assert reloaded.audit() == before_audit


def test_da04_reloaded_session_continues_the_replay_transparently():
    """DA-04's distinct property: the reload restores a LIVE session, not a static dump. After the restart
    the version + fid counters resume from the persisted values and a fresh edit + undo append onto the
    reconstructed audit trail -- so the restart is transparent to the still-open edit session, and that
    continuation itself persists across a SECOND restart."""
    sess = _author_a_mutated_session()
    sid = sess.id
    resume_version = sess.version                      # 6

    ES.drop_in_memory_cache()                          # restart #1
    reloaded = ES.get_session(sid)
    assert reloaded is not None

    # a new keep-out gets the NEXT fid (counters reloaded, no reset to ko1) and the NEXT version
    new_ko = reloaded.create("circle", {"cx": -1.0, "cy": -2.0, "r": 4.0})
    assert new_ko["fid"] == "ko3", "fid counter reset across the restart -> a colliding fid (DA-04 defect)"
    assert reloaded.version == resume_version + 1      # v7, appended onto the reconstructed trail
    assert reloaded.audit()[-1]["op"] == "create" and reloaded.audit()[-1]["version"] == resume_version + 1

    # an undo after the reload walks the RECONSTRUCTED audit LIFO (compensates the just-added create)
    undone = reloaded.undo()
    assert undone["reverted_op"] == "create" and undone["fid"] == "ko3"
    assert reloaded.version == resume_version + 2      # v8
    assert [f["fid"] for f in reloaded.current_features()] == ["ko1", "ko2"]   # ko3 compensated away

    # the CONTINUATION persists too: a second restart replays the post-reload edits identically
    after_version = reloaded.version
    after_features = reloaded.current_features()
    after_audit = reloaded.audit()

    ES.drop_in_memory_cache()                          # restart #2
    again = ES.get_session(sid)
    assert again is not None and again is not reloaded
    assert again.version == after_version
    assert again.current_features() == after_features
    assert again.audit() == after_audit
