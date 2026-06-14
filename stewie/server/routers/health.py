"""Health + metrics router (ARCH-3): the liveness probe (/healthz) and the request-counter readout
(/metrics). The counters + uptime clock live in server.services (the HTTP middleware records every
request there); these routes read a consistent snapshot. No app-module import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter

from stewie.server.services import audit_health, metrics_snapshot, uptime_s

router = APIRouter()


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("stewie")
    except Exception:   # noqa: BLE001 -- not installed (editable/source run)
        return "0.1.0"


@router.get("/healthz")
def healthz():
    # S-10: surface the audit-ledger health so a silently-stopped security trail is OBSERVABLE. The
    # status flips to 'degraded' when audit writes have been failing (the trail is incomplete).
    ah = audit_health()
    return {"status": "degraded" if ah["degraded"] else "ok", "version": _version(),
            "uptime_s": uptime_s(), "audit": ah}


@router.get("/metrics")
def metrics():
    return {"uptime_s": uptime_s(), **metrics_snapshot()}
