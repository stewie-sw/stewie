"""Health + metrics router (ARCH-3): the liveness probe (/healthz) and the request-counter readout
(/metrics). The counters + uptime clock live in server.services (the HTTP middleware records every
request there); these routes read a consistent snapshot. No app-module import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter

from stewie.server.services import (
    audit_health,
    latency_snapshot,
    metrics_snapshot,
    revocation_health,
    uptime_s,
)

router = APIRouter()


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("stewie")
    except Exception:   # noqa: BLE001 -- not installed (editable/source run)
        return "0.1.0"


@router.get("/healthz")
def healthz():
    # S-10 / SEC-02: surface the audit-ledger AND session-revocation health so a silently-stopped
    # security trail or a fail-closed (unreadable) revocation store is OBSERVABLE. The status flips to
    # 'degraded' when either subsystem is degraded (audit writes failing, or revocation reads failing).
    ah = audit_health()
    rh = revocation_health()
    return {"status": "degraded" if (ah["degraded"] or rh["degraded"]) else "ok", "version": _version(),
            "uptime_s": uptime_s(), "audit": ah, "revocation": rh}


@router.get("/metrics")
def metrics():
    # FS-10: the latency block reports p50/p95/max per route against its budget (over_budget flagged).
    return {"uptime_s": uptime_s(), **metrics_snapshot(), "latency": latency_snapshot()}
