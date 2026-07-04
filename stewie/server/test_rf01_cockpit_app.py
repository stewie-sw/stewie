"""[REQ:RF-01] the React cockpit shell: its 13 pane identities match the vanilla cockpit EXACTLY, and the
backend serves it at /app (SPA fallback) while the vanilla cockpit stays authoritative at / (strangler-fig,
ADR-0007). The pane-parity check is source-parsed (no build needed); the /app route is exercised in whatever
state the tree is in (built -> serves the shell; not built -> 404 fail-closed, vanilla unaffected)."""
import os
import re

from fastapi.testclient import TestClient

from stewie.server.server import app

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _vanilla_pane_ids() -> set[str]:
    with open(os.path.join(_ROOT, "stewie", "server", "index.html"), encoding="utf-8") as fh:
        return set(re.findall(r'data-view="([a-z-]+)"', fh.read()))


def _react_pane_ids() -> set[str]:
    with open(os.path.join(_ROOT, "frontend", "src", "panes.ts"), encoding="utf-8") as fh:
        return set(re.findall(r'id:\s*"([a-z-]+)"', fh.read()))


def test_rf01_react_shell_has_the_same_13_pane_identities_as_vanilla():  # [REQ:RF-01]
    react, vanilla = _react_pane_ids(), _vanilla_pane_ids()
    assert len(react) == 13, f"expected 13 React panes, got {sorted(react)}"
    assert react == vanilla, f"pane identity drift React vs vanilla: {react ^ vanilla}"


def test_rf01_app_route_serves_shell_when_built_else_404_and_vanilla_stays_up():  # [REQ:RF-01]
    client = TestClient(app, raise_server_exceptions=False)
    built = os.path.isfile(os.path.join(_ROOT, "frontend", "dist", "index.html"))
    r_app = client.get("/app")
    r_route = client.get("/app/plan")   # a client-side route -> SPA fallback to index.html
    if built:
        assert r_app.status_code == 200 and "<div id=\"root\">" in r_app.text
        assert r_route.status_code == 200 and "<div id=\"root\">" in r_route.text   # SPA fallback
    else:
        assert r_app.status_code == 404   # fail-closed when the vite build is absent
    assert client.get("/").status_code == 200   # the vanilla cockpit is always served (strangler-fig)
