"""Config + sites router (ARCH-3): the runtime config overlay (PRD N15 describe(), secret values
scrubbed before they reach the browser), the organized Config-pane state (#61: server / auth FLAGS /
data holdings / overlay), and the site registry. Read-only; no app-module import (no cycle)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from stewie.server.deps import _env, require_auth

router = APIRouter()


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("stewie")
    except Exception:   # noqa: BLE001 -- not installed (editable/source run)
        return "0.1.0"


def _redact_secrets(node):
    """Scrub key/token/secret VALUES from the overlay dump (the N15 describe() includes env
    values -- the API key must never reach the browser)."""
    secret = os.environ.get("STEWIE_API_KEY", "")
    if isinstance(node, dict):
        return {k: ("[REDACTED]" if any(t in str(k).upper() for t in ("KEY", "TOKEN", "SECRET"))
                    else _redact_secrets(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_redact_secrets(v) for v in node]
    if isinstance(node, str) and secret and secret in node:
        return "[REDACTED]"
    return node


@router.get("/sites")
def sites_list(_auth: str = Depends(require_auth)):
    """#49: the site registry (Haworth imported; Artemis III candidates honest about data state).
    S-06: operational reads require auth (the site registry is operational configuration)."""
    from stewie.specs.sites import site_rows
    return {"ok": True, "sites": site_rows()}


@router.get("/config")
def get_config(_auth: str = Depends(require_auth)):
    """Runtime config overlay state (intern/dev pane): config_file + overrides + applied (PRD N15).
    SEC-1: describe() redacts secret values at the source; this also passes through _redact_secrets
    (defense in depth) so a future describe() field cannot leak a key. S-06: auth required."""
    from stewie.specs import config as _cfg
    return {"ok": True, **_redact_secrets(_cfg.describe())}


@router.get("/config/full")
def get_config_full(_auth: str = Depends(require_auth)):
    """#61 (Aaron: "config needs to be totally rewritten"): the organized one-call state for the
    Config pane -- server, auth FLAGS (never the key), data holdings, and the N15 overlay.
    S-06: auth required (config exposes data_dir paths + auth posture)."""
    from stewie.specs import config as _cfg
    from stewie.specs.sites import site_rows
    try:
        from stewie.specs.solar import spice_available
        spice = bool(spice_available())
    except Exception:
        spice = False
    rows = site_rows()
    snaps_dir = os.path.join(_cfg.data_dir(), "snapshots")
    n_snaps = len([f for f in os.listdir(snaps_dir) if f.endswith(".npz")]) if os.path.isdir(snaps_dir) else 0
    return {
        "ok": True,
        "server": {"version": _version(), "data_dir": _cfg.data_dir(),
                   "backup_dir": os.environ.get("STEWIE_BACKUP_DIR", "(data_dir)/replica")},
        "auth": {"api_key_set": bool(_env("API_KEY")),
                 "operator_login": os.environ.get("STEWIE_OPERATOR_LOGIN", "1") != "0",
                 "trust_tailscale": os.environ.get("STEWIE_TRUST_TAILSCALE", "") == "1"},
        "data": {"sites_total": len(rows), "sites_imported": sum(1 for r in rows if r["imported"]),
                 "spice_available": spice, "twin_snapshots": n_snaps},
        "overlay": _redact_secrets(_cfg.describe()),
    }
