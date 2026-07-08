"""FS-19: audit-ledger coverage per mutating route. Every route registered with a mutating HTTP method
(POST/PUT/DELETE/PATCH) must record a semantic audit event (services.log_event), and the event must land
in events.jsonl carrying the request's correlation id end-to-end (inbound X-Correlation-Id header ->
middleware ContextVar -> ledger record -> the director /events viewer). The route walk is ENUMERATED
from the live app -- no hand-kept route list -- so a NEW mutating route shipped without ledger coverage
fails here by construction.

Run: PYTHONPATH=. <venv>/bin/python -m pytest stewie/server/test_audit_route_coverage.py -q
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import types

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import stewie.server.server as _srv

_MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
# the catch-all 404 envelope (server.py _no_post) matches only UNROUTED paths and mutates nothing (a rejection
# surface, not a command surface); /world/points + /world/transect are POST *only* to carry a coordinate-list
# body -- they are the read-only batch siblings of GET /world/point (per-cell map-data queries) and mutate
# nothing, so they belong out of the mutating-route ledger walk exactly like the GET reader. [council #55]
_EXEMPT_PATHS = {"/{path:path}", "/world/points", "/world/transect"}


def _flatten(routes) -> list:
    """Depth-first APIRoute walk. FastAPI includes routers lazily (_IncludedRouter wraps the original
    APIRouter), so app.routes must be recursed through original_router to reach the real endpoints."""
    out = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        else:
            inner = getattr(getattr(r, "original_router", None), "routes", None)
            if inner:
                out.extend(_flatten(inner))
    return out


def _mutating_routes() -> list:
    out = []
    for r in _flatten(_srv.app.routes):
        if r.path not in _EXEMPT_PATHS:
            for m in sorted((r.methods or set()) & _MUTATING_METHODS):
                out.append((m, r.path, r.endpoint))
    return sorted(out, key=lambda t: (t[1], t[0]))


_ROUTES = _mutating_routes()


def _calls_log_event(fn) -> bool:
    """True when the endpoint's own code -- or a function/comprehension nested inside it -- names
    services.log_event. Static reachability, so a conditional call (log-on-success) still counts."""
    stack, seen = [inspect.unwrap(fn).__code__], set()
    while stack:
        c = stack.pop()
        if id(c) in seen:
            continue
        seen.add(id(c))
        if "log_event" in c.co_names:
            return True
        stack.extend(k for k in c.co_consts if isinstance(k, types.CodeType))
    return False


def test_the_route_walk_found_the_real_surface():  # [REQ:FS-19]
    """Guard the enumeration itself: the app serves dozens of mutating routes; a refactor that silently
    emptied the walk would make the parametrized coverage test below pass vacuously."""
    assert len(_ROUTES) >= 50, sorted(p for _, p, _ in _ROUTES)


@pytest.mark.parametrize(("method", "path", "endpoint"), _ROUTES,
                         ids=[f"{m}-{p}" for m, p, _ in _ROUTES])
def test_every_mutating_route_records_an_audit_event(method, path, endpoint):  # [REQ:FS-19]
    assert _calls_log_event(endpoint), (
        f"{method} {path} ({endpoint.__module__}.{endpoint.__name__}) never calls services.log_event -- "
        "FS-19 requires every mutating/command route to land in the audit ledger")


# ---- dynamic tier: one REAL request per FS-19 event class, correlation id asserted end-to-end -----

@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("STEWIE_API_KEY", "test-key")
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWIE_BACKUP_DIR", str(tmp_path / "replica"))
    monkeypatch.setenv("STEWIE_ALLOWED_OPERATORS", "fs19-operator@example.com")
    # SF-02: the rc.goto coverage row posts a MISSION-LESS GoTo, so pin an explicit dev/bench teleop
    # posture (the SF-02 authority decision itself is covered in test_rc_command_authority.py).
    monkeypatch.setenv("STEWIE_RUNNABLE_PROFILE", "bench")
    monkeypatch.setenv("STEWIE_ALLOW_TELEOP", "1")
    import stewie.server.server as srv
    importlib.reload(srv)
    yield TestClient(srv.app)
    monkeypatch.undo()
    importlib.reload(srv)


H = {"X-API-Key": "test-key"}


def _events(tmp_path):
    p = os.path.join(str(tmp_path), "events.jsonl")
    return [json.loads(ln) for ln in open(p).read().splitlines()] if os.path.exists(p) else []


_MISSION = {"name": "fs19", "body": "moon", "charger": [0, 0], "orders": [
    {"action": "a", "kind": "cut", "x": 12, "y": 0, "footprint_m2": 16, "depth_m": 0.05},
    {"action": "b", "kind": "fill", "x": 30, "y": 8, "footprint_m2": 16, "depth_m": 0.05}]}

# (method, path, payload, expected ledger action) -- representatives for every FS-19 event class:
# role/permission check, operator action, maintenance op, safety event, mission decision, backend
# contract call, plan/replan, command gate, training session. Mixed NEW + pre-existing instrumentation
# so the correlation-id threading is proven across both.
_CASES = [
    ("POST", "/auth/login", {"email": "fs19-operator@example.com"}, "auth.login"),
    ("POST", "/auth/logout", {}, "auth.logout"),
    ("POST", "/profile", {"name": "fs19 profile", "profile": {"body": "moon"}}, "profile.save"),
    ("PUT", "/draft", {"body": "moon", "orders": [{"x": 3, "y": 4, "kind": "fill"}]}, "draft.save"),
    ("POST", "/admin/twin/snapshot", {}, "admin.twin.snapshot"),
    ("POST", "/nav/faults", {"tip_margin_deg": -1.0, "battery_frac": 0.5}, "nav.faults"),
    ("POST", "/nav/local_plan", {"pose": [0, 0], "heading_rad": 0.0, "goal": [20, 0]}, "nav.local_plan"),
    ("POST", "/gis/query", {"featurecollection": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
         "properties": {"feature": "order", "kind": "cut"}}]}, "feature": "order"}, "gis.query"),
    ("POST", "/plan/commands", _MISSION, "plan.commands"),
    ("POST", "/rc/command", {"kind": "goto", "leg_id": 1, "goal_row": 0.0, "goal_col": 8.0,
                             "v_max_mps": 0.3}, "rc.goto"),
    ("POST", "/session/start", {**_MISSION, "profile": "ideal"}, "session.start"),
]


@pytest.mark.parametrize(("method", "path", "payload", "action"), _CASES,
                         ids=[c[3] for c in _CASES])
def test_the_event_lands_with_the_request_correlation_id(client, tmp_path, method, path,
                                                         payload, action):  # [REQ:FS-19]
    if action == "rc.goto":
        # SF-01: the watchdog is a module-lifetime singleton (it survives the server reload), so an
        # earlier test's feed leaves the link stale / safed here. The deliberate operator re-arm is the
        # sanctioned reset -- exactly what a real cockpit does before commanding motion again.
        assert client.post("/rc/command", json={"kind": "rearm"}, headers=H).status_code == 200
    cid = f"fs19-{action}"
    r = client.request(method, path, json=payload, headers={**H, "X-Correlation-Id": cid})
    assert r.status_code == 200, f"{method} {path}: {r.text}"
    assert r.headers.get("x-correlation-id") == cid          # FS-19: the id is handed back to the client
    recs = [e for e in _events(tmp_path) if e.get("action") == action]
    assert recs, f"{method} {path} returned 200 but wrote no {action!r} event to the audit ledger"
    assert recs[-1].get("correlation_id") == cid, \
        f"the {action!r} event did not inherit the request correlation id"
    assert recs[-1].get("actor"), f"the {action!r} event carries no actor identity"


def test_the_admin_events_pane_surfaces_the_correlation_id(client, tmp_path):  # [REQ:FS-19]
    """Cockpit surfacing: the director /events viewer (Admin pane) returns the ledger records WITH their
    correlation ids, so an operator action can be traced from the UI back through the whole request."""
    cid = "fs19-events-pane"
    r = client.post("/profile", json={"name": "pane", "profile": {}},
                    headers={**H, "X-Correlation-Id": cid})
    assert r.status_code == 200, r.text
    d = client.get("/events?n=20", headers=H).json()
    assert d["ok"]
    ev = next((e for e in d["events"] if e.get("action") == "profile.save"), None)
    assert ev is not None, "the /events pane does not show the profile.save audit event"
    assert ev.get("correlation_id") == cid
