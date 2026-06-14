"""Shared cross-cutting services for the cockpit server (ARCH-3).

Extracted from server.py so the per-concern routers can use them without importing the app module:
the append-only audit ledger and the process-wide request-metrics counters (the HTTP middleware
records every request here; the /metrics + /healthz routes read a snapshot).
"""
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("stewie.server")

# ---- the audit ledger (S-10): locked durable append + rotation + VISIBLE failure ----------------
_AUDIT_LOCK = threading.Lock()
_AUDIT_HEALTH = {"degraded": False, "failures": 0, "last_error": None}
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


def log_event(actor: str, action: str, target: str = "") -> None:
    """Append a durable, ordered audit line under data_dir (S-10). Serialized on a process lock so
    concurrent events cannot interleave; fsync'd so a crash cannot lose it; rotated past the size cap.
    A write failure is recorded as a VISIBLE degraded state (audit_health) and logged at CRITICAL --
    never silently swallowed. Still never raises into the request path."""
    import json as _json
    line = _json.dumps({"ts": round(time.time(), 3), "actor": actor,
                        "action": action, "target": target}) + "\n"
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
