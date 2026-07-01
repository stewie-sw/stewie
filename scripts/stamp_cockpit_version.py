#!/usr/bin/env python3
"""Stamp the CONTENT HASH of each versioned cockpit asset into index.html's <script src> cache-bust query.

Why: app.stewie.space is fronted by Cloudflare, which edge-caches /assets/*.js. The cache key is the URL,
so a CHANGED asset must get a NEW `?v=` or Cloudflare keeps serving the stale bytes (this once shipped
nothing to users for ~30 days, and again shipped a stale three3d.js). A content hash is the right
cache-bust: it changes iff the bytes change (fresh URL on every edit, stable cacheable URL when
unchanged). Replaces the error-prone manual `?v=N` bump.

Covers every asset in ASSETS -- add a file here (and reference it as `name?v=...` in index.html) when a
new cache-busted asset is introduced.

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

#: cache-busted assets referenced from index.html as `<name>?v=<hash>`.
ASSETS = ("cockpit.js", "three3d.js", "geofmt.js", "globe_ellipsoid.js",
          "htmlesc.js", "icons.js", "role_rank.js", "keepout_geom.js",
          "navplot.js", "evidence_html.js", "rover_hud.js", "plan_geom.js",
          "footprint_geom.js",
          "fleet_render.js", "rehearse_render.js", "construction_render.js", "models_render.js",
          "plan_stepper.js", "contents_tree.js", "trainer_boards.js", "world_state_html.js",
          "regolith_estimate.js", "scorecard_chips.js", "terrain_memory_html.js", "nav_stats_html.js",
          "layouts.js")

#: cache-busted assets referenced from the standalone /program board page.
PROGRAM_ASSETS = ("htmlesc.js", "program_board.js")


def content_hash(name: str) -> str:
    """Short stable content hash of an asset (the cache-bust token)."""
    return hashlib.sha256((_ASSET_DIR / name).read_bytes()).hexdigest()[:12]


def _ref(name: str) -> re.Pattern[str]:
    return re.compile(r"(" + re.escape(name) + r"\?v=)([A-Za-z0-9_]+)")


def _stamp_page(page: pathlib.Path, assets: tuple[str, ...]) -> list[tuple[str, str, bool]]:
    """Rewrite each asset's ?v= in one HTML page to its current content hash.
    Returns [(name, hash, changed), ...]."""
    html = page.read_text()
    out: list[tuple[str, str, bool]] = []
    for name in assets:
        rx = _ref(name)
        if not rx.search(html):
            raise SystemExit(f"{page.name} has no {name}?v= reference to stamp")
        h = content_hash(name)
        new = rx.sub(lambda m, h=h: m.group(1) + h, html)
        out.append((name, h, new != html))
        html = new
    page.write_text(html)
    return out


def stamp() -> list[tuple[str, str, bool]]:
    """Stamp every cache-busted page (the cockpit's index.html + the /program board)."""
    return _stamp_page(INDEX_HTML, ASSETS) + _stamp_page(PROGRAM_HTML, PROGRAM_ASSETS)


if __name__ == "__main__":
    for name, h, changed in stamp():
        print(f"{name} ?v={h} ({'updated page' if changed else 'already current'})")
    sys.exit(0)
