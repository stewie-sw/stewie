"""[REQ:] Security guard for the PUBLIC viz2 pixel-stream — token / concurrency-cap / rate-limit.

Gate on exit code: pytest stewie/stream/test_security.py

Each guard is exercised for REAL enforcement, not decoration:
  * token   — GET / and GET /bundles + the WS require a matching ?token when VIZ2_STREAM_TOKEN is set
              (401 / WS 4401 on missing-or-wrong, 200 / ready on correct); UNSET -> open as before;
  * cap     — with MAX_SESSIONS=1 an occupied slot refuses the next WS "at capacity" WITHOUT spawning,
              and the slot is freed on disconnect (a fresh session is admitted again);
  * rate    — with a low MAX_CONN_PER_MIN the (limit+1)th new connection -> HTTP 429 / WS close.

The GPU-spawning parts of a live session (StreamSession.start + the Godot frame pumps) are patched out
so these tests run headless; the guard logic (accept/admit, the real session counter, the real sliding
window, the real disconnect->release teardown) is what is under test. The full Godot loop is covered by
the opt-in e2e (STEWIE_STREAM_E2E=1).
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from stewie.stream import app as app_mod
from stewie.stream import security

app = app_mod.app

TOKEN = "sekret-abc123"
CFG = {"mode": "real", "site": "haworth_sfs_2km_1m"}


# ── helpers ───────────────────────────────────────────────────────────────────────────────────
def _patch_session_no_gpu(monkeypatch, started: list | None = None) -> None:
    """Isolate the GPU: StreamSession.start spawns NOTHING, the frame pump parks (cancellable), and
    the input pump runs a real receive loop so a client disconnect still raises WebSocketDisconnect
    (driving the real teardown->release path). The guard/counter/window logic stays REAL."""
    async def _start(self, *, connect_timeout: float = 90.0) -> None:
        if started is not None:
            started.append(1)

    async def _frames(self, ws) -> None:
        await asyncio.Event().wait()          # park until cancelled by teardown

    async def _input(self, ws) -> None:
        while True:
            await ws.receive_text()           # raises WebSocketDisconnect on client close

    monkeypatch.setattr(app_mod.StreamSession, "start", _start)
    monkeypatch.setattr(app_mod.StreamSession, "pump_frames", _frames)
    monkeypatch.setattr(app_mod.StreamSession, "pump_input", _input)


def _wait_until(pred, timeout: float = 5.0, interval: float = 0.02) -> bool:
    t0 = time.monotonic()
    while not pred() and time.monotonic() - t0 < timeout:
        time.sleep(interval)
    return pred()


# ── unit: sliding-window limiter ────────────────────────────────────────────────────────────────
def test_sliding_window_limiter_allows_up_to_limit_then_denies():
    lim = security.SlidingWindowLimiter(window_s=60.0)
    t = 1000.0
    assert lim.allow("ip", 3, now=t) is True
    assert lim.allow("ip", 3, now=t) is True
    assert lim.allow("ip", 3, now=t) is True
    assert lim.allow("ip", 3, now=t) is False           # (limit+1)th within the window -> denied
    assert lim.allow("other", 3, now=t) is True          # a different key has its own budget
    assert lim.allow("ip", 3, now=t + 61.0) is True      # the window slid past -> budget refilled


# ── unit: session counter ─────────────────────────────────────────────────────────────────────
def test_session_counter_caps_releases_and_never_negative():
    c = security.SessionCounter()
    assert c.acquire(2) is True
    assert c.acquire(2) is True
    assert c.acquire(2) is False                          # at cap
    assert c.count == 2
    c.release()
    assert c.count == 1
    assert c.acquire(2) is True                           # freed slot is reusable
    c.reset()
    assert c.count == 0
    c.release()                                           # release below zero is a no-op
    assert c.count == 0


# ── unit: token + client-ip ───────────────────────────────────────────────────────────────────
def test_token_ok_is_open_when_unset(monkeypatch):
    monkeypatch.delenv(security.ENV_TOKEN, raising=False)
    assert security.token_ok(None) is True
    assert security.token_ok("anything") is True


def test_token_ok_constant_time_match(monkeypatch):
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    assert security.token_ok(TOKEN) is True
    assert security.token_ok("wrong-but-samelen") is False
    assert security.token_ok("") is False
    assert security.token_ok(None) is False


def test_client_ip_prefers_forwarded_for():
    from starlette.datastructures import Headers

    class _Client:
        host = "10.0.0.1"

    with_xff = Headers({"x-forwarded-for": "203.0.113.7, 70.1.2.3"})
    assert security._client_ip_from(with_xff, _Client()) == "203.0.113.7"   # Cloudflare's real client
    no_xff = Headers({})
    assert security._client_ip_from(no_xff, _Client()) == "10.0.0.1"        # socket peer fallback
    assert security._client_ip_from(no_xff, None) == "-"


# ── token gate ON: HTTP ───────────────────────────────────────────────────────────────────────
def test_http_root_requires_token(monkeypatch):
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    client = TestClient(app)
    assert client.get("/").status_code == 401
    assert client.get("/?token=wrong").status_code == 401
    r = client.get(f"/?token={TOKEN}")
    assert r.status_code == 200
    assert b"STEWIE viz2" in r.content


def test_http_bundles_requires_token(monkeypatch):
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    client = TestClient(app)
    assert client.get("/bundles").status_code == 401
    assert client.get("/bundles?token=wrong").status_code == 401
    r = client.get(f"/bundles?token={TOKEN}")
    assert r.status_code == 200
    assert "bundles" in r.json()


def test_single_token_link_works_across_every_surface(monkeypatch):
    """One https://host/?token=T link must carry through the whole setup->preview->stream chain: the
    setup page, both preview data routes, and the /stream view all admit WITH the token and 401
    WITHOUT it (the WS leg is covered by test_ws_correct_token_admitted)."""
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    client = TestClient(app)
    q = f"token={TOKEN}"
    surfaces = [
        "/",
        "/stream",
        "/bundles",
        "/preview/heightmap?site=haworth_sfs_2km_1m",
        "/preview/procedural?seed=1",
    ]
    for path in surfaces:
        sep = "&" if "?" in path else "?"
        assert client.get(path).status_code == 401, f"{path} should require a token"
        assert client.get(f"{path}{sep}{q}").status_code == 200, f"{path} should admit with the token"


def test_healthz_and_vendor_exempt_from_token(monkeypatch):
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200                        # readiness probe exempt
    assert client.get("/vendor/three.module.min.js").status_code == 200     # ES-module asset exempt


# ── token gate ON: WS ─────────────────────────────────────────────────────────────────────────
def test_ws_missing_or_wrong_token_closed_4401(monkeypatch):
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
    assert ei.value.code == security.WS_CLOSE_UNAUTHORIZED
    with pytest.raises(WebSocketDisconnect) as ei2:
        with client.websocket_connect("/ws?token=wrong") as ws:
            ws.receive_text()
    assert ei2.value.code == security.WS_CLOSE_UNAUTHORIZED


def test_ws_correct_token_admitted(monkeypatch):
    monkeypatch.setenv(security.ENV_TOKEN, TOKEN)
    _patch_session_no_gpu(monkeypatch)
    client = TestClient(app)
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        ws.send_json(CFG)
        assert ws.receive_json()["type"] == "ready"


# ── token UNSET: existing behavior unchanged (tailnet mode) ───────────────────────────────────
def test_token_unset_leaves_http_open(monkeypatch):
    monkeypatch.delenv(security.ENV_TOKEN, raising=False)
    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/bundles").status_code == 200


def test_token_unset_leaves_ws_open(monkeypatch):
    monkeypatch.delenv(security.ENV_TOKEN, raising=False)
    _patch_session_no_gpu(monkeypatch)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:          # no token required
        ws.send_json(CFG)
        assert ws.receive_json()["type"] == "ready"


# ── concurrency cap ───────────────────────────────────────────────────────────────────────────
def test_ws_refused_at_capacity_without_spawning(monkeypatch):
    monkeypatch.setenv(security.ENV_MAX_SESSIONS, "1")
    started: list = []

    async def _start(self, *, connect_timeout: float = 90.0) -> None:
        started.append(1)

    monkeypatch.setattr(app_mod.StreamSession, "start", _start)
    # occupy the single slot as if a live session holds the GPU
    assert security.acquire_session() is True
    try:
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.send_json(CFG)
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "capacity" in msg["error"].lower()
            with pytest.raises(WebSocketDisconnect) as ei:
                ws.receive_json()
            assert ei.value.code == security.WS_CLOSE_AT_CAPACITY
        assert started == []                              # the refused connection spawned NOTHING
    finally:
        security.release_session()


def test_ws_slot_freed_on_disconnect(monkeypatch):
    monkeypatch.setenv(security.ENV_MAX_SESSIONS, "1")
    _patch_session_no_gpu(monkeypatch)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws1:
        ws1.send_json(CFG)
        assert ws1.receive_json()["type"] == "ready"
        assert security.current_sessions() == 1           # slot reserved while the session is live
    # ws1 disconnected on block exit -> the teardown finally must release the slot
    assert _wait_until(lambda: security.current_sessions() == 0), "slot not freed on disconnect"
    with client.websocket_connect("/ws") as ws2:          # the freed slot is reusable
        ws2.send_json(CFG)
        assert ws2.receive_json()["type"] == "ready"


# ── rate-limit ────────────────────────────────────────────────────────────────────────────────
def test_http_rate_limit_429_on_limit_plus_one(monkeypatch):
    monkeypatch.setenv(security.ENV_MAX_CONN_PER_MIN, "3")
    client = TestClient(app)                               # token unset -> rate-limit is independent
    for _ in range(3):
        assert client.get("/").status_code == 200
    assert client.get("/").status_code == 429             # the (limit+1)th connection


def test_preview_and_bundles_data_xhrs_are_not_rate_limited(monkeypatch):
    # the intra-page data routes are token-gated but NOT rate-limited (so preview scrubbing is fluid)
    monkeypatch.setenv(security.ENV_MAX_CONN_PER_MIN, "2")
    client = TestClient(app)
    for _ in range(5):
        assert client.get("/preview/procedural?seed=1").status_code == 200


def test_ws_rate_limit_closes_on_limit_plus_one(monkeypatch):
    monkeypatch.setenv(security.ENV_MAX_CONN_PER_MIN, "2")
    _patch_session_no_gpu(monkeypatch)
    client = TestClient(app)
    for _ in range(2):                                     # two new connections consume the budget
        with client.websocket_connect("/ws") as ws:
            ws.send_json(CFG)
            assert ws.receive_json()["type"] == "ready"    # full admit ran -> the hit was recorded
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
    assert ei.value.code == security.WS_CLOSE_RATE_LIMITED
