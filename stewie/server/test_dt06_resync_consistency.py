"""[REQ:DT-06] twin dirty-read consistency under concurrent resync (extends DT-03).

A /world read concurrent with a /resync write must return ONE consistent (mask, heights, version) triple,
never a torn read mixing pre-/post-resync state. The mechanism is a single mutex, state._RESYNC_LOCK, held
by BOTH sides: the observed-twin READ holds it while sampling (mask, heights, version) as one triple
(state.current_terrain_view -> state.py, proven by test_current_terrain_view_reads_the_twin_under_the_resync_lock),
and the resync WRITE holds it across the whole apply_patch..world-commit..compensate critical section
(routers/twin.py::twin_resync). This module proves the WRITE half + that both sides serialize on the SAME
lock, so together with the existing read-side test the no-torn-read guarantee is complete.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).parents[2]


def test_resync_write_holds_the_resync_lock(monkeypatch, tmp_path):  # [REQ:DT-06]
    """The WRITE half: the /twin/resync critical section (apply_patch..world-commit..compensate) holds
    state._RESYNC_LOCK during the mutation, so the observed-twin read (which acquires the same lock) cannot
    observe the twin mid-resync — a dirty read of a patch that may still be undone by the compensating rollback."""
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    from stewie.server import state
    from stewie.server.routers import twin as twin_router
    seen = {"locked_during_mutation": None}

    class _FakeTwin:
        version = 7

        def apply_patch(self, heights_m, *, origin_rc, provenance):
            seen["locked_during_mutation"] = state._RESYNC_LOCK.locked()   # MUST be held while mutating
            return 8

        def undo(self):
            return 7

    class _FakeWSS:
        def record_resync(self, *, provenance, site):
            # the world-state commit runs INSIDE the same critical section; assert the lock still holds here.
            seen["locked_during_commit"] = state._RESYNC_LOCK.locked()

    monkeypatch.setattr(state, "twin", lambda *a, **k: _FakeTwin())
    monkeypatch.setattr(state, "world_state_service", lambda: _FakeWSS())
    req = twin_router.ResyncRequest(heights_m=[[0.0]], origin_rc=(0, 0), provenance="dt06-test", site="haworth")
    out = twin_router.twin_resync(req, identity="operator")

    assert seen["locked_during_mutation"] is True, "apply_patch ran outside the resync lock (torn read possible)"
    assert seen.get("locked_during_commit") is True, "the world-state commit ran outside the resync lock"
    assert out["ok"] is True and out["twin_version"] == 8


def test_read_and_write_serialize_on_the_same_resync_lock():  # [REQ:DT-06]
    """Both sides acquire the SAME module-level mutex (state._RESYNC_LOCK) — the read via the bare name inside
    state.py, the write via state._RESYNC_LOCK in routers/twin.py — so the critical sections are mutually
    exclusive. A different lock on each side would not prevent a torn read; assert they are the same one."""
    state_src = (_ROOT / "stewie" / "server" / "state.py").read_text(encoding="utf-8")
    twin_src = (_ROOT / "stewie" / "server" / "routers" / "twin.py").read_text(encoding="utf-8")
    assert "_RESYNC_LOCK = threading.Lock()" in state_src, "the resync mutex is not defined in state.py"
    assert "with _RESYNC_LOCK:" in state_src, "the observed-twin READ does not hold the resync lock"
    assert "with state._RESYNC_LOCK:" in twin_src, "the resync WRITE does not hold state._RESYNC_LOCK"
