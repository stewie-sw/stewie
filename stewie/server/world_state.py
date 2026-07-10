"""Step 1 / gap A1: the server-owned WorldStateService spine.

DT-01 (``stewie.twin.envelope``) gave a tested, durable, hash-chained transaction ENVELOPE -- but
``TransactionLog.commit`` was called nowhere outside its own tests. The log was a library, not a live
runtime path, so the product could plan, resync, or record terrain without producing one canonical
linked world-state record. That is the architecture gap A1 (one runtime world-state authority is
missing): conserved authority, terrain memory, observed twin, plan, and belief were all read/written
independently.

WorldStateService is the route-level facade that closes it. It holds the LATEST-KNOWN identity of each
world-state source -- the conserved-authority sha, the observed twin (read live), the latest plan id,
and the belief snapshot -- and commits a ``WorldTransaction`` on every meaningful transition
(``record_plan`` / ``record_terrain`` / ``record_resync`` / ``record_belief`` /
``record_execution_event``). It commits from IDENTITIES (``TransactionLog.commit_snapshot``) because a
world-mutating route -- a resync, a terrain record -- holds the twin but not a live ColumnState or
PlanResult object. Sources a transition does not touch are CARRIED FORWARD, so each record is one
consistent linked snapshot (the DT-01 guarantee), produced at runtime.

HONESTY: this makes the transaction log a live runtime path and gives the other routes one facade to
adopt. It does not by itself force EVERY route through a commit yet (the SIM-execute path is wired in a
later step); it links and durably records the current source identities, adding no new perception,
autonomy, or physics fidelity.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable

from stewie.twin import envelope as E
from stewie.twin import terrain_memory as TM

if TYPE_CHECKING:
    from stewie.contracts import BeliefState
    from stewie.twin.envelope import WorldTransaction
    from stewie.twin.versioned import TwinStore

log = logging.getLogger("stewie.server")


@contextmanager
def compensating(compensate: Callable[[], object], *, what: str) -> Iterator[None]:
    """DT-03: run a world-state COMMIT for a store mutation that has ALREADY been applied, atomically.

    A world-mutating route applies its store mutation first (a twin patch, a TerrainMemory save) and then
    must commit the linked ``WorldTransaction`` so the store can never run AHEAD of ``/world/transaction``.
    If that commit RAISES (e.g. a corrupt world journal, which DT-01 surfaces by raising), the store would
    otherwise be left ahead. This context manager runs ``compensate`` -- the caller's rollback of its own
    already-applied mutation (``twin.undo`` / restore the prior TerrainMemory file) -- and then RE-RAISES so
    the route surfaces the failure honestly. It REPLACES the prior best-effort ``try/except Exception: pass``
    that swallowed the failure and left the store ahead. On success it is transparent (no compensation)."""
    try:
        yield
    except Exception:
        try:
            compensate()
        except Exception:   # noqa: BLE001 -- a compensation failure must not MASK the original commit error
            log.exception("DT-03: compensation for %s failed after a world-state commit error", what)
        raise


class WorldStateService:
    """One linked world-state authority over the existing sources. Thread-safe: every transition takes
    one lock so the read-modify-commit of the latest-known identities cannot interleave."""

    def __init__(self, *, twin: "TwinStore | Callable[[], TwinStore]",
                 log: "E.TransactionLog | None" = None, journal_path: str | None = None,
                 body: str = "moon", site: str = "haworth",
                 projection_sink: "Callable[[dict], object] | None" = None) -> None:
        self._twin = twin                                    # a TwinStore or a zero-arg accessor
        # [PG-01] optional DURABLE PROJECTION sink: called best-effort with each committed transaction's
        # linked_body() so a Postgres/PostGIS (or SQLite) read-model mirrors the provenance chain. It is
        # NON-AUTHORITATIVE -- a sink failure is caught + logged, never breaking the authoritative commit.
        self._projection_sink = projection_sink
        if log is not None:
            self._log = log
        elif journal_path is not None:
            self._log = E.TransactionLog.from_journal(journal_path)   # W-4 cold restore
        else:
            self._log = E.TransactionLog()
        self._body = str(body)
        self._site = str(site)
        self._authority_sha = "genesis"                      # latest conserved-authority identity
        self._plan_id = "none"                               # latest plan id
        self._belief: dict = {}                              # latest belief snapshot
        self._mission = "none"
        self._mission_t_s = 0.0
        self._lock = threading.Lock()
        self._seed_from_latest()                             # durability: restore identities on restart

    # ---- internal -------------------------------------------------------------------------------
    def _seed_from_latest(self) -> None:
        """On a cold restore the journal already holds the prior linked state; re-seed the
        latest-known identities from it so the next commit carries them forward (not genesis)."""
        if self._log.transactions:
            t = self._log.latest()
            self._authority_sha = t.authority_sha
            self._plan_id = t.plan_id
            self._belief = dict(t.belief)
            self._mission = t.mission
            self._site = t.site
            self._body = t.body
            self._mission_t_s = t.mission_t_s

    def _twin_obj(self) -> "TwinStore":
        return self._twin() if callable(self._twin) else self._twin

    def _commit_locked(self, *, provenance: str, mission: str | None, site: str | None,
                       body: str | None, mission_t_s: float | None,
                       uncertainty_m: float) -> "WorldTransaction":
        """Commit one linked snapshot from the current latest-known identities + the live twin. Caller
        holds ``self._lock``."""
        if mission is not None:
            self._mission = str(mission)
        if site is not None:
            self._site = str(site)
        if body is not None:
            self._body = str(body)
        if mission_t_s is not None:
            self._mission_t_s = float(mission_t_s)
        tw = self._twin_obj()
        if hasattr(tw, "identity"):                       # atomic (version, hash) under the twin's lock
            t_ver, t_hash = tw.identity()
        else:                                            # duck-typed fallback (e.g. a bare stub twin)
            t_ver = int(getattr(tw, "version", 0))
            events = getattr(tw, "events", None)
            t_hash = events[-1]["hash"] if events else "genesis"
        txn = self._log.commit_snapshot(
            authority_sha=self._authority_sha, twin_version=t_ver, twin_hash=t_hash,
            plan_id=self._plan_id, belief=self._belief, mission=self._mission, site=self._site,
            body=self._body, mission_t_s=self._mission_t_s, provenance=provenance,
            uncertainty_m=uncertainty_m)
        # [PG-01] mirror the just-committed transaction to the durable projection, BEST-EFFORT. The authority
        # (the TransactionLog + its journal) has already committed above; a projection failure is logged and
        # swallowed so the read-model can never break the authoritative write.
        if self._projection_sink is not None:
            try:
                # linked_body() is the hashed content (everything EXCEPT chain_hash, which is its digest);
                # add chain_hash back so the projection stores the COMPLETE tamper-evident record.
                self._projection_sink({**txn.linked_body(), "chain_hash": txn.chain_hash})
            except Exception as e:   # noqa: BLE001 -- the projection is NON-AUTHORITATIVE by design
                log.warning("PG-01: world-txn projection mirror failed (non-authoritative): %s", e)
        return txn

    # ---- transitions (the facade) ---------------------------------------------------------------
    def record_plan(self, *, plan_id: str, provenance: str, mission: str | None = None,
                    site: str | None = None, body: str | None = None,
                    mission_t_s: float | None = None) -> "WorldTransaction":
        """A new plan was accepted. Update the plan identity and commit one linked snapshot."""
        with self._lock:
            self._plan_id = str(plan_id)
            return self._commit_locked(provenance=provenance, mission=mission, site=site, body=body,
                                       mission_t_s=mission_t_s, uncertainty_m=0.0)

    def record_terrain(self, *, authority_sha: str, provenance: str, mission: str | None = None,
                       site: str | None = None, body: str | None = None,
                       mission_t_s: float | None = None) -> "WorldTransaction":
        """A physical/conserved terrain change was recorded. Update the conserved-authority identity
        and commit one linked snapshot (the plan + belief are carried forward)."""
        with self._lock:
            self._authority_sha = str(authority_sha)
            return self._commit_locked(provenance=provenance, mission=mission, site=site, body=body,
                                       mission_t_s=mission_t_s, uncertainty_m=0.0)

    def record_resync(self, *, provenance: str, site: str | None = None,
                      uncertainty_m: float = 0.0) -> "WorldTransaction":
        """A perception/operator resync advanced the observed twin. Commit one linked snapshot (the
        twin's new version/hash is read live; the other sources are carried forward)."""
        with self._lock:
            return self._commit_locked(provenance=provenance, mission=None, site=site, body=None,
                                       mission_t_s=None, uncertainty_m=uncertainty_m)

    def record_belief(self, *, belief: "BeliefState | dict", provenance: str,
                      mission_t_s: float | None = None) -> "WorldTransaction":
        """The autonomy belief was updated. Snapshot it and commit one linked snapshot."""
        with self._lock:
            self._belief = E._belief_snapshot(belief)
            return self._commit_locked(provenance=provenance, mission=None, site=None, body=None,
                                       mission_t_s=mission_t_s, uncertainty_m=0.0)

    def record_execution_event(self, *, provenance: str, authority_sha: str | None = None,
                               belief: "BeliefState | dict | None" = None,
                               mission: str | None = None, site: str | None = None,
                               body: str | None = None, mission_t_s: float | None = None,
                               uncertainty_m: float = 0.0) -> "WorldTransaction":
        """A SIM/live execution event (leg complete, terrain mutation, safing). Optionally updates the
        conserved-authority identity and/or belief, then commits one linked snapshot. The execute path
        (a later step) drives this per leg."""
        with self._lock:
            if authority_sha is not None:
                self._authority_sha = str(authority_sha)
            if belief is not None:
                self._belief = E._belief_snapshot(belief)
            return self._commit_locked(provenance=provenance, mission=mission, site=site, body=body,
                                       mission_t_s=mission_t_s, uncertainty_m=uncertainty_m)

    # ---- reads ----------------------------------------------------------------------------------
    def latest(self) -> "WorldTransaction":
        """The single most recent consistent linked world-state record. Raises if none committed."""
        return self._log.latest()

    def transaction_count(self) -> int:
        return len(self._log.transactions)

    def recent(self, limit: int = 50) -> list[dict]:
        """The most recent linked transactions, oldest-first within the window, as plain dicts -- the
        world/execution timeline the cockpit Report pane renders. ``limit`` bounds the window; 0 -> []."""
        n = max(0, int(limit))
        txns = self._log.transactions[-n:] if n else []
        return [{"seq": t.seq, "provenance": t.provenance, "world_sha": t.world_sha,
                 "twin_version": t.twin_version, "plan_id": t.plan_id,
                 "authority_sha": t.authority_sha, "mission": t.mission,
                 "mission_t_s": t.mission_t_s} for t in txns]

    def verify_chain(self) -> bool:
        return self._log.verify_chain()


def commit_sim_run(wss: WorldStateService, run: dict, *, mission: str, site: str, body: str,
                   plan_id: str, vehicle_id: str = "ipex") -> int:
    """Step 3 (gap W1): commit a SIM run as world transactions through the WorldStateService -- the
    released plan, then one transaction per ExecutionEvent (a leg event per executed leg + a terminal
    completed/safed event). All SIM-labeled. Returns the number of transactions committed. The reusable
    seam: the live ROS/pit path (step 4) builds the same event list and commits it the same way."""
    from lode.sim_execution import execution_events
    wss.record_plan(plan_id=str(plan_id), provenance=f"SIM run: released plan {plan_id}",
                    mission=str(mission), site=str(site), body=str(body))
    n = 1
    for ev in execution_events(run, vehicle_id=vehicle_id):
        wss.record_execution_event(provenance=f"SIM {ev.kind}: {ev.detail} [{ev.outcome}]",
                                   mission=str(mission), site=str(site), body=str(body),
                                   mission_t_s=ev.t_s)
        n += 1
    return n


# ---- [REQ:EG-09] per-site terrain lock (relocated from routers.twin to shared-core world_state) ------
# The load->apply->save read-modify-write of a site's durable Terrain Memory is atomic per site. This lock
# lives in world-core so BOTH the twin (world-service) router and the executive (execution-service) node
# take the SAME lock -- executive already imports world_state, so it imports this from here instead of
# reaching across into routers.twin (the execution->world router back-edge EG-09 forbids). A meta-lock
# guards the registry dict; different sites proceed in parallel.
_TERRAIN_LOCKS: dict = {}
_TERRAIN_LOCKS_GUARD = threading.Lock()


def _terrain_lock(site: str) -> threading.Lock:
    # #282: key on the SANITIZED site (the same normalization save_site/load_site use for the .npz path), so
    # two requests whose site spellings collapse to the same file (e.g. "haworth" vs "haworth ") take the
    # SAME lock -- keying on the raw param re-opened the #278 lost-mission RMW race for such spellings.
    key = TM.safe_site(site)
    with _TERRAIN_LOCKS_GUARD:
        return _TERRAIN_LOCKS.setdefault(key, threading.Lock())
