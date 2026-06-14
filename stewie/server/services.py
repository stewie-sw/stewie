"""Shared cross-cutting services for the cockpit server (ARCH-3).

Extracted from server.py so the per-concern routers can use them without importing the app module.
Currently the append-only audit ledger; future shared services (metrics, etc.) land here too.
"""
from __future__ import annotations

import os


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
