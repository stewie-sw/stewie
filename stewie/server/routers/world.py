"""World-state authority route (FS-02 / TW-05, §25 Phase 1). Returns the typed WorldState DESCRIPTOR
for a site -- the grid geometry (rows/cols/cell_m), the lunar datum, and provenance (a dart.dem_sources
id) the cockpit + planner reason over. The raw rasters live in the twin/DEM store; this is the typed
metadata. observed_fraction/mutated keep their contract defaults here (enriched from the twin in a later
brick). Public read. Delegates to server.state.moon_dem; no app-module import (no cycle)."""
from __future__ import annotations

import os

import numpy as np
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from stewie.contracts import WorldState
from stewie.server import state as S
from stewie.specs.sites import SITES

router = APIRouter()

# site -> dart.dem_sources id, derived from the imported-bundle registry so EVERY imported site reports
# its real bundle id as provenance (not just Haworth). The bundle dir basename IS the dem_sources id
# (e.g. nobile_rim -> nobile_rim1_10km_5m), so a newly imported site is wired automatically.
_SITE_SOURCE = {name: os.path.basename(s.bundle_dir) for name, s in SITES.items() if s.bundle_dir}


@router.get("/world")
def world(site: str = "haworth"):
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
