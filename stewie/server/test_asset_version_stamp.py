"""Enforce the cockpit.js cache-bust stamp. index.html references /assets/cockpit.js?v=<hash>, and that
hash MUST equal the current cockpit.js content hash. Cloudflare edge-caches /assets/*.js by URL, so a
changed cockpit.js with an unchanged ?v ships the STALE asset to app.stewie.space (this happened: ~30 days
of stale JS). If this test fails, run `python scripts/stamp_cockpit_version.py` before deploying. The test
makes the bump impossible to forget instead of a documented hope (deploy/DEPLOY.md)."""
import hashlib
import os
import re

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ASSET_DIR = os.path.join(_HERE, "web", "assets")
_INDEX_HTML = os.path.join(_HERE, "index.html")

# every cache-busted asset referenced from index.html as `<name>?v=<hash>`
_ASSETS = ("cockpit.js", "three3d.js", "geofmt.js")


@pytest.mark.parametrize("name", _ASSETS)
def test_asset_cache_bust_matches_content_hash(name):
    with open(os.path.join(_ASSET_DIR, name), "rb") as fh:
        want = hashlib.sha256(fh.read()).hexdigest()[:12]
    with open(_INDEX_HTML) as fh:
        html = fh.read()
    m = re.search(re.escape(name) + r"\?v=([A-Za-z0-9_]+)", html)
    assert m, f"index.html must cache-bust {name} with ?v=<hash>"
    assert m.group(1) == want, (
        f"stale cache-bust stamp: index.html has {name}?v={m.group(1)} but {name} hashes to {want}. "
        f"Run `python scripts/stamp_cockpit_version.py` (Cloudflare would otherwise serve a stale asset)."
    )


# the standalone /program board page cache-busts its own module set the same way
_PROGRAM_HTML = os.path.join(_HERE, "web", "program.html")
_PROGRAM_ASSETS = ("htmlesc.js", "program_board.js")


@pytest.mark.parametrize("name", _PROGRAM_ASSETS)
def test_program_page_cache_bust_matches_content_hash(name):
    with open(os.path.join(_ASSET_DIR, name), "rb") as fh:
        want = hashlib.sha256(fh.read()).hexdigest()[:12]
    with open(_PROGRAM_HTML) as fh:
        html = fh.read()
    m = re.search(re.escape(name) + r"\?v=([A-Za-z0-9_]+)", html)
    assert m, f"program.html must cache-bust {name} with ?v=<hash>"
    assert m.group(1) == want, (
        f"stale cache-bust stamp: program.html has {name}?v={m.group(1)} but {name} hashes to {want}. "
        f"Run `python scripts/stamp_cockpit_version.py` (Cloudflare would otherwise serve a stale asset)."
    )
