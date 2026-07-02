"""The public landing page must be reachable straight off the backend. In prod nginx serves the apex,
but a direct /landing(.html) URL (dev server, or a proxy that forwards the path) used to fall through to
the JSON 404 handler -- a raw {"ok": false} where a marketing page was expected. The pages router closes
that gap, and the page it serves must carry the cockpit's canonical design tokens (the landing had forked
--accent/--bg values)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from stewie.server.server import app

client = TestClient(app)


def test_landing_served_at_both_direct_urls():
    for url in ("/landing", "/landing.html"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert r.headers["content-type"].startswith("text/html"), url
        assert "wordmark" in r.text and "STEWIE" in r.text, url  # the real landing, not a JSON error


def test_landing_tokens_match_the_cockpit():
    # design-token reconciliation: one brand ramp across landing + cockpit (index.html/program.html)
    html = client.get("/landing").text
    assert "--accent:#ef3a52" in html, "landing --accent must be the canonical cockpit accent"
    assert "--bg:#0a0a0c" in html, "landing --bg must be the canonical cockpit background"
    assert "#C8102E" not in html and "#0D0F11" not in html, "forked token values must be gone"
