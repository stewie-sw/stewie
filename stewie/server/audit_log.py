"""[REQ:EG-07] The PROCESS audit-log wiring -- the live surface of the EG-07 contract.

`stewie.contracts.audit` delivers a tamper-evident hash-chained AuditLog; this module makes ONE per running
backend worker (the deploy is single-worker) and records the executive's critical actions (a director plan
release, a SIM run) into it, stamping a real UTC timestamp. That turns the built-but-inert EG-07 audit trail
into an actual record of who/what/when/where/mode/reason/before/after/evidence for every authority action --
the noted [REQ:EG-07] integration follow-up, wired at the /executive command sites.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

from stewie.contracts.audit import AuditLog, AuditRecord

_AUDIT: AuditLog | None = None
_AUDIT_PATH: str | None = None
_AUDIT_LOCK = threading.Lock()


def journal_path() -> str:
    """SR-04: where the EG-07 chain is persisted, under the configured data_dir (resolved at CALL time,
    not import time, so a relocated data_dir -- the test fixtures, a redeployed container with a fresh
    mount -- is honoured)."""
    from stewie.specs import config as CFG
    return os.path.join(CFG.data_dir(), "audit", "executive_chain.jsonl")


def get_audit_log() -> AuditLog:
    """The process-wide EG-07 audit log (one per backend worker), DURABLE since SR-04.

    Built lazily and re-built if the resolved journal path changes, so the log always belongs to the
    active data_dir. Previously this was ``AuditLog()`` evaluated at import: purely in-memory, so a
    restart silently erased every recorded authority decision.
    """
    global _AUDIT, _AUDIT_PATH
    p = journal_path()
    if _AUDIT is not None and _AUDIT_PATH == p:
        return _AUDIT
    with _AUDIT_LOCK:
        if _AUDIT is None or _AUDIT_PATH != p:
            _AUDIT = AuditLog(journal_path=p)
            _AUDIT_PATH = p
        return _AUDIT


def record_action(actor: str, action: str, *, location: str, mode: str, reason: str,
                  before_state: str, after_state: str, evidence: str,
                  timestamp: str | None = None) -> AuditRecord:
    """Append one critical action to the process audit chain, stamping a real UTC timestamp if none is given.
    Returns the new (hash-chained) record."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    return get_audit_log().append(                       # SR-04: resolve the DURABLE log, not an import-time global
        actor=actor, action=action, timestamp=ts, location=location, mode=mode,
        reason=reason, before_state=before_state, after_state=after_state, evidence=evidence)
