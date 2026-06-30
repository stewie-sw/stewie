"""Plan router (ARCH-3): the planner surface -- the full /plan (one compute -> report + IR + ordered
acceptance), the reusable RC command tape (/plan/commands), the math worksheet (/plan/math), the
director forward-comparison (/resync/compare), and the selectable map layers (/layers + the DEM-backed
raster overlay /layers/raster). The site DEM comes from server.state; auth/audit/report-lock/prune from
server.deps + server.services; the heavy planner modules import lazily. No app-module import (no cycle)."""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from stewie.server import state
from stewie.server.deps import require_auth, require_director
from stewie.server.ratelimit import RateLimiter
from stewie.server.schemas import Order, _MAX_ORDERS
from stewie.server.services import log_event, prune_reports, report_lock

router = APIRouter()
log = logging.getLogger("stewie.server")


# S-08: a per-identity quota on the compute-heavy planner routes (routing + algorithm comparison +
# acceptance + matplotlib PDF render run synchronously in the single worker). One identity cannot
# monopolize the worker with repeated heavy planning; a normal single plan is unaffected.
def _heavy_quota_max() -> int:
    return int(os.environ.get("STEWIE_HEAVY_QUOTA_MAX", "30"))


def _heavy_quota_window() -> float:
    return float(os.environ.get("STEWIE_HEAVY_QUOTA_WINDOW_S", "60"))


_heavy_quota = RateLimiter(_heavy_quota_max(), _heavy_quota_window())


def heavy_quota(identity: str = Depends(require_auth)) -> str:
    """Auth + a per-identity heavy-route quota (S-08). Returns the identity; raises 429 when the
    identity exceeds its compute budget in the window."""
    if not _heavy_quota.allow(identity):
        raise HTTPException(status_code=429,
                            detail="per-identity compute quota exceeded for heavy planning; slow down")
    return identity


# ARCH-01/04: the plan/report compute runs SYNCHRONOUSLY in the worker (the deploy is one uvicorn worker;
# FastAPI runs sync routes in the anyio threadpool). Two caps keep one heavy request from monopolizing it:
# (1) an INPUT-SIZE cap rejects an oversized mission before the compute (bounds the work); (2) a WALL-CLOCK
# deadline bounds the client's wait. NOTE: Python cannot force-kill a worker thread, so a runaway compute
# runs to completion in the background -- the deadline bounds the CLIENT and signals overload; the input
# cap is what actually bounds the compute. (orders + vehicles are already capped by the typed PlanRequest.)
def _max_keepouts() -> int:
    return int(os.environ.get("STEWIE_MAX_KEEPOUTS", "200"))


def _plan_deadline_s() -> float:
    return float(os.environ.get("STEWIE_PLAN_DEADLINE_S", "120"))


_PLAN_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="plan")


def _oversized_plan(payload) -> JSONResponse | None:
    """ARCH-01/04 input-size cap: reject (413) a mission whose keep-out count exceeds the bound, BEFORE
    the heavy compute, so a pathological input cannot drive an unbounded plan."""
    n_ko = len(payload.get("keepouts") or [])
    if n_ko > _max_keepouts():
        return JSONResponse(status_code=413, content={"ok": False, "error":
                            f"too many keep-outs ({n_ko} > {_max_keepouts()}); split the mission"})
    return None


def _bounded(fn):
    """ARCH-01/04 wall-clock cap: run `fn` under a per-request deadline; raises TimeoutError past it."""
    return _PLAN_POOL.submit(fn).result(timeout=_plan_deadline_s())


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(default="mission", max_length=200)
    body: str = Field(default="moon", max_length=40)
    orders: list[Order] = Field(default_factory=list, max_length=_MAX_ORDERS)
    algorithm: str = Field(default="nearest", max_length=40)
    objective: str = Field(default="time", max_length=40)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)   # M11: globe site-pick -> order-frame anchor
    lon: float | None = Field(default=None, ge=-360.0, le=360.0)
    vehicles: int = Field(default=1, ge=1, le=16)               # MV: fleet size (>1 -> multi-vehicle plan)
    site: str = Field(default="haworth", max_length=40)        # REG-01: which imported site DEM to plan on
    max_traverse_slope_deg: float = Field(default=25.0, ge=5.0, le=45.0)   # operator slope budget: the routing traversability gate (planner default 25 deg)
    charger_capacity: int = Field(default=1, ge=1, le=8)   # FL-03: how many rovers can charge at once (multi-vehicle contention; default 1 = single shared charger)


def _totals_json(totals):
    """JSON-safe totals: numbers -> float, but pass through bools/strings (algorithm/objective) and already
    JSON-safe containers (e.g. vehicles_detail = a list of per-vehicle dicts) + None unchanged."""
    out = {}
    for k, v in totals.items():
        out[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return out


def _plan_stem(payload):
    """S-06: an OPAQUE, collision-free report stem. The id is HMAC(session-secret, payload) -- a
    network user who knows the mission name/body cannot derive the filename (the old slug+sha1 stem
    was fully derivable from public mission knowledge), so reports cannot be enumerated. It stays
    DETERMINISTIC for the same payload (no wall-clock), so re-planning the same queue regenerates the
    same file instead of piling up duplicates. No mission name leaks into the path."""
    import hmac
    import json

    from stewie.server import auth as AUTH
    digest = hmac.new(AUTH._signing_secret(),
                      json.dumps(payload, sort_keys=True).encode(),
                      hashlib.sha256).hexdigest()[:24]
    return f"report-{digest}"


def _autonomy_perception(mission, dem, origin, algorithm, objective):
    """Fold the closed-loop autonomy + the AutoNav estimation (perception) uncertainty into /plan.

    Runs the conserved-model closed loop (plan -> execute -> estimate -> replan) once. The `autonomy`
    block summarizes the controller (recharges/replans/completion + the true-vs-budgeted energy the slip
    truth forces); the `perception` block is the rover's onboard ESTIMATE confidence (pose sigma grows by
    dead-reckoning, drum-fill sigma from the FDC mass-inference model, energy sigma from model error).
    Additive: any failure returns (None, None) so the report still goes out."""
    from lode import adaptive_planner as ADP
    from lode import autonomy as AUT
    try:                                               # perception-in-the-loop ON: a SLAM/map pose fix per leg
        cl = AUT.run_closed_loop(mission, dem=dem, dem_origin=origin, algorithm=algorithm,
                                 objective=objective, perception_sigma_m=0.10)
    except Exception as e:                             # noqa: BLE001 -- autonomy is additive, never break /plan
        log.warning("autonomy/perception block folded out (additive; /plan still served): %r", e)
        return None, None
    b, legs = cl["belief"], cl["legs"]
    nominal = sum(leg["nominal_J"] for leg in legs)
    true = sum(leg["true_J"] for leg in legs)
    energy = ADP.price_mission(legs, ADP.learned_model())   # self-learned slip energy applied to this plan
    autonomy = {
        "completed": cl["completed"], "n_trips": cl["n_trips"], "n_legs": len(legs),
        "recharges": cl["recharges"], "replans": cl["replans"],
        "perception_fixes": cl["perception_fixes"], "observe_more": cl["observe_more"],
        "final_soc": round(b.soc_frac(), 3),
        "max_slip": round(max((leg["slip"] for leg in legs), default=0.0), 3),
        "true_vs_nominal_energy": round(true / nominal, 3) if nominal else None,
        # self-optimizing: the LEARNED slip-energy model re-prices the plan toward the executed truth
        "energy_naive_kj": round(energy["naive_J"] / 1e3, 1),
        "energy_learned_kj": round(energy["learned_J"] / 1e3, 1),
        "energy_actual_kj": round(energy["actual_J"] / 1e3, 1),
    }
    leg_e_sig = max((leg["energy_sigma_J"] for leg in legs), default=0.0)
    mc = cl.get("map_channel", {})
    perception = {
        "pose_sigma_m": round(b.pos_sigma_m, 2),               # BOUNDED by the per-leg map/landmark fixes
        "map_fixes": cl["perception_fixes"],                   # pose corrections fused into the belief
        "observe_more_before_dig": cl["observe_more"],         # Uncertainty-layer dig-ready gate firings
        "fix_sigma_m": 0.10,                                   # SLAM/map-match fix precision (AprilTag 12.7 mm best-case)
        "energy_model_sigma_J": round(leg_e_sig, 1),           # slip model-error 1-sigma carried per leg
        "drum_fill_uncertainty_pct": 7.4,                      # FDC mass-inference MPE (2.56% >half full, 7.40% over range)
        # P6 / LAC section 10 map channel, closed into the loop: the executed route's worksite COVERAGE +
        # residual map uncertainty (onboard-observability tier), and the digs gated on local map coverage.
        "map_coverage": round(mc.get("coverage", 0.0), 3),
        "map_uncertainty_m": round(mc.get("mean_uncertainty_m", 0.0), 2),
        "map_observe_more_before_dig": cl.get("map_observe_more", 0),
        "map_survey_time_s": round(cl.get("survey_time_s", 0.0), 1),   # the survey-before-dig gate's real time cost
        # REAL-localization trace for the cockpit Navigation pane: per-leg estimated (believed) pose vs the
        # true pose, the pos sigma, and which real fix corrected it (dem scan-match / beacon AprilTag / none).
        "localization": {
            "trajectory": [{"est": [leg["bx"], leg["by"]], "true": [leg["tx"], leg["ty"]],
                            "sigma": leg["pos_sigma_m"], "fix": leg["fix"]} for leg in legs],
            "fix_kinds": {k: sum(1 for leg in legs if leg.get("fix") == k) for k in ("dem", "beacon", "none")},
        },
        "note": ("perception-in-the-loop: a map/landmark pose fix per leg bounds dead-reckoning drift; the "
                 "dig-ready gate observes more before digging when the pose is uncertain OR the dig site's "
                 "local map coverage is low. map_coverage is the onboard-observability tier (what the route "
                 "sees) -- the dense observed-map RMSE is the gated render/COLMAP tier (see /render)."),
    }
    return autonomy, perception


@router.post("/plan/commands")
def plan_commands(req: PlanRequest, _auth: str = Depends(heavy_quota)):
    """#66 (Aaron: "plan should output cmds for reuse"): the plan as a REUSABLE RC command tape --
    a GoTo sequence (the same contract the sim/pit backend executes). Plan once, command many.
    S-08: auth + per-identity heavy-route quota (this runs routing on the real DEM)."""
    from lode import mission_planner as MP
    from stewie.bridge import rc_contract as RC
    payload = req.model_dump()
    over = _oversized_plan(payload)                  # ARCH-01/04 input-size cap (this routes on the DEM)
    if over is not None:
        return over
    mission = MP.mission_from_dict(payload)
    cell = 5.0 if mission.body == "moon" else 1.0
    dem, origin = state.moon_dem(getattr(req, "site", "haworth")) if mission.body == "moon" else (None, (0.0, 0.0))
    dem = _as_built_dem(getattr(req, "site", "haworth"), dem, origin)   # #242: command tape on the remembered surface
    cmds = RC.commands_from_plan(mission, cell_m=cell, dem=dem, dem_origin=origin)
    return {"ok": True, "cell_m": cell, "commands": [
        {"kind": c.kind, "leg_id": c.leg_id, "goal_row": c.goal_row, "goal_col": c.goal_col,
         "v_max_mps": c.v_max_mps, "goal_radius_cells": c.goal_radius_cells} for c in cmds]}


@router.post("/plan/math")
def plan_math_endpoint(req: PlanRequest, _auth: str = Depends(heavy_quota)):
    """#74: the per-trip MATH WORKSHEET for review (every equation + substituted numbers). S-08: auth
    + per-identity heavy-route quota (it re-derives the routed plan on the real DEM)."""
    from lode import mission_planner as MP
    payload = req.model_dump()
    over = _oversized_plan(payload)                  # ARCH-01/04 input-size cap (re-derives the routed plan)
    if over is not None:
        return over
    mission = MP.mission_from_dict(payload)
    dem, origin = state.moon_dem(getattr(req, "site", "haworth")) if mission.body == "moon" else (None, (0.0, 0.0))
    dem = _as_built_dem(getattr(req, "site", "haworth"), dem, origin)   # #242: math worksheet on the remembered surface
    return {"ok": True, **MP.plan_math(mission, dem=dem, dem_origin=origin)}


@router.post("/resync/compare")
def resync_compare(body: dict, _auth: str = Depends(require_director)):
    """#70: faster-than-realtime forward comparison -- candidate solver inputs re-simulated from
    the CURRENT mission; ranked outcomes with measured wall times. Director-side (it sees truth)."""
    from lode import mission_planner as MP
    from lode.resync import forward_compare
    try:
        mission = MP.mission_from_dict(body.get("mission", body))
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    cands = tuple(body.get("candidates", ("auto", "nearest")))[:5]
    obj = str(body.get("objective", "duration"))
    out = forward_compare(mission, candidates=cands, objective=obj)
    log_event(_auth, "resync.compare", f"{len(cands)} futures")
    return {"ok": True, **out}


@router.get("/layers")
def get_layers():
    """Selectable map layers for the navigation UI (load/unload): imagery, dem, topology, hazard,
    excavation, lander. Vector layers (excavation, lander, zones) are filled per-mission by the client."""
    from stewie.server import map_layers as MLY
    from stewie.server.gis_layers import RASTER_DEFS
    return {"ok": True, "layers": MLY.layer_defs() + RASTER_DEFS}


@router.get("/layers/raster/{kind}.png")
def get_raster_layer(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                     mission_t_s: float | None = None, site: str = "haworth",
                     vmax: float = 30.0, classes: int = 0,
                     _auth: str = Depends(heavy_quota)):
    """A computed GIS raster overlay from the REAL Haworth DEM. S-08: auth + per-identity heavy-route
    quota (each call renders a full raster). When mission_t_s is given the sun
    is AUTOMATIC: real spherical geometry at the Haworth latitude (stewie.specs.solar) -- azimuth
    circles per lunar day, elevation breathes inside colatitude+obliquity. el/az are the manual
    override path. G5 (#251): vmax/classes = the slope graduated-renderer (clamped; NaN -> default 30),
    so the PIP-overlay raster matches the globe drape's symbology."""
    import math
    from stewie.server.gis_layers import render
    if mission_t_s is not None:
        from stewie.specs.sites import site_latlon
        from stewie.specs.solar import sun_az_el
        _lat, _lon = site_latlon(site)                          # #274 (REG-01): the CHOSEN site, not hardcoded Haworth
        sun_az, sun_el = sun_az_el(_lat, float(mission_t_s), site_lon_deg=_lon)
    s_vmax = float(max(1.0, min(90.0, vmax))) if math.isfinite(vmax) else 30.0   # NaN/inf -> default
    s_classes = int(max(0, min(12, classes)))
    try:
        png = render(kind, sun_el=sun_el, sun_az=sun_az, site=site,
                     slope_vmax=s_vmax, slope_classes=s_classes)   # REG-01: the chosen site's tile
    except KeyError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM bundle absent: {e}"})
    if png is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return Response(content=png, media_type="image/png")


@router.post("/plan")
def post_plan(req: PlanRequest, _auth: str = Depends(heavy_quota)):
    # S-08: auth + per-identity compute quota (full plan = routing + comparison + acceptance + PDF).
    # ARCH-01/04: reject an oversized mission UP FRONT, then run the heavy compute under a wall-clock
    # deadline so one request cannot monopolize the single worker (see the cap helpers above).
    payload = req.model_dump(exclude_unset=True)
    over = _oversized_plan(payload)
    if over is not None:
        return over
    try:
        return _bounded(lambda: _plan_impl(req, payload))
    except concurrent.futures.TimeoutError:
        return JSONResponse(status_code=503, content={"ok": False, "error":
                            "plan exceeded the compute budget; reduce the mission size or retry"})


# #267: the as-built remembered-surface imprint is the SINGLE source of truth in state.py, shared with the
# 3D as-built mesh (/dem/asbuilt) so the plan and the rendered topology cannot diverge. Aliased here to keep
# the #242 call sites + test_as_built_readback import (stewie.server.routers.plan._as_built_dem) stable.
_as_built_dem = state.as_built_dem


def _plan_impl(req: PlanRequest, payload: dict):
    """The synchronous plan + report + views compute, run under the ARCH-01/04 caps (post_plan)."""
    from lode import mission_planner as MP
    prune_reports()
    try:
        mission = MP.mission_from_dict(payload)
        if mission.body == "moon":
            dem, origin = state.moon_dem(getattr(req, "site", "haworth"))  # REG-01: the chosen site DEM
            if req.lat is not None and req.lon is not None:   # M11: a globe site-pick overrides the anchor
                try:                                          # REG-01: anchor against the CHOSEN site's tile
                    origin = MP.latlon_to_dem_origin(req.lat, req.lon, bundle_dir=MP.bundle_for_site(req.site))
                except (KeyError, FileNotFoundError):
                    log.warning("site %r has no DEM bundle; using the flattest anchor", req.site)
                except ImportError:
                    log.warning("pyproj absent ([planner] extra); site lat/lon ignored, using flattest anchor")
                except ValueError as e:
                    return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
        else:
            dem, origin = None, (0.0, 0.0)
        dem = _as_built_dem(getattr(req, "site", "haworth"), dem, origin)   # #242: plan on the remembered surface
        # RB-03: compute the plan ONCE (incl. as-built validation + endurance); report/timeline/IR and the
        # validation/endurance fields are all VIEWS of this single result (no independent recompute).
        slope_cap = req.max_traverse_slope_deg          # operator slope budget -> routing traversability gate
        result = MP.plan(mission, dem=dem, dem_origin=origin, algorithm=req.algorithm,
                         objective=req.objective, vehicles=req.vehicles,
                         max_traverse_slope_deg=slope_cap, with_acceptance=True)
        # I10: hauls routed around hazards on the real DEM; I8 + I6/M11 slope-feasible siting.
        with report_lock:                              # serialize the thread-unsafe matplotlib report path
            pdf, md, totals = MP.run(mission, stem=_plan_stem(payload), dem=dem, dem_origin=origin,
                                     algorithm=req.algorithm, objective=req.objective,
                                     vehicles=req.vehicles, max_traverse_slope_deg=slope_cap, result=result)
        validation = result.validation                  # RB-03: from the one result, not a recompute
        timeline = MP.build_timeline(mission, dem=dem, dem_origin=origin, max_traverse_slope_deg=slope_cap,
                                     algorithm=req.algorithm, objective=req.objective, result=result)
        endurance = result.endurance
        autonomy, perception = _autonomy_perception(mission, dem, origin, req.algorithm, req.objective)
        plan_ir = MP.plan_ir(mission, dem=dem, dem_origin=origin,                # the machine-executable plan
                             algorithm=req.algorithm, objective=req.objective,
                             vehicles=req.vehicles, max_traverse_slope_deg=slope_cap, result=result)
        # H-07 follow-up: ORDERED IR-replay acceptance -- walk the trips in plan order through a bounded
        # drum so the order-dependent surface + drum-supply sequencing the pooled validate_plan flattens
        # are surfaced. Drop the per-cell as_built array from the API (keep the scalar verdict).
        ordered_acc = {k: v for k, v in
                       MP.execute_plan_acceptance(mission, result.trips, dem=dem, dem_origin=origin).items()
                       if k != "as_built"}
    except (ValueError, RuntimeError) as e:             # bad input / sinter-gated -> honest 400
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    except (KeyError, TypeError) as e:                  # missing/odd-typed field -> ALSO the contracted
        # 400 {ok:false,error} (audit M40: these surfaced as uncaught 500s)
        return JSONResponse(status_code=400, content={"ok": False, "error": f"bad request field: {e!r}"})
    # H-03: fail CLOSED at the product boundary. A plan with an unreachable mandatory leg (no safe routing
    # corridor) or a battery-infeasible transit must NOT hand a rover/ROS executive an executable action
    # list. Surface feasibility prominently (not buried in totals) and SUPPRESS the executable Plan IR.
    feasible = bool(totals.get("feasible", True))
    infeasible_reasons = list(totals.get("infeasible_reasons", []))
    if not feasible:
        plan_ir = {"executable": False, "feasible": False, "infeasible_reasons": infeasible_reasons,
                   "actions": [], "note": "execution IR suppressed (H-03): the plan has an infeasible "
                   "leg -- unreachable corridor or battery-infeasible transit"}
    # A-06: site/body/time are REQUIRED context -- the terrain provenance must reflect the ACTUAL site
    # and body the plan ran on, never a hardcoded `haworth_dem`. A non-Haworth lunar site reports its
    # own `<site>_dem`; a non-Moon body reports `<body>_flat` (no lunar DEM exists), so a Nobile or Mars
    # plan can never be displayed or reported with Haworth-derived provenance.
    site = getattr(req, "site", "haworth")
    body = mission.body
    if dem is not None:
        terrain_source = f"{site}_dem"                  # the real DEM the plan used (named by its site)
    elif body == "moon":
        terrain_source = "flat_fallback"                # Moon site DEM missing -> honest flat-check warning
    else:
        terrain_source = f"{body}_flat"                 # non-Moon body has no lunar DEM (flat by design)
    # FS-15: the typed PlanResult contract the cockpit consumes via adapters.js (the dashboard strip +
    # CONOPS line read this view model, not ad-hoc legacy `totals` keys). Built from the SAME totals so the
    # contract and the legacy dict never diverge; additive (legacy `totals` stays for un-migrated panes).
    from stewie.contracts import PlanResult
    plan_result = PlanResult(
        plan_id=(result.provenance.get("input_sha256") or "")[:16] or "plan",
        feasible=feasible, n_orders=len(mission.orders), vehicles=int(totals.get("vehicles", 1) or 1),
        makespan_s=float(totals.get("makespan_s", 0.0)), energy_j=float(totals.get("energy_J", 0.0)),
        mass_moved_kg=float(totals.get("cut_kg", 0.0)) + float(totals.get("fill_kg", 0.0)),
        blocked_legs=int(totals.get("blocked_legs", 0) or 0),
        recharges=int(totals.get("charges", 0) or 0), drum_cycles=int(totals.get("drum_cycles", 0) or 0),
        cut_passes=int(totals.get("cut_passes", 1) or 1),
        resolved_algorithm=str(totals.get("resolved_algorithm") or totals.get("algorithm") or "")).model_dump()
    return {
        "ok": True,
        "feasible": feasible,                           # H-03: surfaced at the top, not buried in totals
        "infeasible_reasons": infeasible_reasons,
        "plan_result": plan_result,                     # FS-15: the typed contract the cockpit view model reads
        "mode": "DEM_KNOWN_POSE_MISSION_SIM",           # product boundary (known-pose mission sim, not SLAM)
        # A-06: site/body context echoed so the UI/report can verify the terrain basis and warn on a
        # mismatch. item 4: NEVER silently degrade to flat -- terrain_source names the ACTUAL terrain used.
        "site": site,
        "body": body,
        "terrain_source": terrain_source,
        "pdf": "/reports/" + os.path.basename(pdf),
        "md": "/reports/" + os.path.basename(md),
        "totals": _totals_json(totals),
        "validation": validation,
        "timeline": timeline,
        "endurance": endurance,
        "autonomy": autonomy,
        "perception": perception,
        "plan_ir": plan_ir,                             # versioned typed-action plan a rover/ROS executive runs
        "ordered_acceptance": ordered_acc,              # H-07: ordered IR-replay verdict (drum sequencing + as-built)
        "provenance": result.provenance,                # RB-03/CT-07: schema, mode, config, input hash of THE plan
    }
