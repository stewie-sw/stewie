"""Security guard for the PUBLIC viz2 pixel-stream (``stewie.stream.app``).

The stream service spawns a Godot ``--live --stream`` process on the host RTX 3090 for every live
session. That is fine on the tailnet (private), but the moment it is exposed publicly (Cloudflare ->
cloudflared -> this app) it would be an OPEN GPU-render endpoint. This module adds three real,
enforcing guards so it can be exposed safely:

  1. **Token auth** (env ``VIZ2_STREAM_TOKEN``). WHEN SET, every guarded route + the WS require a
     matching ``?token=<T>`` query param, compared in CONSTANT TIME (``hmac.compare_digest``). Wrong
     or missing -> HTTP 401 (WS -> close 4401 + reason). WHEN UNSET the guard is OFF and the service
     behaves EXACTLY as today (open, for the tailnet deploy) -- the token gate simply does not apply.
     Static assets (``/vendor/*``) and the health probe (``/healthz``) are exempt from the token gate
     so the ES-module import + readiness poll work with a single ``?token=T`` link.

  2. **Concurrency cap** (env ``VIZ2_STREAM_MAX_SESSIONS``, default 2). A process-global live-session
     counter is incremented right BEFORE a WS spawns Godot/Viz2Runtime and decremented on teardown
     (try/finally). The (cap+1)th connection is refused with an "at capacity, try again shortly" close
     BEFORE any GPU process is spawned. Protects the single GPU.

  3. **Rate-limit** (env ``VIZ2_STREAM_MAX_CONN_PER_MIN``, default 20). A per-client-IP sliding-window
     limit on NEW connection entry points (``GET /``, ``GET /stream``, ``WS /ws``); beyond it -> HTTP
     429 / WS close. The intra-page data XHRs (``/bundles``, ``/preview/*``) are token-gated but NOT
     rate-limited, so live preview scrubbing is never throttled. In-memory (the deploy runs ONE
     uvicorn worker). The client IP honors ``X-Forwarded-For`` (Cloudflare rewrites it to the real
     client) when present, else the socket peer.

All three read their env at REQUEST time (no import-time caching), so a per-request/per-test override
takes effect immediately. State (the sliding window + the session counter) is process-global and can
be reset via :func:`reset_state` (used by the stream test fixture for isolation).
"""
from __future__ import annotations

import hmac
import os
import time
from collections import deque
from typing import Awaitable, Callable

from fastapi import FastAPI, WebSocket
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# ── env knobs ────────────────────────────────────────────────────────────────────────────────
ENV_TOKEN = "VIZ2_STREAM_TOKEN"
ENV_MAX_SESSIONS = "VIZ2_STREAM_MAX_SESSIONS"
ENV_MAX_CONN_PER_MIN = "VIZ2_STREAM_MAX_CONN_PER_MIN"

DEFAULT_MAX_SESSIONS = 2
DEFAULT_MAX_CONN_PER_MIN = 20
RATE_WINDOW_S = 60.0

# ── WS close codes (application range 4000-4999) ─────────────────────────────────────────────
WS_CLOSE_UNAUTHORIZED = 4401   # missing / wrong token (parallels HTTP 401)
WS_CLOSE_RATE_LIMITED = 4429   # too many new connections from this IP (parallels HTTP 429)
WS_CLOSE_AT_CAPACITY = 4409    # all GPU session slots busy (parallels HTTP 409)

#: routes that count as a NEW connection for rate-limiting (a page/stream entry). The high-frequency
#: intra-page data XHRs (/bundles, /preview/*) are deliberately excluded so preview scrubbing is not
#: throttled; they are still token-gated.
_RATE_LIMITED_PATHS = frozenset({"/", "/stream"})


def _is_exempt(path: str) -> bool:
    """Paths exempt from BOTH the token gate and the rate-limit: the vendored ES-module static asset
    (imported by ``index.html``) and the readiness probe (polled by the e2e/health check)."""
    return path == "/healthz" or path == "/vendor" or path.startswith("/vendor/")


# ── sliding-window rate limiter ──────────────────────────────────────────────────────────────
class SlidingWindowLimiter:
    """A dependency-free, in-memory sliding-window counter keyed by an arbitrary string (client IP).

    ``allow(key, limit)`` records the current instant and returns True if the number of hits within
    the trailing ``window_s`` is < ``limit``; the (limit+1)th hit in the window returns False (the
    caller maps that to HTTP 429 / a WS close). ``limit`` is passed per call so an env change takes
    effect without rebuilding the limiter.
    """

    def __init__(self, window_s: float = RATE_WINDOW_S) -> None:
        self.window_s = float(window_s)
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int, *, now: float | None = None) -> bool:
        t = now if now is not None else time.monotonic()
        cutoff = t - self.window_s
        dq = self._hits.get(key)
        if dq is None:
            dq = deque()
            self._hits[key] = dq
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= max(1, int(limit)):
            return False
        dq.append(t)
        if len(self._hits) > 4096:          # opportunistic GC so churned keys cannot grow unbounded
            self._gc(t)
        return True

    def reset(self) -> None:
        self._hits.clear()

    def _gc(self, now: float) -> None:
        cutoff = now - self.window_s
        stale = [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]
        for k in stale:
            del self._hits[k]


# ── concurrency (live GPU session) counter ───────────────────────────────────────────────────
class SessionCounter:
    """A process-global live-session counter. ``acquire(cap)`` reserves a slot if under ``cap`` (the
    check-and-increment is atomic under asyncio -- no ``await`` between test and increment);
    ``release`` frees one. Robust to a double release (never goes negative)."""

    def __init__(self) -> None:
        self._n = 0

    def acquire(self, cap: int) -> bool:
        if self._n >= max(1, int(cap)):
            return False
        self._n += 1
        return True

    def release(self) -> None:
        if self._n > 0:
            self._n -= 1

    @property
    def count(self) -> int:
        return self._n

    def reset(self) -> None:
        self._n = 0


# ── process-global state (reset between tests via reset_state) ───────────────────────────────
_limiter = SlidingWindowLimiter(RATE_WINDOW_S)
_sessions = SessionCounter()


def reset_state() -> None:
    """Clear the sliding-window buckets + the live-session counter (test isolation)."""
    _limiter.reset()
    _sessions.reset()


def current_sessions() -> int:
    """Live-session count (introspection / tests)."""
    return _sessions.count


# ── config readers (env at request time) ─────────────────────────────────────────────────────
def _configured_token() -> str | None:
    t = os.environ.get(ENV_TOKEN, "")
    return t if t else None


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def max_sessions() -> int:
    return _int_env(ENV_MAX_SESSIONS, DEFAULT_MAX_SESSIONS)


def max_conn_per_min() -> int:
    return _int_env(ENV_MAX_CONN_PER_MIN, DEFAULT_MAX_CONN_PER_MIN)


# ── token + client-ip helpers ────────────────────────────────────────────────────────────────
def token_ok(supplied: str | None) -> bool:
    """Constant-time token check. Returns True when the guard is OFF (no ``VIZ2_STREAM_TOKEN`` set),
    else True only when ``supplied`` matches it via ``hmac.compare_digest``."""
    expected = _configured_token()
    if expected is None:
        return True                      # guard disabled -> open (tailnet mode)
    if not supplied:
        return False
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _client_ip_from(headers: object, client: object) -> str:
    """Best client IP: the first hop of ``X-Forwarded-For`` (Cloudflare rewrites it to the real
    client) when present, else the socket peer host."""
    xff = ""
    get = getattr(headers, "get", None)
    if callable(get):
        xff = get("x-forwarded-for", "") or ""
    if xff:
        return xff.split(",")[0].strip()
    host = getattr(client, "host", None)
    return host if host else "-"


def client_ip(request: Request) -> str:
    return _client_ip_from(request.headers, request.client)


def ws_client_ip(ws: WebSocket) -> str:
    return _client_ip_from(ws.headers, ws.client)


# ── HTTP guard (middleware) ──────────────────────────────────────────────────────────────────
def install_http_guard(app: FastAPI) -> None:
    """Register the HTTP token + rate-limit middleware on ``app``. WebSocket ``/ws`` is guarded
    separately in the endpoint (see :func:`ws_guard_admit` / :func:`acquire_session`)."""

    @app.middleware("http")
    async def _guard(request: Request,
                     call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if _is_exempt(path):
            return await call_next(request)
        if not token_ok(request.query_params.get("token")):
            return JSONResponse({"detail": "unauthorized: missing or invalid stream token"},
                                status_code=401)
        if path in _RATE_LIMITED_PATHS and not _limiter.allow(client_ip(request), max_conn_per_min()):
            return JSONResponse({"detail": "rate limited: too many connections, try again shortly"},
                                status_code=429)
        return await call_next(request)


# ── WS guard ─────────────────────────────────────────────────────────────────────────────────
async def ws_guard_admit(ws: WebSocket) -> bool:
    """Token + rate-limit gate for a NEW ``/ws`` connection. Accepts the socket, then (on a denial)
    closes it with the right application code + reason and returns False; returns True when admitted
    (the caller then reads the session config). The connection is ACCEPTED first so the browser
    receives a real close frame carrying the 4401/4429 code (a pre-accept reject is only an HTTP 403
    and the code never reaches the client)."""
    await ws.accept()
    if not token_ok(ws.query_params.get("token")):
        await ws.close(code=WS_CLOSE_UNAUTHORIZED, reason="unauthorized: missing or invalid token")
        return False
    if not _limiter.allow(ws_client_ip(ws), max_conn_per_min()):
        await ws.close(code=WS_CLOSE_RATE_LIMITED, reason="rate limited: too many connections")
        return False
    return True


def acquire_session() -> bool:
    """Reserve a live-GPU session slot if under ``VIZ2_STREAM_MAX_SESSIONS``. Call this BEFORE
    spawning Godot/Viz2Runtime; on False, refuse the connection without spawning."""
    return _sessions.acquire(max_sessions())


def release_session() -> None:
    """Free a live-GPU session slot (call in the WS teardown ``finally``)."""
    _sessions.release()
