"""Enforce the cockpit.js cache-bust stamp. index.html references /assets/cockpit.js?v=<hash>, and that
hash MUST equal the current cockpit.js content hash. Cloudflare edge-caches /assets/*.js by URL, so a
changed cockpit.js with an unchanged ?v ships the STALE asset to app.stewie.space (this happened: ~30 days
of stale JS). If this test fails, run `python scripts/stamp_cockpit_version.py` before deploying. The test
makes the bump impossible to forget instead of a documented hope (deploy/DEPLOY.md)."""
import hashlib
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_COCKPIT_JS = os.path.join(_HERE, "web", "assets", "cockpit.js")
_INDEX_HTML = os.path.join(_HERE, "index.html")


def test_cockpit_js_cache_bust_matches_content_hash():
    with open(_COCKPIT_JS, "rb") as fh:
        want = hashlib.sha256(fh.read()).hexdigest()[:12]
    with open(_INDEX_HTML) as fh:
        html = fh.read()
    m = re.search(r"cockpit\.js\?v=([A-Za-z0-9_]+)", html)
    assert m, "index.html must cache-bust cockpit.js with ?v=<hash>"
    assert m.group(1) == want, (
        f"stale cache-bust stamp: index.html has ?v={m.group(1)} but cockpit.js hashes to {want}. "
        f"Run `python scripts/stamp_cockpit_version.py` (Cloudflare would otherwise serve a stale asset)."
    )
