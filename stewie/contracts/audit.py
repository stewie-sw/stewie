"""[REQ:EG-07] The immutable audit trail (PRD §7).

Every critical action (a live command, a plan merge, a config change, ...) records the nine fields
who/what/when/where/mode/reason/before-state/after-state/evidence, APPEND-ONLY and HASH-CHAINED: each record
carries the hash of its predecessor, so mutating any earlier field breaks the chain and `verify_chain` returns
False (tamper is detectable). This is the tamper-evident sibling of the TwinStore journal; it stores authority
DECISIONS (who did what, why) rather than terrain revisions.

The record's `timestamp` is caller-provided (the action's real time, from its own context) so the log is
deterministic + does not smuggle wall-clock nondeterminism into the hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass

import fcntl

#: the chain root: the `prev_hash` of the first record (64 hex zeros, i.e. sha256's width).
GENESIS_HASH = "0" * 64

_FIELDS = ("actor", "action", "timestamp", "location", "mode", "reason",
           "before_state", "after_state", "evidence")
_ANCHOR_SCHEMA = "stewie.audit-head/v1"


class AuditIntegrityError(RuntimeError):
    """The durable audit journal is not safe to extend.

    Appending to a damaged chain would make the damage harder to recover and could concatenate a new
    record onto a torn JSON line. Authority actions therefore fail closed until an operator repairs or
    quarantines the journal.
    """


@dataclass(frozen=True)
class AuditRecord:
    """One append-only audit entry: the nine recorded fields + the chain links. Frozen -- a record is never
    edited in place; tampering means building a different record, which the chain then rejects."""
    actor: str            # who   -- the acting principal (role:id)
    action: str           # what  -- the critical action performed
    timestamp: str        # when  -- caller-provided, the action's real time
    location: str         # where -- resource / namespace / site the action touched
    mode: str             # the EnvironmentMode the action ran in (EG-01)
    reason: str           # why   -- the recorded justification
    before_state: str     # state before the action (hash or summary)
    after_state: str      # state after the action
    evidence: str         # evidence pointer (artifact sha / bundle id / signature)
    prev_hash: str        # the predecessor's record_hash (GENESIS_HASH for the first)
    record_hash: str      # sha256 over prev_hash + the nine fields


def _digest(fields: dict, prev_hash: str) -> str:
    """The tamper-evident record hash: sha256 over the previous hash + the nine fields (order-independent)."""
    payload = json.dumps({"prev_hash": prev_hash, **{k: fields[k] for k in _FIELDS}}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def verify_chain(records) -> bool:
    """True iff `records` is an intact hash-chain: every record links to its predecessor AND its stored
    record_hash still equals the recomputed digest of its fields. Any mutated field -> False."""
    prev = GENESIS_HASH
    for r in records:
        if r.prev_hash != prev:
            return False
        fields = {k: getattr(r, k) for k in _FIELDS}
        if _digest(fields, prev) != r.record_hash:
            return False
        prev = r.record_hash
    return True


class AuditLog:
    """An append-only, hash-chained sequence of AuditRecords. There is NO delete/update API -- the log only
    grows; integrity is checked with `verify` / `verify_chain`.

    SR-04 (2026-07-28 review): the chain is DURABLE when constructed with a ``journal_path``. It was
    previously a process-global list with no persistence, so a redeploy -- the routine operation in
    deploy/DEPLOY.md -- destroyed every director release, SIM run and reconciliation record, after which
    the audit endpoint answered ``{"verified": true, "count": 0}``. An operator could not tell "no
    privileged action was ever taken" from "the authority record was destroyed", and the EV-01 evidence
    bundle embedded that same positive verdict as proof.

    Each record is appended as one JSON line, flushed and ``fsync``-ed BEFORE it is admitted to the
    in-memory chain, mirroring the durable S-10 event ledger (`services._audit_append_raw`). A record
    that could not be written durably is NOT reported as recorded -- the append raises, so a caller can
    refuse the action rather than proceed on an unrecorded authority decision.
    """

    def __init__(self, journal_path: str | None = None) -> None:
        self._records: list[AuditRecord] = []
        self._journal_path = journal_path
        self._lock = threading.Lock()
        #: set when the persisted journal could not be read back intact (torn/garbled line). A load
        #: failure is CORRUPTION of the authority record, so integrity() reports False, never None.
        self._load_error: str | None = None
        if journal_path:
            # A never-created log has no shared state to protect yet; keep construction side-effect free
            # so an unwritable destination fails at append, not merely at object creation.
            if os.path.exists(journal_path) or os.path.exists(self._anchor_path()):
                with self._journal_lock():
                    self._load()
                    self._ensure_anchor()
            else:
                self._load()

    def _anchor_path(self) -> str:
        if self._journal_path is None:
            raise RuntimeError("cannot resolve an audit anchor without a journal_path")
        return self._journal_path + ".head.json"

    def _read_anchor(self) -> dict | None:
        path = self._anchor_path()
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            anchor = json.load(f)
        if not isinstance(anchor, dict) or anchor.get("schema") != _ANCHOR_SCHEMA:
            raise ValueError("invalid audit-head schema")
        count = anchor.get("count")
        head = anchor.get("record_hash")
        if not isinstance(count, int) or count < 0 or not isinstance(head, str):
            raise ValueError("invalid audit-head fields")
        if len(head) != 64:
            raise ValueError("invalid audit-head record_hash")
        return anchor

    @staticmethod
    def _anchor_error(records: list[AuditRecord], anchor: dict | None) -> str | None:
        if anchor is None:
            return None
        count = int(anchor["count"])
        head = str(anchor["record_hash"])
        if count > len(records):
            return f"audit journal regressed from anchored count {count} to {len(records)}"
        if count == 0:
            return None if head == GENESIS_HASH else "empty audit anchor has a non-genesis head"
        if records[count - 1].record_hash != head:
            return "audit journal does not contain its anchored head"
        return None

    def _load(self) -> None:
        """Reconstruct the chain from its journal. A malformed line stops the load and marks the log
        corrupt -- a torn tail is never silently dropped, because dropping it would rewrite history."""
        if self._journal_path is None:
            raise RuntimeError("cannot load an audit journal without a journal_path")
        self._load_error = None
        recs: list[AuditRecord] = []
        try:
            anchor = self._read_anchor()
            if os.path.exists(self._journal_path):
                with open(self._journal_path, encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        recs.append(AuditRecord(**json.loads(ln)))
            anchor_error = self._anchor_error(recs, anchor)
            if anchor_error:
                self._load_error = anchor_error
        except (OSError, ValueError, TypeError) as e:   # ValueError covers JSONDecodeError
            self._load_error = f"unreadable audit journal: {e!r}"
        self._records = recs

    @contextmanager
    def _journal_lock(self):
        """Serialize appenders across workers/processes, not only across threads in this object.

        A per-instance ``threading.Lock`` cannot protect two ``AuditLog(path)`` instances: both can load
        the same tail and append sibling records. The sidecar flock is held while the journal is reloaded,
        verified, and extended, giving every process a fresh authoritative tail.
        """
        if self._journal_path is None:
            raise RuntimeError("cannot lock an audit journal without a journal_path")
        lock_path = self._journal_path + ".lock"
        d = os.path.dirname(lock_path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _persist(self, rec: AuditRecord) -> None:
        """Durable append: write + flush + fsync, so a crash cannot lose an authority record. Raises on
        any I/O error (the caller must not claim the action was recorded)."""
        if self._journal_path is None:
            raise RuntimeError("cannot persist an audit record without a journal_path")
        d = os.path.dirname(self._journal_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(self._journal_path, "a") as f:
            f.write(json.dumps(asdict(rec), sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        # Persist a newly-created journal's directory entry as well as its contents.
        dir_fd = os.open(d or ".", os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    def _persist_anchor(self, count: int, record_hash: str) -> None:
        """Atomically persist an external high-water mark so journal deletion/regression is detectable."""
        path = self._anchor_path()
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".audit-head-", dir=d or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {"schema": _ANCHOR_SCHEMA, "count": count, "record_hash": record_hash},
                    f, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            dir_fd = os.open(d or ".", os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _ensure_anchor(self) -> None:
        """Bootstrap/advance the sidecar only from an already-valid journal while holding its OS lock."""
        if self._load_error or not verify_chain(self._records):
            return
        anchor = self._read_anchor()
        anchored_count = int(anchor["count"]) if anchor is not None else 0
        if self._records and anchored_count < len(self._records):
            self._persist_anchor(len(self._records), self._records[-1].record_hash)

    def _refresh(self) -> None:
        """Refresh read-side state so another worker's append or external corruption is visible."""
        if self._journal_path is None:
            return
        with self._lock:
            with self._journal_lock():
                self._load()
                self._ensure_anchor()

    def append(self, *, actor: str, action: str, timestamp: str, location: str, mode: str, reason: str,
               before_state: str, after_state: str, evidence: str) -> AuditRecord:
        """Record one critical action. Chains onto the current tail (or GENESIS for the first). Returns the
        new record. `mode` is normalized to its string value so an EnvironmentMode or a raw string both work.

        Serialized on a per-log lock so two concurrent appends cannot both chain onto the same tail and
        fork the chain. The record is persisted (when journalled) BEFORE it joins the in-memory chain.
        """
        fields = {
            "actor": actor, "action": action, "timestamp": timestamp, "location": location,
            "mode": getattr(mode, "value", mode), "reason": reason,
            "before_state": before_state, "after_state": after_state, "evidence": evidence,
        }
        with self._lock:
            if self._journal_path:
                with self._journal_lock():
                    # Another worker may have appended since this object was constructed. Reload under the
                    # process lock, then refuse a malformed or hash-invalid history before touching its bytes.
                    self._load()
                    if self._load_error or not verify_chain(self._records):
                        detail = self._load_error or "audit journal hash chain is invalid"
                        raise AuditIntegrityError(f"refusing to append to corrupt audit journal: {detail}")
                    self._ensure_anchor()
                    prev = self._records[-1].record_hash if self._records else GENESIS_HASH
                    rec = AuditRecord(**fields, prev_hash=prev, record_hash=_digest(fields, prev))
                    self._persist(rec)
                    self._persist_anchor(len(self._records) + 1, rec.record_hash)
                    self._records.append(rec)
                    return rec
            if not verify_chain(self._records):
                raise AuditIntegrityError("refusing to append to corrupt in-memory audit chain")
            prev = self._records[-1].record_hash if self._records else GENESIS_HASH
            rec = AuditRecord(**fields, prev_hash=prev, record_hash=_digest(fields, prev))
            self._records.append(rec)
        return rec

    def records(self) -> tuple[AuditRecord, ...]:
        """An immutable snapshot of the chain in order."""
        self._refresh()
        return tuple(self._records)

    def verify(self) -> bool:
        """True iff the whole chain is intact (no record has been tampered). NOTE: vacuously True on an
        empty chain -- call `integrity()` for the operator-facing flag that distinguishes that case."""
        self._refresh()
        return not self._load_error and verify_chain(self._records)

    def integrity(self) -> bool | None:
        """The operator-facing integrity flag, three-valued so an EMPTY chain cannot masquerade as a
        verified one (SR-04):

        * ``None``  -- nothing recorded, so there is nothing to attest. Reporting True here is what let a
          wiped chain read as clean.
        * ``False`` -- the journal is unreadable, or a record's stored hash no longer matches (tamper).
        * ``True``  -- a non-empty chain that verifies end to end.
        """
        self._refresh()
        if self._load_error:
            return False
        if not self._records:
            return None
        return verify_chain(self._records)
