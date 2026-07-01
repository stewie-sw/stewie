"""Admin-ops router (ARCH-3): the director-only maintenance operations -- twin snapshot + snapshot
retention, off-host backup replication, and the G1/G2 release-gate re-validation button. Director
-gated (server.deps); the twin store comes from server.state. Distinct from operators_admin (which
manages operator ACCOUNTS); this is the ops/maintenance surface. No app-module import (no cycle)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from stewie.server import state
from stewie.server.deps import require_director
from stewie.server.services import log_event

router = APIRouter()


@router.post("/admin/twin/snapshot")
def admin_snapshot(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    path = BK.snapshot(state.twin(), os.path.join(CFG.data_dir(), "snapshots"))
    log_event(_auth, "admin.twin.snapshot", os.path.basename(path))     # FS-19: maintenance ops audit
    return {"ok": True, "snapshot": path}


@router.post("/admin/twin/retention")
def admin_retention(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    removed = BK.apply_retention(os.path.join(CFG.data_dir(), "snapshots"))
    log_event(_auth, "admin.twin.retention", f"{len(removed)} removed")
    return {"ok": True, "removed": removed}


@router.post("/admin/backup/replicate")
def admin_replicate(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    dest = os.environ.get("STEWIE_BACKUP_DIR", os.path.join(CFG.data_dir(), "replica"))
    out = BK.replicate(CFG.data_dir(), dest)
    log_event(_auth, "admin.backup.replicate", dest)
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
    # P3 (PRD §22.3): surface the actual gate EVIDENCE numbers (not just PASS/PASS) for the review
    # panel. Every value is read from the on-disk artifact; an absent key degrades to None (older
    # artifacts may carry a different schema). No number is computed or fabricated here.
    g1, g2 = latest.get("g1", {}), latest.get("g2", {})
    kd, sc = g1.get("katwijk_dead_reckon", {}), g1.get("simulated_closure", {})
    cc, cov = g1.get("contract_checks", {}), g2.get("covariance_calibration", {})
    evidence = {
        "evidence_mode": latest.get("evidence_mode"),
        "g1_ate_m": kd.get("ate_aligned_m"),
        "g1_eval_track_m": kd.get("eval_track_length_m"),
        "g1_baseline_raw_m": sc.get("baseline_wheel_imu_ate_raw_m"),
        "g1_baseline_aligned_m": sc.get("baseline_wheel_imu_ate_aligned_m"),
        "g1_contract_checks_pass": sum(1 for v in cc.values() if v == "PASS"),
        "g1_contract_checks_total": len(cc),
        "g2_sigma_px": cov.get("sigma_disparity_px"),
        "g2_coverage_3sigma": cov.get("held_out_coverage_3sigma"),
        "g2_median_depth_m": g2.get("median_depth_m"),
        "g2_sigma_depth_m": g2.get("median_sigma_depth_m"),
        "g2_evidence_scope": g2.get("evidence_scope"),
        "next_gate": summary.get("next_gate"),
    }
    log_event(_auth, "admin.gates.validate",
              f"G1={summary.get('G1', '?')} G2={summary.get('G2', '?')} byte_identical={same}")
    return {"ok": True, "g1": str(summary.get("G1", "?")), "g2": str(summary.get("G2", "?")),
            "latest_artifact": dated[-1], "byte_identical_to_frozen": same, "evidence": evidence}
