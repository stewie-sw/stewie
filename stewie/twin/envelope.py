"""DT-01 (PRD §27.2.D + §6.2 W-1/W-4): the versioned world-state TRANSACTION ENVELOPE.

The operational world model is four state sources read INDEPENDENTLY today: the conserved physics
authority (``ColumnState`` -- the mass-exact terrain transition), the OBSERVED twin (``TwinStore`` --
the append-only perception/ops map), the planner's latest ``PlanResult``, and the autonomy belief
(``BeliefState``). Four independent reads can disagree: the twin advances while a query is mid-flight,
or a stale plan is paired with a fresh belief. DT-01 binds them into ONE record so a single query
returns a CONSISTENT linked world-state, not four reads that may have skewed.

A ``WorldTransaction`` is that record: it carries each source's identity (a content sha for the
conserved authority; the twin's monotonic version + latest chain hash; the plan id; a belief
snapshot), the mission/site/body/time/provenance/uncertainty stamp DT-01 requires, a combined
``world_sha`` over all four (so mutating ANY source moves the sha), and a ``chain_hash`` linking it to
the prior transaction. The ``TransactionLog`` is append-only + hash-chained (tamper-evident) and --
when given a ``journal_path`` -- DURABLE: each commit appends fsync-on-event (W-1) under
``data_dir/twin/``, and ``from_journal`` cold-rebuilds the log from the journal ALONE and reproduces
the latest ``world_sha`` bit-exact (W-4). A crash mid-fsync tears only the final line; cold restore
recovers every complete prior transaction and surfaces (does not silently drop) interior corruption.

HONESTY (PRD): this is the transactional SPINE + durability for the world model -- one consistent
linked snapshot with a recoverable, tamper-evident history. It is NOT a production-complete digital
twin: it links and durably records the existing state sources; it does not by itself add new
perception, autonomy, or physics fidelity.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:                                            # avoid import-time cost / cycles
    from stewie.contracts import BeliefState, PlanResult
    from stewie.physics.column_state import ColumnState
    from stewie.twin.versioned import TwinStore


def authority_sha(authority: "ColumnState") -> str:
    """A deterministic content sha256 over the conserved authority's full state -- the mass-exact
    rasters that ARE the physics truth (mass_areal / density / disturbance / state_label) plus the
    datum, grid geometry, and the drum inventory. Two ColumnStates with identical conserved content
    hash identically; any conserved mutation (a cut, a dump, a relax) changes the sha. Hashed in
    float64 native bytes (the authority's accumulation precision), so the digest is byte-exact across
    a save/load round-trip of the same state."""
    h = hashlib.sha256()
    h.update(np.asarray(authority.mass_areal, dtype=np.float64).tobytes())
    h.update(np.asarray(authority.density, dtype=np.float64).tobytes())
    h.update(np.asarray(authority.disturbance, dtype=np.float64).tobytes())
    h.update(np.asarray(authority.state_label, dtype=np.uint8).tobytes())
    datum = authority.datum
    h.update(np.asarray(datum, dtype=np.float64).tobytes() if isinstance(datum, np.ndarray)
             else np.array([datum], dtype=np.float64).tobytes())
    h.update(np.array([authority.width, authority.height], dtype=np.int64).tobytes())
    h.update(np.array([authority.cell_m, float(authority.drum_inventory)],
                      dtype=np.float64).tobytes())
    return h.hexdigest()


@dataclass
class WorldTransaction:
    """One linked, provenance-stamped world-state record (DT-01).

    The four linked source identities: ``authority_sha`` (conserved physics), ``twin_version`` +
    ``twin_hash`` (observed twin), ``plan_id`` (latest plan), ``belief`` (autonomy belief snapshot).
    The stamp: ``mission`` / ``site`` / ``body`` / ``mission_t_s`` / ``provenance`` /
    ``uncertainty_m``. Integrity: ``world_sha`` over all four sources + the stamp; ``seq`` (monotonic),
    ``prev_hash`` (the predecessor's chain hash), ``chain_hash`` (this record's tamper-evident hash)."""
    seq: int
    authority_sha: str
    twin_version: int
    twin_hash: str
    plan_id: str
    belief: dict
    mission: str
    site: str
    body: str
    mission_t_s: float
    provenance: str
    uncertainty_m: float
    world_sha: str
    prev_hash: str
    chain_hash: str

    def linked_body(self) -> dict:
        """The content this record commits to -- everything EXCEPT its own chain_hash (which is the
        digest OF this body). Stable key order via json sort_keys at hashing time."""
        b = asdict(self)
        b.pop("chain_hash")
        return b


def _world_sha(authority_sha_: str, twin_version: int, twin_hash: str, plan_id: str, belief: dict,
               mission: str, site: str, body: str, mission_t_s: float, provenance: str,
               uncertainty_m: float) -> str:
    """The combined content hash over all four linked sources + the stamp. A function of EVERY source
    so mutating any one moves the sha (the consistency guarantee: this is one linked snapshot)."""
    h = hashlib.sha256()
    payload = {
        "authority_sha": authority_sha_,
        "twin_version": twin_version,
        "twin_hash": twin_hash,
        "plan_id": plan_id,
        "belief": belief,
        "mission": mission,
        "site": site,
        "body": body,
        "mission_t_s": mission_t_s,
        "provenance": provenance,
        "uncertainty_m": uncertainty_m,
    }
    h.update(json.dumps(payload, sort_keys=True).encode())
    return h.hexdigest()


def _belief_snapshot(belief: "BeliefState | dict") -> dict:
    """A plain-dict snapshot of the autonomy belief, deterministic-key. Accepts a pydantic
    ``BeliefState`` (the contract) or a plain dict (already-snapshotted, e.g. on replay)."""
    if hasattr(belief, "model_dump"):
        return dict(belief.model_dump())          # type: ignore[union-attr]
    return dict(belief)


@dataclass
class TransactionLog:
    """Append-only, hash-chained log of ``WorldTransaction`` records (DT-01). With a ``journal_path``
    it is DURABLE: each commit appends fsync-on-event (W-1); ``from_journal`` cold-restores (W-4)."""
    journal_path: str | None = None             # W-1: per-edit durable append; None = volatile
    transactions: list[WorldTransaction] = field(default_factory=list)

    # ---- commit ---------------------------------------------------------------------------------
    def commit(self, *, authority: "ColumnState", twin: "TwinStore", plan: "PlanResult",
               belief: "BeliefState | dict", mission: str, site: str, body: str,
               mission_t_s: float, provenance: str, uncertainty_m: float = 0.0) -> WorldTransaction:
        """Link the four CURRENT world-state source OBJECTS into one record, hash-chain it, durably
        journal it (if journalling), and append it. Returns the committed transaction. Extracts each
        source's identity then delegates to ``commit_snapshot`` (the shared commit path)."""
        return self.commit_snapshot(
            authority_sha=authority_sha(authority),
            twin_version=int(twin.version),
            twin_hash=twin.events[-1]["hash"] if twin.events else "genesis",
            plan_id=str(plan.plan_id), belief=belief, mission=mission, site=site, body=body,
            mission_t_s=mission_t_s, provenance=provenance, uncertainty_m=uncertainty_m)

    def commit_snapshot(self, *, authority_sha: str, twin_version: int, twin_hash: str, plan_id: str,
                        belief: "BeliefState | dict", mission: str, site: str, body: str,
                        mission_t_s: float, provenance: str,
                        uncertainty_m: float = 0.0) -> WorldTransaction:
        """Commit a transaction from already-extracted source IDENTITIES rather than live source
        OBJECTS. A route-level facade (``WorldStateService``) holds the latest-known identity of each
        source (the conserved-authority sha, the observed twin's version/hash, the plan id, the belief)
        but not a live ColumnState/PlanResult at a resync or terrain-record -- so it commits here.
        Same hash-chain, same durability, same mandatory provenance as ``commit``."""
        if not provenance or not str(provenance).strip():
            raise ValueError("every world transaction requires non-empty provenance")
        bel = _belief_snapshot(belief)
        return self._append(str(authority_sha), int(twin_version), str(twin_hash), str(plan_id), bel,
                            str(mission), str(site), str(body), float(mission_t_s), str(provenance),
                            float(uncertainty_m))

    def _chain_hash(self, body: dict, prev: str) -> str:
        h = hashlib.sha256()
        h.update(prev.encode())
        h.update(json.dumps(body, sort_keys=True).encode())
        return h.hexdigest()

    def _append(self, a_sha: str, t_ver: int, t_hash: str, plan_id: str, belief: dict,
                mission: str, site: str, body: str, mission_t_s: float, provenance: str,
                uncertainty_m: float, *, expected_chain: str | None = None) -> WorldTransaction:
        seq = len(self.transactions)
        prev = self.transactions[-1].chain_hash if self.transactions else "genesis"
        w_sha = _world_sha(a_sha, t_ver, t_hash, plan_id, belief, mission, site, body,
                           mission_t_s, provenance, uncertainty_m)
        txn = WorldTransaction(seq=seq, authority_sha=a_sha, twin_version=t_ver, twin_hash=t_hash,
                               plan_id=plan_id, belief=belief, mission=mission, site=site, body=body,
                               mission_t_s=mission_t_s, provenance=provenance,
                               uncertainty_m=uncertainty_m, world_sha=w_sha, prev_hash=prev,
                               chain_hash="")
        txn.chain_hash = self._chain_hash(txn.linked_body(), prev)
        # on REPLAY, verify the recomputed chain hash BEFORE any durable write or in-memory append --
        # a tampered journal raises with NO state change (atomic failure), never persisting a bad record.
        if expected_chain is not None and txn.chain_hash != expected_chain:
            raise ValueError("world transaction replay hash mismatch -- the journal was altered")
        # W-1 / H-20: durably append BEFORE committing the in-memory record, so a write/fsync failure
        # leaves memory == disk (never memory-ahead). Journal the FULL record (chain_hash included) so
        # cold restore recovers the exact bytes and re-verifies the chain.
        if self.journal_path:
            with open(self.journal_path, "a") as fh:
                fh.write(json.dumps(asdict(txn), sort_keys=True) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        self.transactions.append(txn)
        return txn

    # ---- queries --------------------------------------------------------------------------------
    def latest(self) -> WorldTransaction:
        """The single most recent consistent linked world-state record (DT-01's "one query returns a
        consistent linked world-state, not independent reads")."""
        if not self.transactions:
            raise ValueError("no world transaction has been committed")
        return self.transactions[-1]

    def verify_chain(self) -> bool:
        """Recompute every record's world_sha and chain_hash from its linked content; any mismatch or
        broken prev-link means the log was altered."""
        prev = "genesis"
        for txn in self.transactions:
            recomputed_world = _world_sha(
                txn.authority_sha, txn.twin_version, txn.twin_hash, txn.plan_id, txn.belief,
                txn.mission, txn.site, txn.body, txn.mission_t_s, txn.provenance, txn.uncertainty_m)
            if recomputed_world != txn.world_sha:
                return False
            if txn.prev_hash != prev:
                return False
            if self._chain_hash(txn.linked_body(), prev) != txn.chain_hash:
                return False
            prev = txn.chain_hash
        return True

    # ---- W-4 cold restore -----------------------------------------------------------------------
    @classmethod
    def from_journal(cls, journal_path: str) -> "TransactionLog":
        """W-4 cold restore: rebuild the log from the durable journal ALONE. Each line replays through
        ``_append`` (chain-verified, so a tampered record raises). A crash mid-fsync tears only the
        FINAL line -> recover every complete prior record; an interior torn line is real history loss
        -> surface it (refuse a partial silent restore)."""
        log = cls(journal_path=None)                         # replay WITHOUT re-journalling
        if os.path.exists(journal_path):
            lines = [ln for ln in open(journal_path).read().splitlines() if ln.strip()]
            for i, line in enumerate(lines):
                try:
                    rec: dict[str, Any] = json.loads(line)
                except json.JSONDecodeError:
                    if i == len(lines) - 1:                  # torn tail: stop, keep prior records
                        break
                    raise ValueError(
                        f"world journal corrupt at interior line {i} (not the tail) "
                        "-- refusing a partial silent restore")
                log._append(rec["authority_sha"], int(rec["twin_version"]), rec["twin_hash"],
                            rec["plan_id"], rec["belief"], rec["mission"], rec["site"], rec["body"],
                            float(rec["mission_t_s"]), rec["provenance"],
                            float(rec.get("uncertainty_m", 0.0)),
                            expected_chain=rec["chain_hash"])
        log.journal_path = journal_path                      # future commits journal again
        return log
