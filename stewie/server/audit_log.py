"""[REQ:EG-07] The PROCESS audit-log wiring -- the live surface of the EG-07 contract.

`stewie.contracts.audit` delivers a tamper-evident hash-chained AuditLog; this module makes ONE per running
backend worker (the deploy is single-worker) and records the executive's critical actions (a director plan
release, a SIM run) into it, stamping a real UTC timestamp. That turns the built-but-inert EG-07 audit trail
into an actual record of who/what/when/where/mode/reason/before/after/evidence for every authority action --
the noted [REQ:EG-07] integration follow-up, wired at the /executive command sites.
"""
from __future__ import annotations

from datetime import datetime, timezone

from stewie.contracts.audit import AuditLog, AuditRecord

_AUDIT = AuditLog()


def get_audit_log() -> AuditLog:
    """The process-wide EG-07 audit log (one per backend worker)."""
    return _AUDIT


def record_action(actor: str, action: str, *, location: str, mode: str, reason: str,
                  before_state: str, after_state: str, evidence: str,
                  timestamp: str | None = None) -> AuditRecord:
    """Append one critical action to the process audit chain, stamping a real UTC timestamp if none is given.
    Returns the new (hash-chained) record."""
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    return _AUDIT.append(actor=actor, action=action, timestamp=ts, location=location, mode=mode,
                         reason=reason, before_state=before_state, after_state=after_state, evidence=evidence)
