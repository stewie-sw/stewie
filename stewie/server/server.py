#!/usr/bin/env python3
"""server.py -- ASGI server for the planet browser + mission planner (PRD N7/N8).

FastAPI/uvicorn. Serves the static front-end (index.html, bodies.json), the generated reports, and the
JSON API the browser drives: POST /plan, /sense, /structure, /compare, /render. Production hardening:
Pydantic request models (typed contract + input limits), optional API-key auth on the mutating routes,
CORS, a thread-safe (locked) matplotlib report path, a reports/ TTL sweep, structured access logging
(PRD N10), and /healthz + /metrics.

    python -m planet_browser.server [--port 8770] [--host 0.0.0.0]    # or the `dustgym-serve` entry point

Env knobs (PRD N15 overlay style): DUSTGYM_API_KEY (auth on POST when set), DUSTGYM_CORS_ORIGINS
(comma-list or *), DUSTGYM_REPORTS_TTL_S (report retention, default 86400), DUSTGYM_LOG_LEVEL.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import sys
import threading
import time

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from stewie.specs import config as CFG               # PO-02: configurable application-data dirs
from stewie.twin.io_fields import atomic_write_bytes  # PO-02/CT-04: atomic writes for profiles
from lode import adaptive_planner as ADP
from lode import autonomy as AUT
from stewie.server import map_layers as MLY
from lode import mission_planner as MP
from leap import structures as ST
from dart import articulated_parallax as AP   # P1.1: SN-10 articulation-parallax relocalization
from dart import pose_graph_se2 as PG         # the live SE(2) estimator the fix is injected into
from dart import integrated_slam as ISLAM     # P1.2: the integrated multi-factor SLAM run + LOO

# PRD N10: structured logging + observability. Used for access logs, startup, and the additive
# failure paths. Level via $DUSTGYM_LOG_LEVEL.
log = logging.getLogger("stewie.server")

def _env(name: str, default=None):
    """STEWIE_<name> with DUSTGYM_<name> fallback (rename 2026-06-10; legacy accepted one cycle)."""
    return os.environ.get(f"STEWIE_{name}", os.environ.get(f"DUSTGYM_{name}", default))


_START = time.monotonic()
_REPORT_LOCK = threading.Lock()                 # matplotlib pyplot is process-global + thread-unsafe
_METRICS: dict = {"requests_total": 0, "by_status": {}, "by_route": {}}
_METRICS_LOCK = threading.Lock()   # RC-04: serialize the metrics read-modify-write


def _configure_logging(level: str | None = None) -> None:
    """Configure logging for the server (PRD N10): level from arg, else $DUSTGYM_LOG_LEVEL, else INFO."""
    lvl = (level or _env("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(level=getattr(logging, lvl, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


# plan_render_pipeline lives in scripts/ (it drives the Godot sidecar); MP already put the repo root on the
# path. Importing it is optional -- /render degrades to a 503 if the binary is absent.
sys.path.insert(0, os.path.join(MP._REPO_ROOT, "scripts"))
try:
    import plan_render_pipeline as PRP
except Exception as _prp_exc:   # noqa: BLE001 -- /render just becomes unavailable
    PRP = None
    log.info("render pipeline unavailable (Godot sidecar import failed: %r); /render -> 503", _prp_exc)
_HAWORTH = os.path.join(MP._REPO_ROOT, "samples", "lunar_dem", "haworth_10km_5m")

HERE = os.path.dirname(os.path.abspath(__file__))
# PO-02/RB-06: reports + profiles live in the configurable application-data dir ($DUSTGYM_DATA_DIR,
# else ~/.local/share/dustgym) -- NOT inside the (possibly read-only) installed package. Tests
# monkeypatch these module-level vars to a tmp dir; run() writes reports to the same CFG.reports_dir().
REPORTS = CFG.reports_dir()
PROFILES = CFG.profiles_dir()                      # saved planning profiles (config snapshots), like reports/

_CTYPE = {".html": "text/html; charset=utf-8", ".json": "application/json",
          ".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8",
          ".js": "text/javascript", ".css": "text/css", ".png": "image/png"}

_MAX_ORDERS = 1000   # N8 input limit: refuse absurd build queues before they reach the planner
_MAX_BODY_BYTES = int(_env("MAX_BODY_BYTES", 4 * 1024 * 1024))   # N8: request-body size cap (4 MiB)


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("stewie")    # the dist renamed (was dustgym; the old lookup always fell back to 0.1.0)
    except Exception:   # noqa: BLE001 -- not installed (editable/source run)
        return "0.1.0"


def _prune_reports(ttl_s: float | None = None) -> int:
    """Delete report files older than the TTL (default $DUSTGYM_REPORTS_TTL_S or 86400 s). Returns count."""
    ttl = float(ttl_s if ttl_s is not None else _env("REPORTS_TTL_S", 86400))
    if ttl <= 0 or not os.path.isdir(REPORTS):
        return 0
    now, removed = time.time(), 0
    for n in os.listdir(REPORTS):
        p = os.path.join(REPORTS, n)
        try:
            if os.path.isfile(p) and now - os.path.getmtime(p) > ttl:
                os.remove(p)
                removed += 1
        except OSError:
            pass
    return removed


def _totals_json(totals):
    """JSON-safe totals: numbers -> float, but pass through bools/strings (algorithm/objective) and already
    JSON-safe containers (e.g. vehicles_detail = a list of per-vehicle dicts) + None unchanged."""
    out = {}
    for k, v in totals.items():
        out[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    return out


_MOON_DEM = None   # (dem, flattest-anchor); loaded once, reused across /plan requests


_SITE_DEMS: dict = {}


def _moon_dem(site: str = "haworth"):
    """Load the real DEM for ``site`` (REG-01: any imported site, not just Haworth) + its
    auto-selected flattest buildable anchor, cached PER SITE so Moon plans get live slope-gating on
    the chosen terrain. Degrades to (None, (0,0)) -> flat check if the bundle is absent."""
    global _MOON_DEM
    if site in _SITE_DEMS:
        return _SITE_DEMS[site]
    try:
        dem = MP.load_site_dem(site)
        out = (dem, MP.flattest_anchor(dem))
    except Exception as e:   # noqa: BLE001 -- degrade to flat-check, but surface it
        log.warning("DEM for site %r unavailable; falling back to flat slope-check: %r", site, e)
        out = (None, (0.0, 0.0))
    _SITE_DEMS[site] = out
    if site == "haworth":
        _MOON_DEM = out
    return out


def _autonomy_perception(mission, dem, origin, algorithm, objective):
    """Fold the closed-loop autonomy + the AutoNav estimation (perception) uncertainty into /plan.

    Runs the conserved-model closed loop (plan -> execute -> estimate -> replan) once. The `autonomy`
    block summarizes the controller (recharges/replans/completion + the true-vs-budgeted energy the slip
    truth forces); the `perception` block is the rover's onboard ESTIMATE confidence (pose sigma grows by
    dead-reckoning, drum-fill sigma from the FDC mass-inference model, energy sigma from model error).
    Additive: any failure returns (None, None) so the report still goes out."""
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
        "note": ("perception-in-the-loop: a map/landmark pose fix per leg bounds dead-reckoning drift; the "
                 "dig-ready gate observes more before digging when the pose is uncertain OR the dig site's "
                 "local map coverage is low. map_coverage is the onboard-observability tier (what the route "
                 "sees) -- the dense observed-map RMSE is the gated render/COLMAP tier (see /render)."),
    }
    return autonomy, perception


def _plan_stem(payload):
    """Stable, collision-free report stem from the mission (name slug + content hash) -- repeatable,
    no wall-clock, so the same queue regenerates the same file instead of piling up duplicates."""
    import json
    import re
    name = re.sub(r"[^a-z0-9]+", "-", str(payload.get("name", "mission")).lower()).strip("-") or "mission"
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:8]
    return f"{name}-{digest}"


# --------------------------------------------------------------------------------------------------
# Request models (PRD N8: the typed API contract + input limits). extra="allow" passes through the
# optional per-kind order fields the planner reads; the limits below cap obviously-abusive inputs.
# --------------------------------------------------------------------------------------------------
class Order(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str | None = Field(default=None, max_length=120)
    kind: str | None = Field(default=None, max_length=40)
    x: float = 0.0
    y: float = 0.0
    footprint_m2: float = Field(default=1.0, gt=0, le=1e8)
    depth_m: float = Field(default=0.0, ge=-100.0, le=100.0)


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


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(default="mission", max_length=200)
    body: str = Field(default="moon", max_length=40)
    orders: list[Order] = Field(default_factory=list, max_length=_MAX_ORDERS)
    objective: str = Field(default="time", max_length=40)


class SenseRequest(BaseModel):
    true_mass_kg: float = Field(ge=0.0, le=1e5)
    capacity_kg: float | None = Field(default=None, gt=0.0, le=1e5)
    noise_frac: float = Field(default=0.0, ge=0.0, le=1.0)
    seed: int = Field(default=0, ge=0)


class StructureRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str | None = Field(default=None, max_length=80)
    x: float = 0.0
    y: float = 0.0
    params: dict = Field(default_factory=dict)


class RenderRequest(BaseModel):
    u: float = Field(default=0.5, ge=0.0, le=1.0)
    v: float = Field(default=0.5, ge=0.0, le=1.0)
    pad_frac: float = Field(default=0.5, gt=0.0, le=1.0)
    mission_t_s: float | None = None   # T6.3: render under the planner's mission-time sun


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)      # saved under a slug of this name
    profile: dict = Field(default_factory=dict)         # the full config snapshot (body/soil/fleet/orders/...)


class LocalizeRequest(BaseModel):
    # I3: the estimator surface is observation-only -- forbid extra keys so no truth/hidden-state field
    # (true_pose, slip, terrain truth) can ride in on the request and silently enter the estimator.
    model_config = ConfigDict(extra="forbid")
    landmarks_xy: list[tuple[float, float]] = Field(max_length=256)   # known shadow-tip landmark (x,y)
    pixel_shifts: list[float] = Field(max_length=256)                # vertical parallax shift per landmark (px)
    dh_m: float = Field(gt=0.0, le=10.0)                # commanded chassis lift (m) -- the parallax baseline
    fx_px: float = Field(gt=0.0, le=1e5)                # camera focal length (px)
    sigma_px: float = Field(default=0.3, gt=0.0, le=100.0)           # measured shadow-edge pixel noise
    prior_xy: tuple[float, float] = (0.0, 0.0)          # current dead-reckoned pose guess
    prior_yaw: float = Field(default=0.0, ge=-7.0, le=7.0)
    prior_sigma_xy: float = Field(default=50.0, gt=0.0, le=1e6)      # weak by default -> the fix dominates
    prior_sigma_yaw: float = Field(default=1.0, gt=0.0, le=1e3)


class SlamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")          # I3: observation/config only -- no truth injection
    # pattern-validated -> the segment name cannot path-traverse out of the dataset root
    segment: str = Field(default="Part1", pattern=r"^Part[1-9][0-9]?$", max_length=12)
    n_keyframes: int = Field(default=30, ge=5, le=200)
    seed: int = Field(default=0, ge=0, le=10000)


class SlamCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    segment: str = Field(default="Part1", pattern=r"^Part[1-9][0-9]?$", max_length=12)
    n_keyframes: int = Field(default=30, ge=5, le=200)
    n_seeds: int = Field(default=12, ge=1, le=100)


class LocalizeRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera: str = Field(default="front_left", pattern=r"^[a-z_]+$", max_length=32)
    drift_m: float = Field(default=1.41, gt=0.0, le=50.0)


class ParallaxPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: str = Field(default="crater_boulders", pattern=r"^[A-Za-z0-9_\-]+$", max_length=64)
    sun_az_deg: float = Field(ge=0.0, le=360.0)
    sun_el_deg: float = Field(ge=0.0, le=90.0)
    posture_from: str = Field(default="TRANSIT", pattern=r"^[A-Z_]+$", max_length=32)
    posture_to: str = Field(default="MEERKAT", pattern=r"^[A-Z_]+$", max_length=32)
    size: str = Field(default="1024x768", pattern=r"^\d{2,5}x\d{2,5}$", max_length=12)


def _truthy(v) -> bool:
    return bool(v) and str(v).strip().lower() in ("1", "true", "yes", "on")


def _is_loopback(request: Request) -> bool:
    """True for an in-process (ASGI TestClient) or loopback client. dev-open is permitted only here,
    so a STEWIE_DEV_OPEN flag accidentally left on in a (proxied) deployment still cannot be used by a
    remote client -- the backend behind nginx sees the proxy's container IP, not loopback."""
    c = getattr(request, "client", None)
    if c is None:
        return True
    return c.host in ("127.0.0.1", "::1", "localhost", "testclient")


def require_auth(request: Request,
                 x_api_key: str | None = Header(default=None, alias="X-API-Key"),
                 authorization: str | None = Header(default=None),
                 tailscale_user_login: str | None = Header(default=None,
                                                           alias="Tailscale-User-Login")) -> str:
    """N8 + #52 + audit C-01: identity-bearing auth on mutating routes, FAIL CLOSED.
    Accepted, in order: a WHITELISTED Tailscale identity (opt-in via STEWIE_TRUST_TAILSCALE=1
    behind `tailscale serve`), an HMAC session token from /auth/login (Bearer), or the raw API
    key (automation; identity "api-key"). When NO key is configured the route is LOCKED (503)
    unless STEWIE_DEV_OPEN is explicitly set AND the client is loopback/in-process -- a keyless
    deployment is no longer silently director-open. Returns the operator identity."""
    from stewie.server import auth as AUTH
    key = _env("API_KEY")
    if not key:
        if _truthy(_env("DEV_OPEN")) and _is_loopback(request):
            return "dev-open"
        raise HTTPException(status_code=503, detail=(
            "auth not configured: set STEWIE_API_KEY for authenticated access, or STEWIE_DEV_OPEN=1 "
            "on a loopback-only dev server. Privileged routes are locked (fail-closed)."))
    ts = AUTH.tailscale_identity({"tailscale-user-login": tailscale_user_login or ""})
    if ts:
        return ts
    supplied = x_api_key or (authorization or "").removeprefix("Bearer ").strip()
    op = AUTH.verify_token(supplied)
    if op:
        return op
    if hmac.compare_digest(supplied.encode(), key.encode()):   # constant-time -> no timing oracle
        return "api-key"
    raise HTTPException(status_code=401, detail="invalid or missing API key")


def require_director(identity: str = Depends(require_auth)) -> str:
    """#68 [REQ:PO-04]: the truth/training surface is director-only."""
    from stewie.server import auth as AUTH
    if AUTH.role_of(identity) != "director":
        raise HTTPException(status_code=403,
                            detail=f"director role required (signed in as operator {identity!r})")
    return identity


app = FastAPI(title="STEWIE — mission planner + planet browser API", version=_version())

_cors = _env("CORS_ORIGINS", "*").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def _access_log(request: Request, call_next):
    t0 = time.monotonic()
    # N8: reject oversized bodies up front (Content-Length guard) before they reach a handler.
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            clen = int(request.headers.get("content-length") or 0)
        except ValueError:
            clen = 0
        if clen > _MAX_BODY_BYTES:
            return JSONResponse(status_code=413,
                                content={"ok": False, "error": f"request body too large (> {_MAX_BODY_BYTES} bytes)"})
        # SEC-3: the header is client-supplied; enforce the ACTUAL byte count too (Starlette caches
        # the body, so the handler re-reads this same copy -- no double-read).
        body = await request.body()
        if len(body) > _MAX_BODY_BYTES:
            return JSONResponse(status_code=413,
                                content={"ok": False, "error": f"request body too large (> {_MAX_BODY_BYTES} bytes)"})
    response = await call_next(request)
    dt = (time.monotonic() - t0) * 1000.0
    raw = request.url.path
    # key the by_route metric on the MATCHED ROUTE TEMPLATE (e.g. /figure/{key}), not the raw client path:
    # the raw path is attacker-controlled, so an unbounded dict would be a memory-DoS. Templates are finite.
    matched = request.scope.get("route")
    route_key = getattr(matched, "path", "unmatched")
    sk = str(response.status_code)
    with _METRICS_LOCK:                                  # RC-04: atomic counter update under the threadpool
        _METRICS["requests_total"] += 1
        _METRICS["by_status"][sk] = _METRICS["by_status"].get(sk, 0) + 1
        _METRICS["by_route"][route_key] = _METRICS["by_route"].get(route_key, 0) + 1
    log.info('%s "%s %s" %s %.1fms',
             request.client.host if request.client else "-", request.method, raw, response.status_code, dt)
    return response


@app.exception_handler(RequestValidationError)
async def _on_validation_error(request: Request, exc: RequestValidationError):
    """Surface Pydantic validation failures in the {ok:false,error} envelope at 400 (not FastAPI's 422
    default), preserving the API contract. Malformed JSON is reported as 'bad JSON'."""
    errs = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errs):
        return JSONResponse(status_code=400, content={"ok": False, "error": f"bad JSON: {errs[0].get('msg', '')}"})
    msg = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:]) or e['loc'][-1]}: {e['msg']}" for e in errs[:3])
    return JSONResponse(status_code=400, content={"ok": False, "error": msg or "invalid request"})


@app.exception_handler(StarletteHTTPException)
async def _on_http_exc(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.detail})


# ---- GET: static front-end + generated reports + DEM previews + ops ------------------------------
@app.get("/")
@app.get("/index.html")
def get_index():
    return FileResponse(os.path.join(HERE, "index.html"), media_type=_CTYPE[".html"])


# ---- S-4: the object store (catalog) ---------------------------------------------------------
from stewie.server import objects as OBJ               # noqa: E402


# ---- #39: the event history (who did what when; actor = the #52 auth identity) ----------------
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


@app.get("/events")
def get_events(n: int = 50, _auth: str = Depends(require_director)):
    """The newest-first event history (who did what when). SEC-2: director-only -- it carries
    operator identities + the full mutation trail (an audit surface, not public)."""
    import json as _json

    from stewie.specs import config as CFG
    path = os.path.join(CFG.data_dir(), "events.jsonl")
    out: list = []
    if os.path.exists(path):
        lines = open(path).read().splitlines()[-max(1, min(int(n), 500)):]
        for ln in reversed(lines):
            try:
                out.append(_json.loads(ln))
            except ValueError:
                continue
    return {"ok": True, "events": out}


# ---- #32: no-terminal admin ops (the W-2/W-3 CLIs + gate validation as buttons) ---------------
@app.post("/admin/twin/snapshot")
def admin_snapshot(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    path = BK.snapshot(_twin(), os.path.join(CFG.data_dir(), "snapshots"))
    return {"ok": True, "snapshot": path}


@app.post("/admin/twin/retention")
def admin_retention(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    removed = BK.apply_retention(os.path.join(CFG.data_dir(), "snapshots"))
    return {"ok": True, "removed": removed}


@app.post("/admin/backup/replicate")
def admin_replicate(_auth: str = Depends(require_director)):
    from stewie.specs import config as CFG
    from stewie.twin import backup as BK
    dest = os.environ.get("STEWIE_BACKUP_DIR", os.path.join(CFG.data_dir(), "replica"))
    out = BK.replicate(CFG.data_dir(), dest)
    return {"ok": True, **out}


@app.post("/admin/gates/validate")
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


@app.get("/twin/cg")
def twin_cg(front_deg: float = 0.0, back_deg: float = 0.0, front_kg: float = 0.0,
            back_kg: float = 0.0, pitch_deg: float = 0.0, roll_deg: float = 0.0):
    """#25: the live center-of-gravity + tip margin -- posture (arm angles) + drum LOADS through
    ArmState.cg_offset_m (the loads enter AT the drums) and the SSA stability model."""
    from stewie.physics.stability import stability as STAB
    from stewie.specs.arm_state import ArmState
    # F2 (data-book audit): THREE conflicting geometry triplets existed. The registry is the ONE
    # source (per-vehicle, Aaron's directive): geometry_of("ipex") = gauge 0.3645 [WHEELTEST Eq.1
    # 0.5207 test-platform track x the 0.7 IPEx scale, per ipex_specs' own comment] / wheelbase
    # 0.30 / CG 0.21. This CORRECTS the #59 change, which over-read 0.5207 as IPEx's own track.
    from stewie.specs.vehicles import geometry_of
    arm = ArmState()
    arm.front_deg = max(-110.0, min(110.0, float(front_deg)))   # instantaneous pose (no rate sim here)
    arm.back_deg = max(-110.0, min(110.0, float(back_deg)))
    dx, dz = arm.cg_offset_m(front_drum_kg=max(0.0, front_kg), back_drum_kg=max(0.0, back_kg))
    geo = geometry_of("ipex")
    st = STAB(float(pitch_deg), float(roll_deg), gauge_m=geo["gauge_m"],
              wheelbase_m=geo["wheelbase_m"], cg_height_m=geo["cg_height_m"] + dz, cg_dx_m=dx)  # VT4-01: dx now bites
    return {"ok": True, "cg_dx_m": round(dx, 4), "cg_dz_m": round(dz, 4),
            "cg_height_m": round(geo["cg_height_m"] + dz, 4), **{k: (round(v, 3) if isinstance(v, float) else v)
                                                          for k, v in st.items()}}


@app.get("/auth/config")
def auth_config():
    return {"ok": True, "operator_login": os.environ.get("STEWIE_OPERATOR_LOGIN", "1") != "0"}


# --- #66 + SF-01: the pluggable RC seam (one process-wide sim backend + its watchdog) -----------
from stewie.bridge import rc_contract as RC          # noqa: E402
_RC_BACKEND = RC.SimBackend(start_rc=(0.0, 0.0))
_RC_WATCHDOG = RC.SafingWatchdog(_RC_BACKEND, deadline_s=float(os.environ.get("STEWIE_RC_DEADLINE_S", "5")))
import threading as _rcthreading                     # noqa: E402
import time as _time                                  # noqa: E402
_RC_LOCK = _rcthreading.Lock()


@app.post("/plan/commands")
def plan_commands(req: PlanRequest):
    """#66 (Aaron: "plan should output cmds for reuse"): the plan as a REUSABLE RC command tape --
    a GoTo sequence (the same contract the sim/pit backend executes). Plan once, command many."""
    mission = MP.mission_from_dict(req.model_dump())
    cell = 5.0 if mission.body == "moon" else 1.0
    dem, origin = _moon_dem(getattr(req, "site", "haworth")) if mission.body == "moon" else (None, (0.0, 0.0))
    cmds = RC.commands_from_plan(mission, cell_m=cell, dem=dem, dem_origin=origin)
    return {"ok": True, "cell_m": cell, "commands": [
        {"kind": c.kind, "leg_id": c.leg_id, "goal_row": c.goal_row, "goal_col": c.goal_col,
         "v_max_mps": c.v_max_mps, "goal_radius_cells": c.goal_radius_cells} for c in cmds]}


@app.post("/rc/command")
def rc_command(body: dict, identity: str = Depends(require_auth)):
    """#66: submit an RC command (GoTo/Safe/SetSim) to the active backend through the SF-01
    watchdog. SetSim (a training time-warp) is DIRECTOR-only; GoTo/Safe are open to any operator."""
    from stewie.server import auth as AUTH
    kind = str(body.get("kind", "")).lower()
    now = _time.monotonic()
    with _RC_LOCK:
        cmd: object
        if kind == "goto":
            cmd = RC.GoTo(leg_id=int(body.get("leg_id", 0)), goal_row=float(body["goal_row"]),
                          goal_col=float(body["goal_col"]), v_max_mps=float(body.get("v_max_mps", 0.3)),
                          goal_radius_cells=float(body.get("goal_radius_cells", 1.0)))
        elif kind == "safe":
            cmd = RC.Safe(reason=RC.SAFE_REASON_OPERATOR)
        elif kind == "setsim":
            if AUTH.role_of(identity) != "director":
                raise HTTPException(status_code=403, detail="SetSim (time-warp) is director-only")
            cmd = RC.SetSim(time_factor=float(body.get("time_factor", 1.0)))
        else:
            raise HTTPException(status_code=400, detail=f"unknown RC command kind {kind!r}")
        _RC_WATCHDOG.submit(cmd, now=now)
        log_event(identity, f"rc.{kind}", str(body.get("leg_id", "")))
    return {"ok": True, "accepted": kind, "watchdog_tripped": _RC_WATCHDOG.tripped}


@app.get("/rc/telemetry")
def rc_telemetry(_auth: None = Depends(require_auth)):
    """#66: drain the backend telemetry (Pose/Leg) + the SF-01 watchdog state. The watchdog ticks
    on every poll, so a stalled operator (no commands) auto-SAFEs within the deadline."""
    now = _time.monotonic()
    with _RC_LOCK:
        tripped = _RC_WATCHDOG.tick(now=now)
        tlm = [t.__dict__ | {"kind": t.kind} for t in _RC_BACKEND.poll()]
    return {"ok": True, "telemetry": tlm, "watchdog": {"tripped": tripped,
            "deadline_s": _RC_WATCHDOG.deadline_s}}


@app.post("/plan/math")
def plan_math_endpoint(req: PlanRequest):
    """#74: the per-trip MATH WORKSHEET for review (every equation + substituted numbers). Open
    (read-only derivation of a plan the caller already authored)."""
    payload = req.model_dump()
    mission = MP.mission_from_dict(payload)
    dem, origin = _moon_dem(getattr(req, "site", "haworth")) if mission.body == "moon" else (None, (0.0, 0.0))
    return {"ok": True, **MP.plan_math(mission, dem=dem, dem_origin=origin)}


@app.post("/resync/compare")
def resync_compare(body: dict, _auth: str = Depends(require_director)):
    """#70: faster-than-realtime forward comparison -- candidate solver inputs re-simulated from
    the CURRENT mission; ranked outcomes with measured wall times. Director-side (it sees truth)."""
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


@app.post("/auth/login")
def auth_login(body: dict, _auth: str = Depends(require_auth)):
    """#52: email + the API key -> a 12 h identity token. The email MUST be whitelisted.
    STEWIE_OPERATOR_LOGIN=0 disables the flow (key-only deployments; Aaron 2026-06-10)."""
    from stewie.server import auth as AUTH
    if os.environ.get("STEWIE_OPERATOR_LOGIN", "1") == "0":
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "operator login is disabled "
                                     "(STEWIE_OPERATOR_LOGIN=0); use the API key"})
    email = str(body.get("email", "")).strip().lower()
    if not AUTH.is_allowed(email):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": f"{email!r} is not a whitelisted operator"})
    return {"ok": True, "operator": email, "token": AUTH.issue_token(email),
            "ttl_s": AUTH.TOKEN_TTL_S}


@app.post("/missions/{name}")
def mission_save(name: str, doc: dict, _auth: str = Depends(require_auth)):
    try:
        out = OBJ.save_mission(name, doc)
        log_event(_auth, "mission.save", out["name"])
        return {"ok": True, **out}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/missions")
def mission_list():
    return {"ok": True, "missions": OBJ.list_missions()}


@app.get("/missions/{name}")
def mission_load(name: str):
    d = OBJ.load_mission(name)
    if d is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no mission {name!r}"})
    return {"ok": True, "doc": d}


@app.delete("/missions/{name}")
def mission_delete(name: str, _auth: str = Depends(require_auth)):
    ok = OBJ.delete_mission(name)
    log_event(_auth, "mission.delete", name)
    return {"ok": ok}


@app.post("/structures/custom/{name}")
def structure_save(name: str, doc: dict, _auth: str = Depends(require_auth)):
    try:
        out = OBJ.save_structure(name, doc)
        log_event(_auth, "structure.save", out["name"])
        return {"ok": True, **out}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/structures/custom")
def structure_list():
    return {"ok": True, "structures": OBJ.list_structures()}


@app.get("/structures/custom/{name}/expand")
def structure_expand(name: str, x: float, y: float):
    orders = OBJ.expand_structure(name, x, y)
    if orders is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no structure {name!r}"})
    return {"ok": True, "orders": orders}


@app.delete("/structures/custom/{name}")
def structure_delete(name: str, _auth: str = Depends(require_auth)):
    ok = OBJ.delete_structure(name)
    log_event(_auth, "structure.delete", name)
    return {"ok": ok}


@app.on_event("startup")
def _warm_globe_cache():
    """Background-warm the heavy globe products (PSR's sweep measured 44 s cold) so the first
    user click finds them ready; errors are non-fatal (no DEM in some deployments)."""
    import threading

    # C-01: announce the auth posture at boot so a fail-open deployment can't pass unnoticed.
    if _env("API_KEY"):
        log.info("auth: API key configured -- privileged routes require it")
    elif _truthy(_env("DEV_OPEN")):
        log.warning("auth: NO API key; STEWIE_DEV_OPEN set -> dev-open for LOOPBACK clients only "
                    "(never set this in a deployment)")
    else:
        log.critical("auth: NO API key and STEWIE_DEV_OPEN unset -> privileged routes are LOCKED "
                     "(fail-closed). Set STEWIE_API_KEY to enable authenticated access.")

    def warm():
        try:
            from stewie.server.gis_layers import render_globe
            for kind in ("dem", "slope", "hazard", "illumination", "psr"):
                render_globe(kind)
        except Exception:
            pass

    threading.Thread(target=warm, daemon=True).start()


@app.get("/layers/legend")
def layers_legend():
    """Legend values FROM THE PHYSICS (audit P1): hazard thresholds are the hazard-map defaults
    (doc-true 20/15 + the 7.5 cm obstacle), the slope ramp is the renderer's real mapping, the
    shadow legend carries the live solar authority -- the UI never hardcodes a threshold."""
    import inspect

    from dart.hazard_map import build_hazard_map
    from stewie.specs.ipex_specs import OBSTACLE_HEIGHT_M
    sig = inspect.signature(build_hazard_map)
    return {
        "ok": True,
        "slope": {"max_deg": 30.0, "ramp": "green 0° → red 30° (opacity rises with steepness)"},
        "hazard": {"nogo_deg": sig.parameters["max_slope_deg"].default,
                   "penalty_deg": sig.parameters["slope_hazard_deg"].default,
                   "obstacle_m": OBSTACLE_HEIGHT_M,
                   "text": "red = no-go (> tested slope limit or rock above the obstacle envelope); "
                           "amber = penalty (> nominal slope)"},
        "illumination": {"sun": "horizon-clipped shadow at the mission-time sun (SPICE)",
                         "text": "blue = shadowed at the selected time"},
        "psr": {"sweep": "never lit across a 0–330° azimuth sweep at 3° elevation",
                "text": "violet = permanently shadowed region (PSR) candidate -- never sunlit; "
                        "the cold traps where water ice survives"},
        "dem": {"text": "cartographic hillshade (315°/45°) from the raw 5 m heightmap"},
    }


@app.get("/layers/globe/{kind}.png")
def globe_layer_png(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                    mission_t_s: float | None = None, color: str = "39ff14"):
    """The GEOGRAPHIC drape (server-reprojected; Aaron's rotated-tile screenshot fix)."""
    from stewie.server.gis_layers import _to_png, render_globe
    if mission_t_s is not None:
        from stewie.specs.solar import sun_az_el
        sun_az, sun_el = sun_az_el(-87.45, float(mission_t_s))
    try:
        out = render_globe(kind, sun_el=sun_el, sun_az=sun_az, grid_color=color[:7])
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM absent: {e}"})
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    from fastapi.responses import Response
    return Response(content=_to_png(out[0]), media_type="image/png")


@app.get("/layers/globe/{kind}/bbox")
def globe_layer_bbox(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                     mission_t_s: float | None = None):
    from stewie.server.gis_layers import render_globe
    if mission_t_s is not None:
        from stewie.specs.solar import sun_az_el
        sun_az, sun_el = sun_az_el(-87.45, float(mission_t_s))
    out = render_globe(kind, sun_el=sun_el, sun_az=sun_az)
    if out is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    return {"ok": True, **out[1]}


@app.get("/sites")
def sites_list():
    """#49: the site registry (Haworth imported; Artemis III candidates honest about data state)."""
    from stewie.specs.sites import site_rows
    return {"ok": True, "sites": site_rows()}


@app.get("/dem/georef")
def dem_georef():
    """The Haworth tile's globe footprint (selenographic corners) for the cockpit overlay."""
    try:
        return {"ok": True, **MP.dem_georef_corners()}
    except (ImportError, FileNotFoundError, ValueError) as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(e)})


@app.get("/dem/site_xy")
def dem_site_xy(lat: float, lon: float):
    """Selenographic lat/lon -> the Haworth site frame (x, y) [m] (the cursor-meters readout)."""
    try:
        x, y = MP.latlon_to_dem_origin(lat, lon)
    except ValueError as e:
        return JSONResponse(status_code=422, content={"ok": False, "error": str(e)})
    except ImportError as e:
        return JSONResponse(status_code=503, content={"ok": False, "error": f"pyproj absent: {e}"})
    return {"ok": True, "x_m": round(x, 1), "y_m": round(y, 1)}


@app.get("/fonts/{name}")
def get_font(name: str):
    """Vendored brand fonts (Orbitron, OFL -- license shipped alongside). No CDN at runtime."""
    safe = os.path.basename(name)
    path = os.path.join(HERE, "fonts", safe)
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no font {safe}"})
    return FileResponse(path, media_type="font/ttf" if safe.endswith(".ttf") else "text/plain")


@app.get("/icons/{name}")
def get_icon(name: str):
    """The app-icon set (cropped from the brand board's 1024 tile)."""
    safe = os.path.basename(name)
    path = os.path.join(HERE, "icons", safe)
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no icon {safe}"})
    return FileResponse(path, media_type="image/png")


@app.get("/bodies.json")
def get_bodies():
    p = os.path.join(HERE, "bodies.json")
    if not os.path.isfile(p):
        return JSONResponse(status_code=404, content={"ok": False, "error": "not found: bodies.json"})
    return FileResponse(p, media_type=_CTYPE[".json"])


@app.get("/reports/{name}")
def get_report(name: str):
    safe = os.path.basename(name)                       # basename only -> no path traversal
    p = os.path.join(REPORTS, safe)
    if not os.path.isfile(p):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"not found: {safe}"})
    ext = os.path.splitext(safe)[1]
    return FileResponse(p, media_type=_CTYPE.get(ext, "application/octet-stream"))


@app.get("/dem/{name}")
def get_dem(name: str):                                 # the real LOLA work-area DEM previews (Haworth)
    bundle = os.path.join(HERE, "..", "..", "samples", "lunar_dem", "haworth_10km_5m")
    f = {"hillshade.png": "preview_hillshade.png", "height.png": "preview_height.png"}.get(os.path.basename(name))
    if not f:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no dem {os.path.basename(name)}"})
    path = os.path.join(bundle, f)
    if not os.path.isfile(path):                        # bundle absent (e.g. a wheel install) -> 404, not a 500
        return JSONResponse(status_code=404, content={"ok": False, "error": f"dem preview not available: {f}"})
    return FileResponse(path, media_type="image/png")


# ---- engineer/developer/intern panes: validation figures + runtime config (served from source) ---
_VALIDATION = os.path.join(MP._REPO_ROOT, "validation")


def _validation_figures() -> dict:
    """Map 'category/file.png' -> absolute path for every PNG under validation/. Served from the source
    tree (empty if absent, e.g. a wheel install). The returned keys are the allowlist -> traversal-proof."""
    out: dict = {}
    if not os.path.isdir(_VALIDATION):
        return out
    for root, _dirs, files in os.walk(_VALIDATION):
        for fn in sorted(files):
            if fn.endswith(".png"):
                rel = os.path.relpath(os.path.join(root, fn), _VALIDATION).replace(os.sep, "/")
                out[rel] = os.path.join(root, fn)
    return out


@app.get("/figures")
def get_figures():
    """List the validation figures (engineer pane). key = 'category/file.png'; fetch via /figure/{key}."""
    figs = _validation_figures()
    return {"ok": True, "figures": [{"key": k, "category": k.split("/")[0], "url": "/figure/" + k}
                                    for k in sorted(figs)]}


@app.get("/figure/{key:path}")
def get_figure(key: str):
    """Serve a validation PNG by allowlisted key (only the keys /figures lists -> no path traversal)."""
    p = _validation_figures().get(key)
    if not p:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no figure {key}"})
    return FileResponse(p, media_type="image/png")


def _sample_missions() -> dict:
    """{name -> path} for the bundled intern sample missions (planet_browser/sample_missions/*.json)."""
    import glob
    d = os.path.join(HERE, "sample_missions")
    return {os.path.splitext(os.path.basename(p))[0]: p for p in sorted(glob.glob(os.path.join(d, "*.json")))}


@app.get("/sample_missions")
def get_sample_missions():
    """List the bundled intern sample missions; load one (into the build queue) via /sample_mission/{name}."""
    return {"ok": True, "samples": [{"name": n, "url": "/sample_mission/" + n} for n in _sample_missions()]}


@app.get("/sample_mission/{name}")
def get_sample_mission(name: str):
    """Serve a bundled sample mission by allowlisted name (only the names /sample_missions lists)."""
    p = _sample_missions().get(name)
    if not p:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no sample mission {name}"})
    with open(p) as f:
        return json.load(f)


@app.get("/config")
def get_config():
    """Runtime config overlay state (intern/dev pane): config_file + overrides + applied (PRD N15).
    SEC-1: describe() redacts secret values at the source; this also passes through _redact_secrets
    (defense in depth) so a future describe() field cannot leak a key."""
    from stewie.specs import config as _cfg
    return {"ok": True, **_redact_secrets(_cfg.describe())}


@app.get("/config/full")
def get_config_full():
    """#61 (Aaron: "config needs to be totally rewritten"): the organized one-call state for the
    Config pane -- server, auth FLAGS (never the key), data holdings, and the N15 overlay."""
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


def _redact_secrets(node):
    """Scrub key/token/secret VALUES from the overlay dump (the N15 describe() includes env
    values -- the API key must never reach the browser)."""
    secret = (os.environ.get("STEWIE_API_KEY", "") or os.environ.get("DUSTGYM_API_KEY", ""))
    if isinstance(node, dict):
        return {k: ("[REDACTED]" if any(t in str(k).upper() for t in ("KEY", "TOKEN", "SECRET"))
                    else _redact_secrets(v)) for k, v in node.items()}
    if isinstance(node, list):
        return [_redact_secrets(v) for v in node]
    if isinstance(node, str) and secret and secret in node:
        return "[REDACTED]"
    return node


@app.get("/layers")
def get_layers():
    """Selectable map layers for the navigation UI (load/unload): imagery, dem, topology, hazard,
    excavation, lander. Vector layers (excavation, lander, zones) are filled per-mission by the client."""
    from stewie.server.gis_layers import RASTER_DEFS
    return {"ok": True, "layers": MLY.layer_defs() + RASTER_DEFS}


@app.get("/layers/raster/{kind}.png")
def get_raster_layer(kind: str, sun_el: float = 6.0, sun_az: float = 90.0,
                     mission_t_s: float | None = None):
    """A computed GIS raster overlay from the REAL Haworth DEM. When mission_t_s is given the sun
    is AUTOMATIC: real spherical geometry at the Haworth latitude (stewie.specs.solar) -- azimuth
    circles per lunar day, elevation breathes inside colatitude+obliquity. el/az are the manual
    override path."""
    from stewie.server.gis_layers import render
    if mission_t_s is not None:
        from stewie.specs.solar import sun_az_el
        sun_az, sun_el = sun_az_el(-87.45, float(mission_t_s))   # Haworth site latitude
    try:
        png = render(kind, sun_el=sun_el, sun_az=sun_az)
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"DEM bundle absent: {e}"})
    if png is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"unknown layer {kind!r}"})
    from fastapi.responses import Response
    return Response(content=png, media_type="image/png")


# ---- B3: operator/director training sessions (the real closed loop, two views) ----------------
from stewie.server import session as SES               # noqa: E402


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")           # mission dict + optional profile
    name: str = "session"
    profile: str = "ideal"


@app.post("/session/start")
def session_start(req: SessionRequest, _auth: None = Depends(require_auth)):
    body = req.model_dump()
    profile = body.pop("profile", "ideal")
    mission_t0_s = float(body.pop("mission_t0_s", 0.0) or 0.0)
    try:
        mission = MP.mission_from_dict(body)
        dem, origin = _moon_dem(body.get("site", "haworth")) if body.get("body", "moon") == "moon" else (None, (0.0, 0.0))
        s = SES.start(mission, profile=profile, dem=dem, dem_origin=origin, mission_t0_s=mission_t0_s)
    except (ValueError, RuntimeError, KeyError, FileNotFoundError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "session_id": s.session_id, "n_legs": len(s.record["legs"]),
            "operator_url": f"/session/{s.session_id}/operator",
            "debrief_url": f"/session/{s.session_id}/debrief"}


@app.get("/session/{sid}/operator")
def session_operator(sid: str):
    """OPEN by contract (B3): the operator-trainee sees only telemetry-delivered, truth-denylisted data."""
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    return s.operator_view()


@app.get("/session/{sid}/scorecard")
def session_scorecard(sid: str, identity: str = Depends(require_auth)):
    """#80: the trainer A-board KPIs. Operators see the public board; directors also get the
    truth board (believed-vs-actual divergence)."""
    from stewie.server import auth as AUTH
    s = SES.get(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="no such session")
    sc = s.scorecard()
    board = dict(sc["public"])
    if AUTH.role_of(identity) == "director":
        board.update(sc["truth"])
    return {"ok": True, "scorecard": board}


@app.get("/session/{sid}/debrief")
def session_debrief(sid: str, fast_forward: float = 1.0, _auth: str = Depends(require_director)):
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    return s.debrief_view(fast_forward=fast_forward)


@app.get("/session/{sid}/summary")
def session_summary(sid: str, _auth: None = Depends(require_auth)):
    s = SES.get(sid)
    if s is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": "unknown session"})
    SES.persist_summary(s)
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(SES.summary_markdown(s), media_type="text/markdown")


# ---- P2.2: the versioned observed-terrain twin (resync = the reconstruction update channel) ---
from stewie.twin import versioned as VT                # noqa: E402

_TWIN: "VT.TwinStore | None" = None
import threading as _threading                            # noqa: E402
_TWIN_LOCK = _threading.Lock()                            # RC-02: serialize the lazy cold-restore


def _twin() -> "VT.TwinStore":
    """Lazy twin over the Haworth observed map (the planner's site); base = the loaded DEM."""
    global _TWIN
    if _TWIN is not None:                                 # fast path (no lock once built)
        return _TWIN
    with _TWIN_LOCK:                                      # RC-02: only ONE thread runs from_journal
        if _TWIN is None:
            dem, _anchor = _moon_dem()
            base = dem[0] if isinstance(dem, tuple) else dem
            import numpy as _np
            if base is None:
                base = _np.zeros((64, 64))              # degraded mode mirrors _moon_dem's fallback
            from stewie.specs import config as _CFG
            _jdir = os.path.join(_CFG.data_dir(), "twin")
            os.makedirs(_jdir, exist_ok=True)
            _jp = os.path.join(_jdir, "haworth.journal")
            # W-1 (PRD 6.2): the server twin is DURABLE -- cold restore from the journal, then journal on
            _TWIN = VT.TwinStore.from_journal(_np.asarray(base, dtype=float), cell_m=5.0,
                                              journal_path=_jp)
    return _TWIN


class ResyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heights_m: list
    origin_rc: list
    provenance: str


@app.post("/twin/resync")
def twin_resync(req: ResyncRequest, _auth: None = Depends(require_auth)):
    import numpy as _np
    try:
        v = _twin().apply_patch(_np.array(req.heights_m, dtype=float),
                                origin_rc=tuple(req.origin_rc), provenance=req.provenance)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "twin_version": v}


@app.get("/twin/version")
def twin_version():
    t = _twin()
    return {"twin_version": t.version, "chain_valid": t.verify_chain(), "events": t.history()}


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": _version(), "uptime_s": round(time.monotonic() - _START, 1)}


@app.get("/metrics")
def metrics():
    return {"uptime_s": round(time.monotonic() - _START, 1), **_METRICS}


# ---- profiles: save / list / load a planning config snapshot ------------------------------------
def _profile_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", str(name).lower()).strip("-") or "profile"


@app.post("/profile")
def post_profile(req: ProfileRequest, _auth: None = Depends(require_auth)):
    """Save a planning profile (the full config snapshot) under a slug of its name, to profiles/."""
    os.makedirs(PROFILES, exist_ok=True)
    slug = _profile_slug(req.name)
    atomic_write_bytes(os.path.join(PROFILES, slug + ".json"),            # PO-02: atomic, no partial profile
                       json.dumps({"name": req.name, "profile": req.profile}, indent=2).encode("utf-8"))
    return {"ok": True, "name": slug}


@app.get("/profiles")
def get_profiles():
    """List the saved profile slugs."""
    if not os.path.isdir(PROFILES):
        return {"ok": True, "profiles": []}
    return {"ok": True, "profiles": sorted(os.path.splitext(f)[0]
                                           for f in os.listdir(PROFILES) if f.endswith(".json"))}


@app.get("/profile/{name}")
def get_profile(name: str):
    """Load a saved profile by slug -> {name, profile}."""
    slug = _profile_slug(name)
    p = os.path.join(PROFILES, slug + ".json")
    if not os.path.isfile(p):
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no profile {slug!r}"})
    with open(p) as fh:
        return json.load(fh)


# ---- POST: the planner API (auth-gated when $DUSTGYM_API_KEY is set) -----------------------------
@app.post("/plan")
def post_plan(req: PlanRequest, _auth: None = Depends(require_auth)):
    _prune_reports()
    payload = req.model_dump(exclude_unset=True)
    try:
        mission = MP.mission_from_dict(payload)
        if mission.body == "moon":
            dem, origin = _moon_dem(getattr(req, "site", "haworth"))  # REG-01: the chosen site DEM
            if req.lat is not None and req.lon is not None:   # M11: a globe site-pick overrides the anchor
                try:
                    origin = MP.latlon_to_dem_origin(req.lat, req.lon)
                except ImportError:
                    log.warning("pyproj absent ([planner] extra); site lat/lon ignored, using flattest anchor")
                except ValueError as e:
                    return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
        else:
            dem, origin = None, (0.0, 0.0)
        # RB-03: compute the plan ONCE (incl. as-built validation + endurance); report/timeline/IR and the
        # validation/endurance fields are all VIEWS of this single result (no independent recompute).
        result = MP.plan(mission, dem=dem, dem_origin=origin, algorithm=req.algorithm,
                         objective=req.objective, vehicles=req.vehicles, with_acceptance=True)
        # I10: hauls routed around hazards on the real DEM; I8 + I6/M11 slope-feasible siting.
        with _REPORT_LOCK:                              # serialize the thread-unsafe matplotlib report path
            pdf, md, totals = MP.run(mission, stem=_plan_stem(payload), dem=dem, dem_origin=origin,
                                     algorithm=req.algorithm, objective=req.objective,
                                     vehicles=req.vehicles, result=result)
        validation = result.validation                  # RB-03: from the one result, not a recompute
        timeline = MP.build_timeline(mission, dem=dem, dem_origin=origin,
                                     algorithm=req.algorithm, objective=req.objective, result=result)
        endurance = result.endurance
        autonomy, perception = _autonomy_perception(mission, dem, origin, req.algorithm, req.objective)
        plan_ir = MP.plan_ir(mission, dem=dem, dem_origin=origin,                # the machine-executable plan
                             algorithm=req.algorithm, objective=req.objective,
                             vehicles=req.vehicles, result=result)
    except (ValueError, RuntimeError) as e:             # bad input / sinter-gated -> honest 400
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    except (KeyError, TypeError) as e:                  # missing/odd-typed field -> ALSO the contracted
        # 400 {ok:false,error} (audit M40: these surfaced as uncaught 500s)
        return JSONResponse(status_code=400, content={"ok": False, "error": f"bad request field: {e!r}"})
    return {
        "ok": True,
        "mode": "DEM_KNOWN_POSE_MISSION_SIM",           # product boundary (known-pose mission sim, not SLAM)
        # item 4: NEVER silently degrade to flat -- surface which terrain the plan actually used so the UI/report
        # can warn when the real DEM is missing (routes/hazards are not trustworthy on the flat fallback).
        "terrain_source": "haworth_dem" if dem is not None else "flat_fallback",
        "pdf": "/reports/" + os.path.basename(pdf),
        "md": "/reports/" + os.path.basename(md),
        "totals": _totals_json(totals),
        "validation": validation,
        "timeline": timeline,
        "endurance": endurance,
        "autonomy": autonomy,
        "perception": perception,
        "plan_ir": plan_ir,                             # versioned typed-action plan a rover/ROS executive runs
        "provenance": result.provenance,                # RB-03/CT-07: schema, mode, config, input hash of THE plan
    }


@app.post("/compare")
def post_compare(req: CompareRequest, _auth: None = Depends(require_auth)):
    payload = req.model_dump(exclude_unset=True)
    try:
        mission = MP.mission_from_dict(payload)
        dem, origin = _moon_dem() if mission.body == "moon" else (None, (0.0, 0.0))
        result = MP.compare_algorithms(mission, objective=req.objective, dem=dem, dem_origin=origin)
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, **result}


@app.post("/localize")
def post_localize(req: LocalizeRequest, _auth: None = Depends(require_auth)):
    """[REQ:PM-06] SN-10 articulation-parallax relocalization, wired into the estimator. From the
    shadow-tip PIXEL shifts observed under a commanded chassis lift dh, triangulate landmark ranges,
    fix the rover (x,y) heading-free, inject it into a one-node PoseGraphSE2 as an ABSOLUTE factor with
    the geometry-DERIVED covariance, and return the re-optimized fix + 1-sigma. This is the missing
    endpoint that makes the validated estimator reachable from the live system (PRD §22 P1.1)."""
    n = len(req.landmarks_xy)
    if n < 2:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "need >= 2 landmarks for a heading-free fix"})
    if len(req.pixel_shifts) != n:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "pixel_shifts must match landmarks_xy in length"})
    try:
        graph = PG.PoseGraphSE2()
        graph.add_prior(0, (float(req.prior_xy[0]), float(req.prior_xy[1]), float(req.prior_yaw)),
                        float(req.prior_sigma_xy), float(req.prior_sigma_yaw))
        out = AP.articulation_localize(
            graph, 0, [(float(x), float(y)) for x, y in req.landmarks_xy],
            [float(s) for s in req.pixel_shifts],
            dh_m=float(req.dh_m), fx_px=float(req.fx_px), sigma_px=float(req.sigma_px))
    except (ValueError, RuntimeError) as e:                 # degenerate geometry -> honest 400, not a 500
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    fix = out["fix_xy"]
    log_event("api", "localize", f"{n} landmarks -> fix ({fix[0]:.2f},{fix[1]:.2f}) sigma {out['fix_sigma_m']:.3f}m")
    return {
        "ok": True,
        "fix_xy": [float(fix[0]), float(fix[1])],
        "fix_sigma_m": float(out["fix_sigma_m"]),
        "pose": {str(k): [float(c) for c in v] for k, v in out["pose"].items()},
        "xy_sigma": {str(k): float(v) for k, v in out["xy_sigma"].items()},
        "yaw_sigma": {str(k): float(v) for k, v in out["yaw_sigma"].items()},
    }


_KATWIJK_CACHE: dict = {}   # part name -> loaded real arrays (parse once, reuse across requests)


def _katwijk_arrays(segment: str):
    """Resolve + cache the REAL Katwijk arrays for a segment. Returns None if the dataset is not on this
    host (not bundled -- ESA license + size); the /slam endpoint then answers 503, never fabricates.
    No machine-specific path in source: the root is $STEWIE_KATWIJK_DIR (DUSTGYM_ fallback)."""
    if segment in _KATWIJK_CACHE:
        return _KATWIJK_CACHE[segment]
    root = _env("KATWIJK_DIR")
    if not root:
        return None
    part_dir = os.path.join(root, segment)
    if not os.path.isdir(part_dir):
        return None
    arrays = ISLAM.load_katwijk_arrays(part_dir)
    _KATWIJK_CACHE[segment] = arrays
    return arrays


@app.post("/slam")
def post_slam(req: SlamRequest, _auth: None = Depends(require_auth)):
    """[REQ:PM-06] The integrated multi-factor SLAM run, exposed. Fuse odometry + IMU-yaw + shadow-yaw
    + articulation-parallax + DEM-registration over a real Katwijk segment and return the trajectory,
    the aligned + absolute trajectory error, the odometry-only baseline, and the leave-one-out factor
    attribution. The raw Katwijk traverse is not bundled (ESA license + size); when it is not on this
    host the endpoint answers 503 -- it never fabricates a trajectory (PRD §22 P1.2)."""
    arrays = _katwijk_arrays(req.segment)
    if arrays is None:
        return JSONResponse(status_code=503, content={
            "ok": False, "error": f"Katwijk segment {req.segment!r} unavailable (set STEWIE_KATWIJK_DIR "
            "to the dataset root; not bundled -- ESA license + size)"})
    truth, dr, tyaw, gyro = arrays
    try:
        loo = ISLAM.leave_one_out(truth, dr, tyaw, gyro, n_keyframes=req.n_keyframes, seed=req.seed)
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    full, base = loo["full"], loo["baseline_odom"]
    log_event("api", "slam",
              f"{req.segment}: fused {full['abs_max_err_m']:.2f}m vs baseline {base['abs_max_err_m']:.2f}m")
    return {
        "ok": True, "segment": req.segment, "n_keyframes": req.n_keyframes,
        "ate_aligned_m": full["ate_aligned_m"], "abs_max_err_m": full["abs_max_err_m"],
        "baseline_abs_max_err_m": base["abs_max_err_m"],
        "reduction_x": round(base["abs_max_err_m"] / max(full["abs_max_err_m"], 1e-9), 1),
        "n_fix": full["n_fix"],
        "trajectory_xy": [[float(x), float(y)] for x, y in full["est_xy"]],
        "baseline_xy": [[float(x), float(y)] for x, y in base["est_xy"]],   # odom-only path -> est-vs-DR plot
        "leave_one_out": loo["leave_one_out"],
    }


@app.post("/slam/compare")
def post_slam_compare(req: SlamCompareRequest, _auth: None = Depends(require_auth)):
    """[REQ:SN-12] The shared-testbed head-to-head, surfaced. The SAME pose graph over the SAME real
    Katwijk trajectory under three approach classes, each at its characteristic absolute-fix sigma:
    passive single-pass (no fix), ShadowNav-class global map-match (~3 m), ARGUS articulation parallax
    (~0.5 m). Each class is MODELED at its reported accuracy against the real drift -- the proprietary
    stacks are not executed (honest comparison-of-classes, not of stacks). 503 when the dataset is
    absent (PRD §22 P3)."""
    arrays = _katwijk_arrays(req.segment)
    if arrays is None:
        return JSONResponse(status_code=503, content={
            "ok": False, "error": f"Katwijk segment {req.segment!r} unavailable (set STEWIE_KATWIJK_DIR; "
            "not bundled -- ESA license + size)"})
    truth, dr, tyaw, gyro = arrays
    try:
        cmp = ISLAM.shared_testbed_comparison(truth, dr, tyaw, gyro,
                                              n_seeds=req.n_seeds, n_keyframes=req.n_keyframes)
    except (ValueError, RuntimeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "segment": req.segment, "n_seeds": req.n_seeds,
            "modeled": "each class at its reported sigma vs the real drift; stacks not executed", "comparison": cmp}


@app.post("/render/parallax")
def post_render_parallax(req: ParallaxPlanRequest, _auth: None = Depends(require_auth)):
    """[REQ:SN-10] Wire the articulation-parallax capture onto the render surface. Return the
    two-posture standstill capture plan: the known baseline dh = lift_B - lift_A and the two Godot
    render commands (posture A + posture B, same scene + sun, the 8-camera rig) a GPU host runs to
    capture the parallax pair. The plan + the exact dh are deterministic; executing the renders and
    reading the shadow-tip pixel SHIFT is the gated GPU/photometric layer (PRD §22 P1.3)."""
    from stewie.godot import articulation_bridge as AB
    try:
        plan = AB.parallax_capture_plan(
            req.scene, sun_az_deg=req.sun_az_deg, sun_el_deg=req.sun_el_deg,
            posture_from=req.posture_from, posture_to=req.posture_to, size=req.size)
    except (KeyError, ValueError) as e:                 # unknown posture name -> get_posture raises KeyError
        return JSONResponse(status_code=400, content={"ok": False, "error": f"unknown posture: {e}"})
    return {"ok": True, "scene": req.scene, **plan}


_PARALLAX_RENDER_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "godot", "out", "parallax"))
_PARALLAX_SCENE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "samples", "crater_boulders"))


@app.post("/localize/render")
def post_localize_render(req: LocalizeRenderRequest, _auth: None = Depends(require_auth)):
    """[REQ:SN-10] REAL measured articulation-parallax fix from the committed two-posture render-pair.
    A truth-free confidence gate + RANSAC over the measured shadow/clast vertical parallax recovers the
    rover ground position in the DEM-local frame (where it sits on the 3D DEM). TRL-5-faithful: the
    matched features lie inside the IPEx rig's sourced 0.37-1.9 m resolvable range. 503 when the
    render-pair is absent -- never a fabricated fix (PRD §22 P3)."""
    if not os.path.exists(os.path.join(_PARALLAX_RENDER_DIR, "A", req.camera + ".png")):
        return JSONResponse(status_code=503, content={
            "ok": False, "error": "two-posture render-pair unavailable "
            "(stewie/godot/out/parallax); render it with the Godot sidecar first"})
    from stewie.godot import articulation_bridge as AB
    try:
        res = AB.localize_on_render_pair(_PARALLAX_RENDER_DIR, _PARALLAX_SCENE_DIR,
                                         camera=req.camera, drift_m=req.drift_m)
    except (ValueError, RuntimeError, KeyError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    log_event("api", "localize/render", f"{req.camera}: fix err {res['error_m']} m, {res['n_inliers']} inliers")
    return {"ok": True, **res}


@app.post("/structure")
def post_structure(req: StructureRequest, _auth: None = Depends(require_auth)):
    """Decompose a named structure (Landing Pad / Haul Road / Berm / ...) at (x,y) into mass-balanced
    cut/fill orders (structures.decompose). Returns orders the build queue can adopt."""
    if len(req.params or {}) > 32:                      # N8: cap the param dict (decompose also rejects unknown keys)
        return JSONResponse(status_code=400, content={"ok": False, "error": "too many structure params (max 32)"})
    try:
        orders = ST.decompose(req.name, req.x, req.y, **(req.params or {}))
    except (ValueError, TypeError) as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})
    return {"ok": True, "name": req.name, "orders": orders}


@app.post("/sense")
def post_sense(req: SenseRequest, _auth: None = Depends(require_auth)):
    """Drum-fill sensing (ICE-RASSOR): true drum mass -> motor-current observable -> inferred mass +
    offload decision. `noise_frac` toggles seeded sensor noise (0 = OFF)."""
    cap = req.capacity_kg if req.capacity_kg is not None else float(MP.RM.REGOLITH_PER_CYCLE_KG)
    grid = [cap * f for f in (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0)]
    sensor = MP.RM.DrumSensor.calibrated(grid, capacity_kg=cap, noise_frac=req.noise_frac, seed=req.seed)
    current = sensor.current(req.true_mass_kg)
    inferred = sensor.infer(current)
    dec = sensor.offload(inferred)
    return {
        "ok": True, "true_mass_kg": req.true_mass_kg, "current_a": current, "inferred_kg": inferred,
        "uncertainty_frac": dec.uncertainty_frac, "lower_kg": dec.lower_kg, "upper_kg": dec.upper_kg,
        "capacity_kg": cap, "offload": dec.offload, "noise_frac": req.noise_frac,
    }


@app.post("/render")
def post_render(req: RenderRequest, _auth: None = Depends(require_auth)):
    """Crop a Haworth window at the picked (u,v), plan a flatten, render BEFORE/AFTER in Godot, and
    return the figure URL + earthwork volumes. Slow (two Godot renders); 503 if the binary is absent."""
    if PRP is None:
        return JSONResponse(status_code=503,
                            content={"ok": False, "error": "render pipeline unavailable (Godot binary absent)"})
    _prune_reports()
    stem = "render_" + hashlib.sha1(f"{req.u:.4f}_{req.v:.4f}_{req.pad_frac:.2f}".encode()).hexdigest()[:10]
    try:
        with _REPORT_LOCK:
            r = PRP.render_map_area(_HAWORTH, req.u, req.v, os.path.join(REPORTS, stem),
                                    pad_frac=req.pad_frac, mission_t_s=req.mission_t_s)
    except Exception as e:                              # noqa: BLE001 -- render failure -> honest 500
        log.exception("render failed for (u=%s, v=%s)", req.u, req.v)
        return JSONResponse(status_code=500, content={"ok": False, "error": f"render failed: {e}"})
    fig_name = stem + ".png"
    shutil.copyfile(r["figure"], os.path.join(REPORTS, fig_name))
    return {
        "ok": True, "figure": "/reports/" + fig_name,
        "cut_vol_m3": round(r["cut_vol_m3"], 2), "fill_vol_m3": round(r["fill_vol_m3"], 2),
        "cut_kg": round(r["cut_kg"]), "extent_m": round(r["extent_m"], 1), "cell_m": round(r["cell_m"], 2),
    }


# ---- catch-all 404s (registered last) keep the {ok:false,error} envelope ------------------------
@app.get("/{path:path}")
def _no_get(path: str):
    return JSONResponse(status_code=404, content={"ok": False, "error": f"no route /{path}"})


@app.post("/{path:path}")
def _no_post(path: str):
    return JSONResponse(status_code=404, content={"ok": False, "error": f"no route /{path}"})


def main():
    ap = argparse.ArgumentParser(description="planet browser + mission planner server (ASGI)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; use 0.0.0.0 to reach it over the LAN/tailnet (default localhost)")
    args = ap.parse_args()
    _configure_logging()
    _prune_reports()
    log.info("planet browser + planner (ASGI) -> http://%s:%s/   (POST /plan,/sense; /healthz,/metrics; Ctrl-C)",
             args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
