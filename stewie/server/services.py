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
from collections import deque
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


# ---- FS-10: latency budgets ---------------------------------------------------------------------
# Per-route engineering budgets (ms). These are TARGETS, grounded in each route's nature (a synchronous
# matplotlib PDF render is seconds; analytic sun geometry is sub-100 ms), not measured data. The
# middleware records each request's real latency; latency_snapshot() reports p50/p95/max from a bounded
# recent-sample window and flags a route whose p95 is over budget. Operators read it in /metrics; the
# middleware also WARN-logs a real breach so a regression surfaces in the logs, not just the dashboard.
_LAT_WINDOW = 256                                    # bounded ring buffer per route -> no unbounded growth
_DEFAULT_BUDGET_MS = 1000.0
_LATENCY_BUDGETS_MS: dict[str, float] = {
    "/plan": 30000.0,            # synchronous PDF render -- seconds, not ms
    "/session/{sid}/scorecard": 30000.0,   # TR-01: re-sims candidate futures (forward_compare) to score makespan
    "/figure/{key}": 8000.0,     # figure render
    "/layers": 3000.0,           # globe-layer render
    "/world": 1500.0,            # DEM load + reproject
    "/structure": 1500.0,
    "/contracts/schema": 300.0,
    "/ephemeris": 200.0,         # analytic sun geometry -- fast
    "/sense": 200.0,
    "/healthz": 100.0,
    "/metrics": 100.0,
}
_LAT_SAMPLES: dict[str, "deque[float]"] = {}


def budget_for(route_key: str) -> float:
    """The latency budget (ms) for a matched route template, else the default."""
    return _LATENCY_BUDGETS_MS.get(route_key, _DEFAULT_BUDGET_MS)


def record_latency(route_key: str, ms: float) -> None:
    """Record one request's observed latency (ms) into the route's bounded recent-sample window."""
    with _METRICS_LOCK:
        buf = _LAT_SAMPLES.get(route_key)
        if buf is None:
            buf = deque(maxlen=_LAT_WINDOW)
            _LAT_SAMPLES[route_key] = buf
        buf.append(float(ms))


def _pct(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def latency_snapshot() -> dict:
    """Per-route latency summary from the recent-sample window: count, p50, p95, max, budget, and an
    over_budget flag (p95 over the route budget). A consistent copy taken under the metrics lock."""
    with _METRICS_LOCK:
        items = [(k, list(v)) for k, v in _LAT_SAMPLES.items()]
    out: dict[str, dict] = {}
    for route, samples in items:
        if not samples:
            continue
        s = sorted(samples)
        b = budget_for(route)
        p95 = _pct(s, 0.95)
        out[route] = {"count": len(s), "p50": round(_pct(s, 0.5), 1), "p95": round(p95, 1),
                      "max": round(s[-1], 1), "budget_ms": b, "over_budget": p95 > b}
    return out


# ---- FS-10: resource budgets beyond latency ------------------------------------------------------
# The latency block above covers ONE budget class (per-route wall-clock). FS-10 also names memory,
# CPU/GPU, bandwidth, tile/cache, and model-inference budgets across the map-render / planning /
# fleet-solve / navigation-estimation / cockpit-mobile subsystems. Each class DECLARES an engineering
# budget + unit + the subsystem it governs; a bounded ring buffer records REAL observed measurements
# (the same recorded-sample accounting as latency, not a synthetic distribution); resource_budget_snapshot()
# reports p95/max per class and flags a class whose p95 is over budget. Some sources are live on this host
# (process RSS, CPU time, response bytes -- recorded from the OS/middleware); GPU frame-time and
# model-inference latency have no live source here (no GPU traffic, no deployed model), so their budget is
# DECLARED and the accounting is exercised by recorded samples -- the class is defined, its live producer named.
_RES_WINDOW = 256


class _ResBudget:
    __slots__ = ("cls", "subsystem", "budget", "unit", "live_source")

    def __init__(self, cls: str, subsystem: str, budget: float, unit: str, live_source: str) -> None:
        self.cls = cls
        self.subsystem = subsystem
        self.budget = float(budget)
        self.unit = unit
        self.live_source = live_source


# class -> (subsystem it governs, declared budget, unit, where the live measurement comes from)
_RESOURCE_BUDGETS: dict[str, _ResBudget] = {
    "memory":          _ResBudget("memory", "navigation_estimation", 2048.0, "MB", "process RSS (resource.getrusage)"),
    "cpu":             _ResBudget("cpu", "fleet_solve", 60.0, "cpu_seconds", "process CPU time (resource.getrusage)"),
    "gpu":             _ResBudget("gpu", "map_render", 33.0, "ms_per_frame", "gated: needs a GPU render host (no live source here)"),
    "bandwidth":       _ResBudget("bandwidth", "cockpit_mobile", 512.0, "KB_per_response", "HTTP response bytes (server middleware)"),
    "tile_cache":      _ResBudget("tile_cache", "map_render", 4096.0, "KB_per_tile", "globe/tile cache byte size (map_layers)"),
    "model_inference": _ResBudget("model_inference", "plan", 50.0, "ms", "gated: no learned model deployed (ML-01/FS-12)"),
}
_RES_SAMPLES: dict[str, "deque[float]"] = {}
_LAST_CPU_S: float = 0.0


def resource_budget_classes() -> dict:
    """The declared FS-10 resource budgets (class -> subsystem/budget/unit/live-source), independent of
    any recorded samples. The cockpit/System pane reads this so the budget contract is visible even before
    a class has recorded a measurement."""
    return {k: {"subsystem": b.subsystem, "budget": b.budget, "unit": b.unit, "live_source": b.live_source}
            for k, b in _RESOURCE_BUDGETS.items()}


def record_resource(resource_class: str, value: float) -> None:
    """Record one REAL observed measurement (in the class's declared unit) into that class's bounded
    recent-sample window. Unknown classes are ignored (the registry is the finite, declared set)."""
    if resource_class not in _RESOURCE_BUDGETS:
        return
    with _METRICS_LOCK:
        buf = _RES_SAMPLES.get(resource_class)
        if buf is None:
            buf = deque(maxlen=_RES_WINDOW)
            _RES_SAMPLES[resource_class] = buf
        buf.append(float(value))


def sample_process_resources() -> None:
    """Record the process's REAL current memory (peak RSS) and CPU-time into the memory/cpu budgets.
    Uses the stdlib ``resource`` module (no psutil dependency); ru_maxrss is KB on Linux, bytes on macOS.
    Called on each /metrics read so the memory/cpu budget classes carry live OS measurements, not
    injected values. A no-op where ``resource`` is unavailable (Windows)."""
    global _LAST_CPU_S
    try:
        import resource as _res
    except ImportError:                                    # pragma: no cover -- non-POSIX
        return
    import sys
    ru = _res.getrusage(_res.RUSAGE_SELF)
    maxrss = float(ru.ru_maxrss)
    rss_mb = maxrss / (1024.0 * 1024.0) if sys.platform == "darwin" else maxrss / 1024.0
    record_resource("memory", rss_mb)
    cpu_s = float(ru.ru_utime + ru.ru_stime)
    record_resource("cpu", cpu_s)
    _LAST_CPU_S = cpu_s


def resource_budget_snapshot() -> dict:
    """Per-class resource-budget summary from the recent-sample window: count, p95, max, the declared
    budget/unit/subsystem, and an over_budget flag (p95 over budget). Classes with no recorded sample
    yet report count=0 with their declared budget so the contract is still visible. A consistent copy
    under the metrics lock."""
    with _METRICS_LOCK:
        samples = {k: list(v) for k, v in _RES_SAMPLES.items()}
    out: dict[str, dict] = {}
    for cls, b in _RESOURCE_BUDGETS.items():
        s = sorted(samples.get(cls, []))
        row = {"subsystem": b.subsystem, "budget": b.budget, "unit": b.unit,
               "live_source": b.live_source, "count": len(s)}
        if s:
            p95 = _pct(s, 0.95)
            row.update({"p95": round(p95, 1), "max": round(s[-1], 1), "over_budget": p95 > b.budget})
        else:
            row.update({"p95": None, "max": None, "over_budget": False})
        out[cls] = row
    return out


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
