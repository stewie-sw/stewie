#!/usr/bin/env python3
"""server.py -- ASGI server for the planet browser + mission planner (PRD N7/N8).

FastAPI/uvicorn. Serves the static front-end (index.html, bodies.json), the generated reports, and the
JSON API the browser drives: POST /plan, /sense, /structure, /compare, /render. Production hardening:
Pydantic request models (typed contract + input limits), optional API-key auth on the mutating routes,
CORS, a thread-safe (locked) matplotlib report path, a reports/ TTL sweep, structured access logging
(PRD N10), and /healthz + /metrics.

    python -m stewie.server.server [--port 8770] [--host 0.0.0.0]    # or the `stewie-serve` entry point

Env knobs (PRD N15 overlay style): STEWIE_API_KEY (auth on POST when set), STEWIE_CORS_ORIGINS
(comma-list or *), STEWIE_REPORTS_TTL_S (report retention, default 86400), STEWIE_LOG_LEVEL.
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# PRD N10: structured logging + observability. Used for access logs, startup, and the additive
# failure paths. Level via $STEWIE_LOG_LEVEL.
log = logging.getLogger("stewie.server")

# ARCH-3: the shared auth dependencies + env helpers live in stewie.server.deps so the per-concern
# routers can import them without cycling through this app module.
from stewie.server.deps import _env, _truthy  # noqa: E402




def _configure_logging(level: str | None = None) -> None:
    """Configure logging for the server (PRD N10): level from arg, else $STEWIE_LOG_LEVEL, else INFO."""
    lvl = (level or _env("LOG_LEVEL", "INFO")).upper()
    logging.basicConfig(level=getattr(logging, lvl, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", force=True)


HERE = os.path.dirname(os.path.abspath(__file__))

_CTYPE = {".html": "text/html; charset=utf-8", ".json": "application/json",
          ".pdf": "application/pdf", ".md": "text/markdown; charset=utf-8",
          ".js": "text/javascript", ".css": "text/css", ".png": "image/png"}

_MAX_BODY_BYTES = int(_env("MAX_BODY_BYTES", 4 * 1024 * 1024))   # N8: request-body size cap (4 MiB)


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("stewie")    # the dist renamed (was stewie; the old lookup always fell back to 0.1.0)
    except Exception:   # noqa: BLE001 -- not installed (editable/source run)
        return "0.1.0"



# --------------------------------------------------------------------------------------------------
# Request models (PRD N8: the typed API contract + input limits). extra="allow" passes through the
# optional per-kind order fields the planner reads; the limits below cap obviously-abusive inputs.
# --------------------------------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: "FastAPI"):
    """ARCH-06: boot wiring via the FastAPI lifespan context manager (the @app.on_event("startup")
    API is deprecated and slated for removal in Starlette). Startup runs the auth-posture announcement
    + the background globe-cache warm; there is no shutdown work. `_startup_warm_globe_cache` is
    resolved at call time, so it may be defined later in the module."""
    from stewie.server import auth as _auth
    _auth.validate_proxy_trust_config()                   # SEC-03: refuse to boot fail-open (raises)
    from stewie.server import operators as _ops          # first-director provisioning from deploy env
    _seeded = _ops.bootstrap_director_from_env()          # so the deploy key never enters a browser
    if _seeded:
        log.info("bootstrap: seeded founding director %r from STEWIE_BOOTSTRAP_DIRECTOR "
                 "(sign in with STEWIE_BOOTSTRAP_PASSWORD)", _seeded)
    _startup_warm_globe_cache()
    yield


app = FastAPI(title="STEWIE — mission planner + planet browser API", version=_version(),
              lifespan=lifespan)

# S-11: CORS is SAME-ORIGIN by default. An unset (or empty) STEWIE_CORS_ORIGINS yields an EMPTY
# allowlist -> no Access-Control-Allow-Origin is reflected for a cross-origin request (the browser's
# same-origin policy applies). A wildcard '*' is honored only if EXPLICITLY configured (dev), and a
# comma list pins exact origins. This replaces the prior default of '*', which let any website script
# the authenticated API from a victim's browser.
_cors = _env("CORS_ORIGINS", "").strip()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors == "*" else [o.strip() for o in _cors.split(",") if o.strip()],
    allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """S-11: baseline hardening headers on every response. CSP/frame-ancestors are enforced at the
    nginx edge (deploy/nginx.conf), where the HTML document is served; these are the app-level
    complements that travel with the API responses too."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    return response

# ARCH-3: per-concern routers (the RC command path first, per §21). Each owns its own state + imports
# the shared auth deps (server.deps) / audit log (server.services) -- no import of this app module.
from stewie.server.routers import admin_ops as _admin_ops_router  # noqa: E402
from stewie.server.routers import assets as _assets_router  # noqa: E402
from stewie.server.routers import auth as _auth_router  # noqa: E402
from stewie.server.routers import config as _config_router  # noqa: E402
from stewie.server.routers import dem as _dem_router  # noqa: E402
from stewie.server.routers import ephemeris as _ephemeris_router  # noqa: E402
from stewie.server.routers import figures as _figures_router  # noqa: E402
from stewie.server.routers import health as _health_router  # noqa: E402
from stewie.server.routers import invites as _invites_router  # noqa: E402
from stewie.server.routers import layers as _layers_router  # noqa: E402
from stewie.server.routers import missions as _missions_router  # noqa: E402
from stewie.server.routers import operators_admin as _operators_admin_router  # noqa: E402
from stewie.server.routers import perception as _perception_router  # noqa: E402
from stewie.server.routers import plan as _plan_router  # noqa: E402
from stewie.server.routers import profiles as _profiles_router  # noqa: E402
from stewie.server.routers import rc as _rc_router  # noqa: E402
from stewie.server.routers import sample_missions as _sample_missions_router  # noqa: E402
from stewie.server.routers import session as _session_router  # noqa: E402
from stewie.server.routers import structures as _structures_router  # noqa: E402
from stewie.server.routers import schema as _schema_router  # noqa: E402
from stewie.server.routers import twin as _twin_router  # noqa: E402
from stewie.server.routers import world as _world_router  # noqa: E402
app.include_router(_rc_router.router)
app.include_router(_auth_router.router)
app.include_router(_invites_router.router)
app.include_router(_missions_router.router)
app.include_router(_structures_router.router)
app.include_router(_operators_admin_router.router)
app.include_router(_profiles_router.router)
app.include_router(_sample_missions_router.router)
app.include_router(_assets_router.router)
app.include_router(_layers_router.router)
app.include_router(_config_router.router)
app.include_router(_health_router.router)
app.include_router(_dem_router.router)
app.include_router(_ephemeris_router.router)
app.include_router(_world_router.router)
app.include_router(_schema_router.router)
app.include_router(_figures_router.router)
app.include_router(_twin_router.router)
app.include_router(_admin_ops_router.router)
app.include_router(_session_router.router)
app.include_router(_plan_router.router)
app.include_router(_perception_router.router)


@app.middleware("http")
async def _access_log(request: Request, call_next):
    t0 = time.monotonic()
    # FS-19: one correlation id per request -- honor an inbound id (an upstream/tunnel can set it) else
    # mint one. Every semantic event log_event'd inside this request inherits it (services ContextVar),
    # so the ledger lets an admin pull the whole story of one operator action by id.
    cid = (request.headers.get("x-correlation-id") or request.headers.get("x-request-id")
           or _new_correlation_id())
    _set_correlation_id(cid)
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
    record_request(sk, route_key)                        # RC-04: atomic counter update (server.services)
    record_latency(route_key, dt)                        # FS-10: per-route latency budget tracking
    budget = budget_for(route_key)
    if dt > budget:                                      # FS-10: a real breach surfaces in the logs, not just /metrics
        log.warning("perf budget exceeded: %s %.1fms > %.0fms budget", route_key, dt, budget)
    log.info('%s "%s %s" %s %.1fms',
             request.client.host if request.client else "-", request.method, raw, response.status_code, dt)
    response.headers["X-Correlation-Id"] = cid           # FS-19: hand the id back so a client can cite it
    # FS-19: the correlation id threads the SEMANTIC events log_event'd inside this request (services
    # ContextVar), and per-route latency/result live in /metrics (FS-10) + the access line above. We do
    # NOT inject a per-request http.* event into events.jsonl: that ledger is the operator AUDIT trail
    # (who did what -- director-gated, the Admin viewer), and actor-less request rows would pollute it.
    # A full per-contract-call observability ledger belongs in a separate stream (future work).
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



# ---- #39: the event history (who did what when; actor = the #52 auth identity) ----------------
# ARCH-3: the audit ledger lives in stewie.server.services so routers can log without importing this app.
from stewie.server.services import (  # noqa: E402
    budget_for,
    new_correlation_id as _new_correlation_id,
    prune_reports as _prune_reports,
    record_latency,
    record_request,
    set_correlation_id as _set_correlation_id,
)


# ---- #32: no-terminal admin ops (the W-2/W-3 CLIs + gate validation as buttons) ---------------
# --- #66 + SF-01: the pluggable RC seam now lives in stewie.server.routers.rc (included below) -----


def _startup_warm_globe_cache():
    """Background-warm the heavy globe products (PSR's sweep measured 44 s cold) so the first
    user click finds them ready; errors are non-fatal (no DEM in some deployments). Invoked from the
    ARCH-06 lifespan at startup."""
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
            for kind in ("dem", "slope", "hazard", "illumination", "psr", "grid"):
                render_globe(kind)   # incl. grid: it was never pre-warmed, so a cold first fetch
                                     # could stall + time out on a slow (mobile) link
        except Exception:
            pass

    threading.Thread(target=warm, daemon=True).start()


# ---- B3: operator/director training sessions (the real closed loop, two views) ----------------
# ---- POST: the planner API (auth-gated when $STEWIE_API_KEY is set) -----------------------------
# ---- catch-all 404s (registered last) keep the {ok:false,error} envelope ------------------------
@app.get("/{path:path}")
def _no_get(path: str):
    return JSONResponse(status_code=404, content={"ok": False, "error": f"no route /{path}"})


@app.post("/{path:path}")
def _no_post(path: str):
    return JSONResponse(status_code=404, content={"ok": False, "error": f"no route /{path}"})


_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost", "")


def _require_tls_for_public_bind(host: str) -> None:
    """S-04: refuse a non-loopback (public) bind unless TLS termination is declared. STEWIE serves no
    TLS itself -- production puts it behind nginx/cloudflared that terminate HTTPS, redirect HTTP, and
    set HSTS (deploy/nginx.conf). Binding 0.0.0.0 with NO terminator declared means plaintext HTTP is
    exposed on the LAN, so we fail closed. The deployment asserts the terminator with
    STEWIE_TLS_TERMINATED=1 (or STEWIE_DEV_OPEN=1 for an explicit loopback-style dev override).
    Loopback binds are always allowed (the cloudflared/nginx origin)."""
    h = (host or "").strip().lower()
    if h in _LOOPBACK_HOSTS:
        return
    if _truthy(_env("TLS_TERMINATED")) or _truthy(_env("DEV_OPEN")):
        return
    log.critical("refusing public bind %r without TLS: set STEWIE_TLS_TERMINATED=1 once HTTPS is "
                 "terminated in front of the server (deploy/nginx.conf), or bind 127.0.0.1.", host)
    raise SystemExit(2)


def main():
    ap = argparse.ArgumentParser(description="planet browser + mission planner server (ASGI)")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address; use 0.0.0.0 to reach it over the LAN/tailnet (default localhost)")
    args = ap.parse_args()
    _configure_logging()
    _require_tls_for_public_bind(args.host)      # S-04: fail closed on a plaintext public bind
    _prune_reports()
    log.info("planet browser + planner (ASGI) -> http://%s:%s/   (POST /plan,/sense; /healthz,/metrics; Ctrl-C)",
             args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_config=None)


if __name__ == "__main__":
    main()
