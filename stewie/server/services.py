"""Shared cross-cutting services for the cockpit server (ARCH-3).

Extracted from server.py so the per-concern routers can use them without importing the app module:
the append-only audit ledger and the process-wide request-metrics counters (the HTTP middleware
records every request here; the /metrics + /healthz routes read a snapshot).
"""
from __future__ import annotations

import os
import threading
import time


def log_event(actor: str, action: str, target: str = "") -> None:
    """Append-only audit line under data_dir (the replicate path covers it). Never raises."""
    import json as _json
    import time as _time

    from stewie.specs import config as CFG
    try:
        with open(os.path.join(CFG.data_dir(), "events.jsonl"), "a") as f:
            f.write(_json.dumps({"ts": round(_time.time(), 3), "actor": actor,
                                 "action": action, "target": target}) + "\n")
    except OSError:
        pass


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
