"""World-state authority route (FS-02 / TW-05, §25 Phase 1). Returns the typed WorldState DESCRIPTOR
for a site -- the grid geometry (rows/cols/cell_m), the lunar datum, and provenance (a dart.dem_sources
id) the cockpit + planner reason over. The raw rasters live in the twin/DEM store; this is the typed
metadata. observed_fraction/mutated keep their contract defaults here (enriched from the twin in a later
brick). Public read. Delegates to server.state.moon_dem; no app-module import (no cycle)."""
from __future__ import annotations

import io
import os
from dataclasses import asdict

import numpy as np
from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from stewie.contracts import WorldState
from stewie.server import state as S
from stewie.server.deps import require_auth
from stewie.specs.sites import SITES

router = APIRouter()

# site -> dart.dem_sources id, derived from the imported-bundle registry so EVERY imported site reports
# its real bundle id as provenance (not just Haworth). The bundle dir basename IS the dem_sources id
# (e.g. nobile_rim -> nobile_rim1_10km_5m), so a newly imported site is wired automatically.
_SITE_SOURCE = {name: os.path.basename(s.bundle_dir) for name, s in SITES.items() if s.bundle_dir}


@router.get("/world")
def world(site: str = "haworth", _auth: str = Depends(require_auth)):
    """FS-02 / TW-05: the typed WorldState descriptor for `site` (grid geometry + lunar datum +
    provenance). 404 if the site's DEM bundle is absent (degraded mode)."""
    dem, _anchor = S.moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    arr = np.asarray(base)
    rows, cols = int(arr.shape[0]), int(arr.shape[1])
    cell_m = float(dem[1]) if (isinstance(dem, tuple) and len(dem) >= 2 and dem[1]) else 5.0
    w = WorldState(rows=rows, cols=cols, cell_m=cell_m, dem_source=_SITE_SOURCE.get(site, site))
    return {"ok": True, "world": w.model_dump()}


@router.get("/world/transaction")
def world_transaction(_auth: str = Depends(require_auth)):
    """Gap A1 / DT-01: the single most recent consistent linked world-state transaction -- the one
    query that returns the conserved authority, observed twin, plan, and belief as ONE snapshot (not
    four independent reads). ``committed: False`` before any transition has been recorded. Auth-gated."""
    wss = S.world_state_service()
    if wss.transaction_count() == 0:
        return {"ok": True, "committed": False, "count": 0}
    return {"ok": True, "committed": True, "count": wss.transaction_count(),
            "transaction": asdict(wss.latest())}


@router.get("/world/transactions")
def world_transactions(limit: int = 50, _auth: str = Depends(require_auth)):
    """Gap A1 / FS-04: the recent linked world-state transactions (chronological) -- the world/execution
    timeline the cockpit Report pane renders (each entry's provenance carries plan/terrain/resync/leg/
    safe and its outcome). Auth-gated; ``limit`` clamped to [1, 500]."""
    lim = max(1, min(500, int(limit)))
    wss = S.world_state_service()
    return {"ok": True, "count": wss.transaction_count(), "transactions": wss.recent(lim)}


# --- CurrentTerrainView provenance (gap A2 viz): measured vs remembered vs modeled terrain -----------
from stewie.twin.terrain_view import CurrentTerrainView  # noqa: E402  (co-located with the routes below)

_PROV_COLORS = np.array([[90, 90, 90],          # PRISTINE  -> gray (modeled)
                         [40, 110, 220],        # AS_BUILT  -> blue (remembered build)
                         [40, 190, 90]],        # OBSERVED  -> green (measured)
                        dtype=np.uint8)


def _block_max_classes(src: np.ndarray, max_px: int) -> np.ndarray:
    """Downsample the class map to <= max_px on the long side by BLOCK-MAX, so a small measured/built
    region (a higher class) survives instead of being averaged away by a plain thumbnail."""
    r, c = src.shape
    factor = max(1, int(np.ceil(max(r, c) / max(1, max_px))))
    if factor == 1:
        return src
    pr, pc = (-r) % factor, (-c) % factor
    padded = np.pad(src, ((0, pr), (0, pc)), constant_values=CurrentTerrainView.PRISTINE)
    rr, cc = padded.shape
    return padded.reshape(rr // factor, factor, cc // factor, factor).max(axis=(1, 3))


@router.get("/world/terrain_view")
def world_terrain_view(site: str = "haworth", _auth: str = Depends(require_auth)):
    """Gap A2 viz: the per-cell provenance of the composed planning surface (CurrentTerrainView) -- how
    many cells are PRISTINE (modeled) / AS_BUILT (remembered build) / OBSERVED (measured resync), plus
    the as-built version, observed twin version, and observed fraction. Auth-gated; 404 if the DEM is
    absent. No fabricated terrain -- read from the live TerrainMemory + observed twin."""
    dem, origin = S.moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    view = S.current_terrain_view(site, dem, origin)
    src = np.asarray(view.source)
    return {"ok": True, "site": site, "provenance": {
        "as_built_version": view.as_built_version, "twin_version": view.twin_version,
        "observed_fraction": view.observed_fraction, "cell_m": view.cell_m,
        "rows": int(src.shape[0]), "cols": int(src.shape[1]),
        "cells": {"pristine": int(np.count_nonzero(src == CurrentTerrainView.PRISTINE)),
                  "as_built": int(np.count_nonzero(src == CurrentTerrainView.AS_BUILT)),
                  "observed": int(np.count_nonzero(src == CurrentTerrainView.OBSERVED))}}}


@router.get("/world/terrain_view.png")
def world_terrain_view_png(site: str = "haworth", max_px: int = 512,
                           _auth: str = Depends(require_auth)):
    """Gap A2 viz: the CurrentTerrainView source map as a colored raster -- PRISTINE gray / AS_BUILT
    blue / OBSERVED green -- downsampled by class-max so small measured/built regions survive. Auth-
    gated; 404 if the DEM is absent."""
    dem, origin = S.moon_dem(site)
    base = dem[0] if isinstance(dem, tuple) else dem
    if base is None:
        return JSONResponse(status_code=404, content={"ok": False, "error": f"no DEM bundle for site {site!r}"})
    from PIL import Image
    view = S.current_terrain_view(site, dem, origin)
    src = _block_max_classes(np.asarray(view.source, dtype=np.uint8), max(16, min(int(max_px), 2048)))
    rgb = _PROV_COLORS[np.clip(src, 0, 2)]
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-cache"})
