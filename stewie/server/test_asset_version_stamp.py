"""Enforce the asset cache-bust stamps. Each page references /assets/<name>.js?v=<hash>, and every such
hash MUST equal the current content hash of that asset. Cloudflare edge-caches /assets/*.js by URL, so a
changed asset with an unchanged ?v ships the STALE bytes to app.stewie.space (this happened: ~30 days of
stale JS; then again 2026-07-01 when cockpit_state.js shipped stamped with a stale hash and adapters.js/
panel_layout.js/idle_logout.js carried unchecked hand labels). The asset list is DERIVED FROM THE PAGES
(scripts/stamp_cockpit_version.page_assets), so a newly referenced ?v= asset is gated automatically --
there is no tuple to forget. If this test fails, run `python scripts/stamp_cockpit_version.py` before
deploying (deploy/DEPLOY.md)."""
import sys
from pathlib import Path

import pytest

_SCRIPTS = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
import stamp_cockpit_version as S  # noqa: E402


def _cases():
    for page in S.PAGES:
        for name in S.page_assets(page):
            yield pytest.param(page, name, id=f"{page.name}:{name}")


@pytest.mark.parametrize(("page", "name"), _cases())
def test_asset_cache_bust_matches_content_hash(page, name):
    import re

    want = S.content_hash(name)
    html = page.read_text()
    m = re.search(re.escape(name) + r"\?v=([A-Za-z0-9_]+)", html)
    assert m, f"{page.name} must cache-bust {name} with ?v=<hash>"
    assert m.group(1) == want, (
        f"stale cache-bust stamp: {page.name} has {name}?v={m.group(1)} but {name} hashes to {want}. "
        f"Run `python scripts/stamp_cockpit_version.py` (Cloudflare would otherwise serve a stale asset)."
    )


def test_every_page_references_a_nonempty_stamped_set():
    # the scan itself must keep finding the pages' assets (an empty scan would silently gate nothing)
    for page in S.PAGES:
        assert len(S.page_assets(page)) >= 2, f"{page.name}: ?v= asset scan found almost nothing"
