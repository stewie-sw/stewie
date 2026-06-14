"""Admin-ops router (ARCH-3): the director-only maintenance operations -- twin snapshot + snapshot
retention, off-host backup replication, and the G1/G2 release-gate re-validation button. Director
-gated (server.deps); the twin store comes from server.state. Distinct from operators_admin (which
manages operator ACCOUNTS); this is the ops/maintenance surface. No app-module import (no cycle)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from stewie.server import state
from stewie.server.deps import require_director

router = APIRouter()


@router.post("/admin/twin/snapshot")
def admin_snapshot(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    path = BK.snapshot(state.twin(), os.path.join(CFG.data_dir(), "snapshots"))
    return {"ok": True, "snapshot": path}


@router.post("/admin/twin/retention")
def admin_retention(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    removed = BK.apply_retention(os.path.join(CFG.data_dir(), "snapshots"))
    return {"ok": True, "removed": removed}


@router.post("/admin/backup/replicate")
def admin_replicate(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    dest = os.environ.get("STEWIE_BACKUP_DIR", os.path.join(CFG.data_dir(), "replica"))
    out = BK.replicate(CFG.data_dir(), dest)
    return {"ok": True, **out}


@router.post("/admin/gates/validate")
def admin_gates(_auth: str = Depends(require_director)):
    """The standing invariant as a BUTTON: re-run the dated G1/G2 validation and compare against
    the frozen 2026-06-07 artifact byte-for-byte."""
    import json as _json

    from stewie.eval import gates as GA
    vdir = os.path.join(os.path.dirname(os.path.abspath(GA.__file__)), "validation")
    # the INVARIANT: re-running the frozen 2026-06-07 baseline must reproduce it byte-for-byte
    cur = GA.validate()
    frozen = open(os.path.join(vdir, "g1_g2_validation_2026-06-07.json"), "rb").read()
    same = frozen == _json.dumps(cur, indent=2).encode() + b"\n"
    # the CURRENT gate states live in the LATEST dated artifact (gates flip only via new artifacts)
    dated = sorted(f for f in os.listdir(vdir) if f.startswith("g1_g2_validation_"))
    latest = _json.load(open(os.path.join(vdir, dated[-1])))
    summary = latest.get("release_gate_summary", {})
    return {"ok": True, "g1": str(summary.get("G1", "?")), "g2": str(summary.get("G2", "?")),
            "latest_artifact": dated[-1], "byte_identical_to_frozen": same}
