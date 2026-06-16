"""Shared cross-cutting services for the cockpit server (ARCH-3).

Extracted from server.py so the per-concern routers can use them without importing the app module:
the append-only audit ledger and the process-wide request-metrics counters (the HTTP middleware
records every request here; the /metrics + /healthz routes read a snapshot).
"""
from __future__ import annotations

import contextvars
import hashlib
import json as _json
import logging
import os
import secrets
import threading
import time
from typing import Any

log = logging.getLogger("stewie.server")

# ---- FS-19: observability ledger plumbing -------------------------------------------------------
# A request-scoped correlation id so every semantic event logged INSIDE one request shares an id (you
# can pull the whole story of one operator action from the ledger). The HTTP middleware sets it per
# request; log_event auto-attaches it. ContextVars are per-task, so concurrent requests never collide.
_CORRELATION: contextvars.ContextVar[str | None] = contextvars.ContextVar("stewie_correlation_id", default=None)
# Field names whose VALUES must never reach the ledger (audit FS-19: no secrets/tokens/passwords/keys).
_REDACT_KEYS = frozenset({
    "password", "passwd", "pass", "token", "api_key", "apikey", "key", "secret",
    "authorization", "auth", "csrf", "private_key", "privatekey", "cookie", "session",
})


def new_correlation_id() -> str:
    """A fresh, unguessable correlation id for one request/decision chain."""
    return secrets.token_hex(8)


def set_correlation_id(cid: str | None) -> None:
    _CORRELATION.set(cid)


def get_correlation_id() -> str | None:
    return _CORRELATION.get()


def redact(obj: Any) -> Any:
    """Recursively mask any value held under a secret-like key, so a caller can never leak a credential
    into the audit ledger even by accident. Non-secret fields pass through unchanged."""
    if isinstance(obj, dict):
        return {k: ("[redacted]" if str(k).lower() in _REDACT_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj]
    return obj


def hash_payload(data: Any) -> str:
    """A short, stable content fingerprint (sha256 hex, truncated) of a request/response payload, so the
    ledger can record WHAT flowed without storing the contents themselves. Order-insensitive for dicts."""
    try:
        canon = _json.dumps(data, sort_keys=True, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        canon = repr(data)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]

# ---- the audit ledger (S-10): locked durable append + rotation + VISIBLE failure ----------------
_AUDIT_LOCK = threading.Lock()
_AUDIT_HEALTH: dict[str, Any] = {"degraded": False, "failures": 0, "last_error": None}
_AUDIT_HEALTH_LOCK = threading.Lock()
_AUDIT_DEFAULT_MAX_BYTES = 16 * 1024 * 1024     # rotate the live ledger past 16 MiB


def _events_path() -> str:
    from stewie.specs import config as CFG
    return os.path.join(CFG.data_dir(), "events.jsonl")


def _audit_max_bytes() -> int:
    try:
        return int(os.environ.get("STEWIE_AUDIT_MAX_BYTES", _AUDIT_DEFAULT_MAX_BYTES))
    except ValueError:
        return _AUDIT_DEFAULT_MAX_BYTES


def _rotate_if_needed(path: str) -> None:
    """Roll events.jsonl -> events.jsonl.<ts> once it exceeds the size cap (called under the lock)."""
    try:
        if os.path.exists(path) and os.path.getsize(path) >= _audit_max_bytes():
            os.replace(path, f"{path}.{int(time.time() * 1000)}")
    except OSError as e:                              # rotation failure is itself a degraded condition
        log.error("S-10: audit ledger rotation failed for %r: %r", path, e)
        raise


def _audit_append_raw(line: str) -> None:
    """The actual durable append: rotate-if-needed, append, flush + fsync so a crash cannot lose the
    record. Separated so tests can inject a failure. Raises on any I/O error (caller records degraded)."""
    path = _events_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _rotate_if_needed(path)
    with open(path, "a") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _record_audit_failure(err: Exception) -> None:
    with _AUDIT_HEALTH_LOCK:
        _AUDIT_HEALTH["degraded"] = True
        _AUDIT_HEALTH["failures"] += 1
        _AUDIT_HEALTH["last_error"] = repr(err)
    # S-10: a lost security event must be VISIBLE, not swallowed -- log at CRITICAL.
    log.critical("S-10 ALERT: audit ledger write FAILED (security events are not being recorded): %r", err)


def audit_health() -> dict:
    """The audit ledger's health for /healthz (S-10): degraded flag + cumulative failure count."""
    with _AUDIT_HEALTH_LOCK:
        return dict(_AUDIT_HEALTH)


def reset_audit_health() -> None:
    with _AUDIT_HEALTH_LOCK:
        _AUDIT_HEALTH.update({"degraded": False, "failures": 0, "last_error": None})


# SEC-02: the session-revocation store's health. A read error on revoked_jti.json makes verify_token
# FAIL CLOSED (deny the token); this surfaces that degradation so it is observable in /healthz, not silent.
_REVOCATION_HEALTH: dict[str, Any] = {"degraded": False, "failures": 0, "last_error": None}
_REVOCATION_HEALTH_LOCK = threading.Lock()


def record_revocation_failure(err: Exception) -> None:
    """SEC-02: the revocation store could not be read, so the auth layer is denying tokens (fail closed).
    Make it VISIBLE -- a degraded health flag, a CRITICAL log line, and a durable audit event."""
    with _REVOCATION_HEALTH_LOCK:
        _REVOCATION_HEALTH["degraded"] = True
        _REVOCATION_HEALTH["failures"] += 1
        _REVOCATION_HEALTH["last_error"] = repr(err)
    log.critical("SEC-02 ALERT: session revocation store UNREADABLE -- denying tokens (fail closed): %r", err)
    try:
        log_event("system", "revocation.read_failed", repr(err))
    except Exception:   # noqa: BLE001 -- health recording must never raise into the auth path
        pass


def revocation_health() -> dict:
    with _REVOCATION_HEALTH_LOCK:
        return dict(_REVOCATION_HEALTH)


def reset_revocation_health() -> None:
    with _REVOCATION_HEALTH_LOCK:
        _REVOCATION_HEALTH.update({"degraded": False, "failures": 0, "last_error": None})


def log_event(actor: str, action: str, target: str = "", **fields: Any) -> None:
    """Append a durable, ordered audit line under data_dir (S-10). Serialized on a process lock so
    concurrent events cannot interleave; fsync'd so a crash cannot lose it; rotated past the size cap.
    A write failure is recorded as a VISIBLE degraded state (audit_health) and logged at CRITICAL --
    never silently swallowed. Still never raises into the request path.

    FS-19: the record carries the active request correlation id (unless a caller overrides it) plus any
    structured ``**fields`` (status, latency_ms, error_code, mission/site/body/time, input/output hashes).
    Every field value is redacted through ``redact`` first, so a secret/token/password can never land in
    the ledger even if a caller passes one by mistake."""
    rec: dict[str, Any] = {"ts": round(time.time(), 3), "actor": actor, "action": action, "target": target}
    cid = fields.pop("correlation_id", None) or get_correlation_id()
    if cid is not None:
        rec["correlation_id"] = cid
    if fields:
        rec.update(redact(fields))
    line = _json.dumps(rec) + "\n"
    try:
        with _AUDIT_LOCK:
            _audit_append_raw(line)
    except OSError as e:
        _record_audit_failure(e)


# matplotlib/pyplot is process-global + thread-unsafe; every report-rendering route serializes on this
# ONE lock (shared by the plan + perception routers -- it must be a single process-wide instance).
report_lock = threading.Lock()


# ---- request metrics (RC-04) -- the middleware records every request; /metrics reads a snapshot ----
_START = time.monotonic()
_METRICS: dict = {"requests_total": 0, "by_status": {}, "by_route": {}}
_METRICS_LOCK = threading.Lock()


def record_request(status_key: str, route_key: str) -> None:
    """Atomic per-request counter update (total + by-status + by-route-template). Called from the
    server's HTTP middleware on every response. The route key is the MATCHED template (finite), never
    the attacker-controlled raw path -- so by_route cannot grow unbounded."""
    with _METRICS_LOCK:
        _METRICS["requests_total"] += 1
        _METRICS["by_status"][status_key] = _METRICS["by_status"].get(status_key, 0) + 1
        _METRICS["by_route"][route_key] = _METRICS["by_route"].get(route_key, 0) + 1


def metrics_snapshot() -> dict:
    """A consistent copy of the counters, taken under the lock so a concurrent middleware update
    cannot mutate the nested dicts mid-serialization."""
    with _METRICS_LOCK:
        return {"requests_total": _METRICS["requests_total"],
                "by_status": dict(_METRICS["by_status"]),
                "by_route": dict(_METRICS["by_route"])}


def uptime_s() -> float:
    """Seconds since the server process started (1 decimal)."""
    return round(time.monotonic() - _START, 1)


def prune_reports(ttl_s: float | None = None) -> int:
    """Delete report files older than the TTL (default $STEWIE_REPORTS_TTL_S or 86400 s). Returns the
    count removed. The reports dir is resolved at call time (PO-02), so a relocated data_dir works."""
    from stewie.specs import config as CFG
    reports = CFG.reports_dir()
    ttl = float(ttl_s if ttl_s is not None else os.environ.get("STEWIE_REPORTS_TTL_S", 86400))
    if ttl <= 0 or not os.path.isdir(reports):
        return 0
    now, removed = time.time(), 0
    for n in os.listdir(reports):
        p = os.path.join(reports, n)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > ttl:
                os.remove(p)
                removed += 1
        except OSError:
            pass
    return removed
