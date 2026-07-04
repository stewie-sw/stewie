"""Health + metrics router (ARCH-3): the liveness probe (/healthz) and the request-counter readout
(/metrics). The counters + uptime clock live in server.services (the HTTP middleware records every
request there); these routes read a consistent snapshot. No app-module import (no cycle)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from stewie.server.deps import require_auth
from stewie.server.services import (
    audit_health,
    latency_snapshot,
    metrics_snapshot,
    resource_budget_snapshot,
    revocation_health,
    sample_process_resources,
    uptime_s,
)

router = APIRouter()


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("stewie")
    except Exception:   # noqa: BLE001 -- not installed (editable/source run)
        return "0.1.0"


def _identity_health() -> dict:
    # BP-04: identity is DEGRADED when a PRODUCTION (TLS-terminated) deployment runs on BUILT-IN default
    # identity -- no explicit STEWIE_ALLOWED_OPERATORS / STEWIE_DIRECTORS. allowlist() then fails closed,
    # and this surfaces the misconfiguration. dev/desktop on defaults is NOT degraded.
    import os

    from stewie.server import auth as _auth
    on_defaults = _auth.identity_on_builtin_defaults()
    prod = os.environ.get("STEWIE_TLS_TERMINATED", "") == "1"
    return {"on_builtin_defaults": on_defaults, "degraded": bool(on_defaults and prod)}


@router.get("/healthz")
def healthz():
    # S-10 / SEC-02: surface the audit-ledger AND session-revocation health so a silently-stopped
    # security trail or a fail-closed (unreadable) revocation store is OBSERVABLE. BP-04 adds identity
    # health (prod running on built-in defaults). Status flips to 'degraded' when ANY subsystem is degraded.
    ah = audit_health()
    rh = revocation_health()
    ih = _identity_health()
    return {"status": "degraded" if (ah["degraded"] or rh["degraded"] or ih["degraded"]) else "ok",
            "version": _version(), "uptime_s": uptime_s(), "audit": ah, "revocation": rh, "identity": ih}


@router.get("/metrics")
def metrics(_auth: str = Depends(require_auth)):
    # FS-10: the latency block reports p50/p95/max per route against its budget (over_budget flagged);
    # the budgets block extends that accounting to memory/cpu/gpu/bandwidth/tile-cache/model-inference.
    # sample_process_resources() records the process's REAL current RSS + CPU time before the snapshot.
    sample_process_resources()
    return {"uptime_s": uptime_s(), **metrics_snapshot(), "latency": latency_snapshot(),
            "budgets": resource_budget_snapshot()}
