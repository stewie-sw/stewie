#!/usr/bin/env python3
"""Stamp the cockpit.js CONTENT HASH into index.html's <script src> cache-bust query.

Why: app.stewie.space is fronted by Cloudflare, which edge-caches /assets/*.js. The cache key is the URL,
so a CHANGED cockpit.js must get a NEW `?v=` or Cloudflare keeps serving the stale asset (this once shipped
nothing to users for ~30 days). A content hash is the right cache-bust: it changes iff the bytes change
(fresh URL on every edit, stable cacheable URL when unchanged). Replaces the error-prone manual `?v=N` bump.

Run before a frontend deploy:  python scripts/stamp_cockpit_version.py
CI enforces it: stewie/server/test_asset_version_stamp.py fails if the stamp is stale (i.e. cockpit.js
changed but nobody re-stamped), so a stale-cache deploy can't slip through. See deploy/DEPLOY.md.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
COCKPIT_JS = _ROOT / "stewie" / "server" / "web" / "assets" / "cockpit.js"
INDEX_HTML = _ROOT / "stewie" / "server" / "index.html"
_REF = re.compile(r'(cockpit\.js\?v=)([A-Za-z0-9_]+)')


def content_hash() -> str:
    """Short stable content hash of cockpit.js (the cache-bust token)."""
    return hashlib.sha256(COCKPIT_JS.read_bytes()).hexdigest()[:12]


def current_stamp(html: str) -> str | None:
    """The ?v= token currently in index.html's cockpit.js reference, or None if absent."""
    m = _REF.search(html)
    return m.group(2) if m else None


def stamp() -> tuple[str, bool]:
    """Rewrite index.html's cockpit.js ?v= to the current content hash. Returns (hash, changed)."""
    h = content_hash()
    html = INDEX_HTML.read_text()
    if not _REF.search(html):
        raise SystemExit("index.html has no cockpit.js?v= reference to stamp")
    new = _REF.sub(lambda m: m.group(1) + h, html)
    changed = new != html
    if changed:
        INDEX_HTML.write_text(new)
    return h, changed


if __name__ == "__main__":
    h, changed = stamp()
    print(f"cockpit.js ?v={h} ({'updated index.html' if changed else 'already current'})")
    sys.exit(0)
