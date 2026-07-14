"""Navigation-evidence router (#108): surface the grounded navigation evidence for the cockpit System
pane -- the comparison (accuracy/precision vs the cited Stanford-LAC and ShadowNav baselines), the
generalization (the capability matrix positioning the three approach classes by regime), and the
photometric+depth modality precision (articulation parallax vs physical stereo). Every number comes
from dart.comparison (sourced constants + the parallax covariance model), so this is read-only published
methodology, no secrets -> an open GET like /figures and /metrics.

Also (#EV-01): the EVIDENCE/REPORT BUNDLE (GET /evidence/bundle) -- one read-only assembly that reproduces
what a mission ran on from the EXISTING persisted sources (plan inputs / selected layers / runtime profile /
world transactions / audit), plus the host-gated ROS/Gazebo/RViz/Godot run captures shown HONESTLY as
'not captured' (never fabricated). Both routes are open GETs (published methodology / map-data reads); no
app-module import (dart + the source modules are leaves here), so no router<->app cycle.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
from dataclasses import asdict

from fastapi import APIRouter

router = APIRouter()

_MODALITY_RANGE_M = 6.0   # near-range landmarks (~shadow-tip distance) where the modalities are compared

# [REQ:EV-01] the host-gated run-capture kinds the acceptance names (ROS bags / Gazebo / RViz / Godot).
# NONE are persisted in the backend data_dir -- they require a live ROS2/Gazebo run on a container host or a
# GPU render (see PRD RS-05/RS-06, the Godot render track). The bundle declares each honestly as
# ``captured: false`` with a reason; it NEVER fabricates a capture artifact. If a run ever DID persist one
# under data_dir/captures/<kind>, the probe below would surface its real path instead (no false negative).
_CAPTURE_KINDS = (
    ("ros_bag", "rosbag2 MCAP of the run's /clock+/tf+sensor topics",
     "host-gated: requires a live ROS2 run (container/pit); not persisted in the backend data_dir"),
    ("gazebo_recording", "Gazebo world state recording",
     "host-gated: requires a live Gazebo sim on a container host; not persisted in the backend data_dir"),
    ("rviz_capture", "RViz display screengrab of the run",
     "host-gated: requires a live RViz session (X/GPU); not persisted in the backend data_dir"),
    ("godot_frames", "Godot sensor-rig camera PNGs (LAC 8-cam + AprilTag)",
     "host-gated: requires a GPU Godot render; the dev render track writes out/cam/, not the per-run data_dir"),
)


@router.get("/evidence")
def get_evidence() -> dict:
    """The navigation evidence bundle: comparison / generalization / photometric+depth + op cost."""
    from dart import comparison as CMP    # [REQ:AP-01] lazy: app-layer router, not a module-level dart edge
    return {
        "ok": True,
        "capability_matrix": CMP.nav_capability_matrix(),               # generalization: 3 approach classes
        "accuracy_precision": CMP.accuracy_precision_comparison(),       # comparison vs the cited baselines
        "modality_sigma": {"range_m": _MODALITY_RANGE_M,                 # photometric+depth precision
                           **CMP.modality_range_sigma(_MODALITY_RANGE_M)},
        "operational_cost": CMP.operational_cost(),                      # time/energy of a fix + a traverse
    }


def _plan_inputs(mission: str | None) -> dict:
    """[REQ:EV-01] the persisted PLAN INPUTS: the world-log ``record_plan`` transactions (each carries the
    released plan_id + mission + provenance -- the durable record of WHICH plan ran) and the persisted
    mission-control report artifacts (PDF/md on disk = the plan records). The executable Plan IR itself is a
    re-derivable VIEW (POST /plan re-computes it from the request); it is not stored verbatim, so the honest
    persisted inputs are the world-log plan transactions + the report artifacts. Never fabricated."""
    from stewie.server import state as S
    from stewie.specs.config import reports_dir
    wss = S.world_state_service()
    recent = wss.recent(500)
    plan_txns = [t for t in recent if t.get("plan_id")]                  # record_plan sets plan_id
    if mission:
        plan_txns = [t for t in plan_txns if (t.get("mission") or "") == mission]
    reports: list[dict] = []
    rdir = reports_dir()
    if os.path.isdir(rdir):
        pdfs = sorted(glob.glob(os.path.join(rdir, "*.pdf")), key=os.path.getmtime, reverse=True)
        for p in pdfs[:25]:
            stem = os.path.splitext(os.path.basename(p))[0]
            md = os.path.join(rdir, stem + ".md")
            reports.append({"stem": stem, "pdf": "/reports/" + os.path.basename(p),
                            "md": ("/reports/" + stem + ".md") if os.path.isfile(md) else None,
                            "size_bytes": os.path.getsize(p), "mtime": int(os.path.getmtime(p))})
    return {"plan_transactions": plan_txns, "n_plans": len(plan_txns),
            "reports": reports, "n_reports": len(reports),
            "note": ("plan inputs are reproduced from the durable world-log record_plan transactions (which "
                     "plan_id/mission ran) + the persisted report artifacts (the plan records). The executable "
                     "Plan IR is a re-derivable view (POST /plan), not stored verbatim -- so it is not claimed "
                     "as a persisted artifact here.")}


def _selected_layers(site: str) -> dict:
    """[REQ:EV-01] the SELECTED LAYERS: the LY-01 catalog's planning-eligible layers (the map layers a plan
    consumes), each with its declared source_class + the GW-03 source-class-implied confidence, plus the
    per-site DT-05 freshness/provenance (observed_fraction, provenance_class, dem_source). Assembled from the
    real committed catalog + the site's own observed twin -- no synthetic freshness."""
    from stewie.server.routers.world import _site_enrichment, layer_confidence
    cat_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "layer_catalog.json")
    with open(cat_path, encoding="utf-8") as fh:
        cat = json.load(fh)
    planning = [{"id": ly["id"], "domain": ly["domain"], "type": ly["type"],
                 "source_class": ly.get("source_class", ""),
                 "confidence": layer_confidence(ly.get("source_class", "")),
                 "release_execute_eligible": bool(ly.get("release_execute_eligible"))}
                for ly in cat.get("layers", []) if ly.get("planning_eligible")]
    enr = _site_enrichment(site)
    if enr is None:
        freshness = None
    else:
        freshness = {"observed": enr["observed"], "observed_fraction": enr["observed_fraction"],
                     "provenance_class": ("observed" if enr["observed_fraction"] > 0.0 else "prior"),
                     "dem_source": enr["dem_source"], "twin_version": enr["twin_version"],
                     "as_built_version": enr["as_built_version"], "mutated": enr["mutated"]}
    return {"catalog_count": len(cat.get("layers", [])), "planning_layers": planning,
            "n_planning_layers": len(planning), "freshness": freshness}


def _runtime_profile() -> dict:
    """[REQ:EV-01] the RUNTIME PROFILE (RT-01): the 8-profile escalation registry + the profile the persisted
    SIM runs execute on -- ``desktop_sil`` (the conserved numpy authority; evidence_class forecast, no live
    command). The live-command profiles (hil/field_test/live_rover) are declared but NOT exercised here (the
    SIM path holds no command authority). The active id is honest, not asserted-as-live."""
    from stewie.specs.runtime_profiles import PROFILES, list_runtime_profiles
    active = "desktop_sil"                                               # the SIM/plan authority the runs use
    return {"active_profile_id": active, "active_profile": PROFILES.get(active),
            "registry": list_runtime_profiles(), "count": len(PROFILES),
            "note": ("the persisted SIM/plan runs execute on desktop_sil (conserved numpy authority, "
                     "evidence_class forecast, can_release/can_execute False); only hil/field_test/live_rover "
                     "carry live command authority and are not exercised on this SIM path.")}


def _world_transactions(mission: str | None, limit: int) -> dict:
    """[REQ:EV-01] the DT-03 world-transaction log (the linked plan/terrain/execution timeline that proves
    what ran), the most recent ``limit`` (optionally filtered to one mission), with the chain-integrity flag."""
    from stewie.server import state as S
    lim = max(1, min(500, int(limit)))
    wss = S.world_state_service()
    txns = wss.recent(lim)
    if mission:
        txns = [t for t in txns if (t.get("mission") or "") == mission]
    return {"count": wss.transaction_count(), "verified": wss.verify_chain(),
            "transactions": txns, "returned": len(txns)}


def _audit(mission: str | None, session: str | None) -> dict:
    """[REQ:EV-01] the AUDIT trail: the EG-07 tamper-evident executive audit chain (director releases + SIM
    runs, who/what/when/where/mode/reason/before/after/evidence) with its integrity flag, optionally narrowed
    to one mission's location; and, when a ``session`` id is given, the GW-08 edit-session versioned audit tail."""
    from stewie.server.audit_log import get_audit_log
    lg = get_audit_log()
    records = [asdict(r) for r in lg.records()]
    if mission:
        records = [r for r in records if mission in str(r.get("location", ""))]
    out: dict = {"executive": {"verified": lg.verify(), "count": len(lg.records()),
                               "records": records, "returned": len(records)}}
    if session:
        from stewie.server.edit_session import get_session
        sess = get_session(str(session))
        if sess is None:
            out["edit_session"] = {"session": session, "found": False,
                                   "note": "no such edit session (a stale id is honestly reported, not faked)"}
        else:
            out["edit_session"] = {"session": sess.id, "found": True, "version": sess.version,
                                   "audit": sess.audit()}
    return out


def _artifacts() -> dict:
    """[REQ:EV-01/FS-27] the ROS/Gazebo/RViz/Godot artifacts. The COMMITTED-config evidence (lifecycle nodes,
    bridge/clock topics, RViz displays, Gazebo worlds, container tiers) is real + persisted -> surfaced. The
    live run CAPTURES (bags/recordings/screengrabs/frames) are HOST-GATED: none is persisted in the backend
    data_dir, so each is declared ``captured: false`` with a reason -- honest, never a fabricated artifact.
    A capture that a run genuinely persisted under data_dir/captures/<kind> would surface its real path."""
    from stewie.server.ros_evidence import collect_ros_evidence
    from stewie.specs.config import data_dir
    cap_root = os.path.join(data_dir(), "captures")
    captures = []
    for kind, what, reason in _CAPTURE_KINDS:
        d = os.path.join(cap_root, kind)
        present = sorted(glob.glob(os.path.join(d, "*"))) if os.path.isdir(d) else []
        if present:                                                     # a real persisted capture -> report it
            captures.append({"kind": kind, "what": what, "captured": True,
                             "paths": ["/captures/" + kind + "/" + os.path.basename(p) for p in present[:20]],
                             "count": len(present)})
        else:
            captures.append({"kind": kind, "what": what, "captured": False, "reason": reason})
    return {"ros_gazebo_rviz": collect_ros_evidence(), "captures": captures,
            "host_gated_kinds": [k for k, _w, _r in _CAPTURE_KINDS]}


@router.get("/evidence/bundle")
def evidence_bundle(site: str = "haworth", mission: str | None = None,
                    session: str | None = None, limit: int = 50) -> dict:
    """[REQ:EV-01] The EVIDENCE/REPORT BUNDLE: one read-only assembly that reproduces what a mission ran on,
    from the EXISTING persisted sources -- plan inputs (world-log record_plan transactions + report
    artifacts), the selected layers (LY-01 catalog + GW-03 confidence + DT-05 per-site freshness), the
    runtime profile (RT-01 registry + the SIM authority profile), the world transactions (DT-03 log), and the
    audit trail (EG-07 executive chain + the optional GW-08 edit-session audit). The ROS/Gazebo/RViz/Godot
    run CAPTURES are HOST-GATED and shown honestly as 'not captured' (never fabricated). A ``bundle_sha`` over
    the assembly gives the single evidence artifact the acceptance asks for -- 'one bundle proves what ran'.

    Public read (published methodology / map-data, like /evidence and /world/layer-catalog): nginx proxies
    /api/ keyless for these GETs. Filters: ``mission`` narrows the plan/world/audit records to one mission;
    ``session`` attaches an edit-session audit tail; ``limit`` bounds the world-transaction window ([1, 500])."""
    body = {
        "ok": True,
        "site": site, "mission": mission, "session": session,
        "plan_inputs": _plan_inputs(mission),
        "selected_layers": _selected_layers(site),
        "runtime_profile": _runtime_profile(),
        "world_transactions": _world_transactions(mission, limit),
        "audit": _audit(mission, session),
        "artifacts": _artifacts(),
        # the axes reproduced from PERSISTED sources vs the axes that are HOST-GATED (shown, not fabricated).
        "reproduced": ["plan_inputs", "selected_layers", "runtime_profile", "world_transactions", "audit"],
        "host_gated": [k for k, _w, _r in _CAPTURE_KINDS],
    }
    # the single evidence artifact: a content hash over the whole assembly (excluding the hash field) so the
    # bundle is self-attesting -- the same persisted state reproduces the same bundle_sha.
    payload = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
    body["bundle_sha"] = hashlib.sha256(payload).hexdigest()
    return body
