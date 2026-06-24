"""Batch (2026-06-15 live-review): ConOps tab flow, gated app (no public app link), admin per-user
login history. Fast static + unit guards; the gate's dynamic behaviour is in scripts/ux_a11y_smoke.py.
"""
from __future__ import annotations

import json
import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_INDEX = os.path.join(_ROOT, "stewie", "server", "index.html")
_LANDING = os.path.join(_ROOT, "stewie", "server", "web", "landing.html")


def _read(p):
    with open(p) as f:
        return f.read()


def test_tab_flow_order_plan_rehearse_validate_execute_report():
    order = re.findall(r'data-view="([a-z]+)"', _read(_INDEX))
    # ConOps spine (cockpit reorg 2026-06-23): Plan -> Rehearse -> Validate -> Execute -> Report. Validate
    # merges the former Navigation + Perception tabs into one tab + a sub-tab strip (data-sub="nav|perception"),
    # so nav/perception are no longer top-level data-view tabs; Execute keeps data-view "metrics" (relabeled).
    assert order[:5] == ["plan", "rehearse", "validate", "metrics", "report"], \
        f"tab flow is {order[:5]}, expected the ConOps spine plan->rehearse->validate->execute(metrics)->report"


def test_landing_has_no_direct_app_link():
    # gated app: the public landing must not advertise/reach the cockpit (access via /app + sign-in only)
    assert 'href="/app"' not in _read(_LANDING), "the public landing still links directly to /app"


def test_events_actor_filter_gives_per_user_login_history(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWIE_DATA_DIR", str(tmp_path))
    rows = [
        {"ts": 1.0, "actor": "alice@x.com", "action": "auth.login", "target": "password"},
        {"ts": 2.0, "actor": "bob@x.com", "action": "auth.login", "target": "password"},
        {"ts": 3.0, "actor": "alice@x.com", "action": "auth.register", "target": "pending"},
        {"ts": 4.0, "actor": "alice@x.com", "action": "auth.login", "target": "password"},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    from stewie.server.routers.operators_admin import get_events
    out = get_events(n=50, actor="alice@x.com", action="auth.login", _auth="director")["events"]
    assert len(out) == 2, f"expected 2 alice logins, got {len(out)}"
    assert all(e["actor"] == "alice@x.com" and e["action"] == "auth.login" for e in out)
    assert out[0]["ts"] == 4.0 and out[1]["ts"] == 1.0, "events must be newest-first"
    # unfiltered keeps the full recent tail (back-compat)
    allout = get_events(n=50, _auth="director")["events"]
    assert len(allout) == 4
