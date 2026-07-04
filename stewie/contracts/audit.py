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
from dataclasses import dataclass

#: the chain root: the `prev_hash` of the first record (64 hex zeros, i.e. sha256's width).
GENESIS_HASH = "0" * 64

_FIELDS = ("actor", "action", "timestamp", "location", "mode", "reason",
           "before_state", "after_state", "evidence")


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
    grows; integrity is checked with `verify` / `verify_chain`."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, *, actor: str, action: str, timestamp: str, location: str, mode: str, reason: str,
               before_state: str, after_state: str, evidence: str) -> AuditRecord:
        """Record one critical action. Chains onto the current tail (or GENESIS for the first). Returns the
        new record. `mode` is normalized to its string value so an EnvironmentMode or a raw string both work."""
        fields = {
            "actor": actor, "action": action, "timestamp": timestamp, "location": location,
            "mode": getattr(mode, "value", mode), "reason": reason,
            "before_state": before_state, "after_state": after_state, "evidence": evidence,
        }
        prev = self._records[-1].record_hash if self._records else GENESIS_HASH
        rec = AuditRecord(**fields, prev_hash=prev, record_hash=_digest(fields, prev))
        self._records.append(rec)
        return rec

    def records(self) -> tuple[AuditRecord, ...]:
        """An immutable snapshot of the chain in order."""
        return tuple(self._records)

    def verify(self) -> bool:
        """True iff the whole chain is intact (no record has been tampered)."""
        return verify_chain(self._records)
