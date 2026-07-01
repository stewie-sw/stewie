#!/usr/bin/env python3
"""Stamp the CONTENT HASH of every versioned asset into each page's cache-bust query.

Why: app.stewie.space is fronted by Cloudflare, which edge-caches /assets/*.js. The cache key is the URL,
so a CHANGED asset must get a NEW `?v=` or Cloudflare keeps serving the stale bytes (this once shipped
nothing to users for ~30 days, and again shipped a stale three3d.js). A content hash is the right
cache-bust: it changes iff the bytes change (fresh URL on every edit, stable cacheable URL when
unchanged). Replaces the error-prone manual `?v=N` bump.

The asset list is DERIVED FROM EACH PAGE (every `/assets/<name>.js?v=...` reference is stamped), not a
hand-maintained tuple: the tuple went stale in practice -- cockpit_state.js shipped with a stale hash and
adapters.js/panel_layout.js/idle_logout.js with hand labels (?v=fs15a1, ?v=1) that no gate checked, which
is exactly the stale-edge-cache failure this script exists to prevent. Reference an asset with `?v=` and
it is automatically stamped + CI-gated; nothing to register.

Run before a frontend deploy:  python scripts/stamp_cockpit_version.py
CI enforces it: stewie/server/test_asset_version_stamp.py fails if any stamp is stale, so a stale-cache
deploy can't slip through. See deploy/DEPLOY.md.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_ASSET_DIR = _ROOT / "stewie" / "server" / "web" / "assets"
INDEX_HTML = _ROOT / "stewie" / "server" / "index.html"
PROGRAM_HTML = _ROOT / "stewie" / "server" / "web" / "program.html"

#: every page that cache-busts /assets/*.js with ?v=
PAGES = (INDEX_HTML, PROGRAM_HTML)

#: an /assets/... reference with a ?v= token (group 1 = the asset path relative to assets/, group 2 = up
#: to the token). Matches nested paths (assets/panes/x.js) too.
_REF_RE = re.compile(r"assets/([A-Za-z0-9_./-]+?\.js)\?v=([A-Za-z0-9_]+)")


def content_hash(name: str) -> str:
    """Short stable content hash of an asset (the cache-bust token)."""
    return hashlib.sha256((_ASSET_DIR / name).read_bytes()).hexdigest()[:12]


def page_assets(page: pathlib.Path) -> list[str]:
    """Every asset the page references with a ?v= cache-bust, in order of first appearance."""
    seen: list[str] = []
    for m in _REF_RE.finditer(page.read_text()):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _stamp_page(page: pathlib.Path, assets: list[str] | tuple[str, ...] | None = None) -> list[tuple[str, str, bool]]:
    """Rewrite each referenced asset's ?v= in one HTML page to its current content hash.
    Returns [(name, hash, changed), ...]."""
    html = page.read_text()
    out: list[tuple[str, str, bool]] = []
    for name in (assets if assets is not None else page_assets(page)):
        rx = re.compile(r"(" + re.escape(name) + r"\?v=)([A-Za-z0-9_]+)")
        if not rx.search(html):
            raise SystemExit(f"{page.name} has no {name}?v= reference to stamp")
        h = content_hash(name)
        new = rx.sub(lambda m, h=h: m.group(1) + h, html)
        out.append((name, h, new != html))
        html = new
    page.write_text(html)
    return out


def stamp() -> list[tuple[str, str, bool]]:
    """Stamp every ?v=-referenced asset on every cache-busted page."""
    out: list[tuple[str, str, bool]] = []
    for page in PAGES:
        out += _stamp_page(page)
    return out


if __name__ == "__main__":
    for name, h, changed in stamp():
        print(f"{name} ?v={h} ({'updated page' if changed else 'already current'})")
    sys.exit(0)
